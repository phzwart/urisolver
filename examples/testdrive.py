#!/usr/bin/env python3
"""Ship a URI to a worker process and deliver a local file.

The worker does not branch on scheme. It establishes access with ``resolve``
(no bulk transfer), then delivers bytes with ``materialize(FileDestination)``.

Two stories, same worker:

1. A file on local disc (``file:``).
2. The single-file Zenodo record ``https://zenodo.org/records/23025715``,
   which is ``pdb_cells.duckdb`` (54,538,240 bytes,
   md5 ``cdabd111595d9fcd5a3700603063f7aa``).

What a successful delivery reports (Tier 0):

- ``resource.uri`` is the shipped URI
- ``info().kind`` is ``file``, ``info().exists`` is true, ``info().size_bytes``
  is the byte length
- ``supports("info")`` and ``supports("materialize")`` are true
- ``materialize(FileDestination).value`` is a path whose bytes are the resource
- ``form`` is ``path``, ``source_uri`` is the shipped URI
- ``is_reference`` is false, ``strategy`` is ``"native"``
- ``result.size_bytes`` matches ``info().size_bytes``

``MemoryDestination()`` is the other Tier 0 delivery. The local story requests
it (``--memory``). The Zenodo story does not pull the 52 MiB object into memory;
the staged file's MD5 is the check.

The Zenodo resolver is example-only. It is not a package entry point.
``resolve`` fetches the record JSON. ``materialize`` streams the one file and
rejects the result when the size or MD5 does not match the record.

Run both stories::

    python examples/testdrive.py

Worker mode (URI arrives as an argument)::

    python examples/testdrive.py --worker URI DEST [--memory] [--exchange-fd N]

``--exchange-fd`` is an inherited byte stream. The public stories leave it unset.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from urisolver import (  # noqa: E402
    Context,
    FileDestination,
    Form,
    InvalidURIError,
    Kind,
    MaterializationError,
    MemoryDestination,
    MemoryLimitError,
    Registry,
    ResolutionError,
    SelectionNotSupportedError,
    UnsupportedDestinationError,
    UnsupportedFormError,
    resolve,
)
from urisolver._resource import ResourceBase  # noqa: E402
from urisolver.destinations import ReferencePolicy  # noqa: E402
from urisolver.info import ResourceInfo  # noqa: E402
from urisolver.results import MaterializedResult  # noqa: E402
from urisolver.exchange import StreamExchange  # noqa: E402
from urisolver.resolvers.file import FileResolver  # noqa: E402
from urisolver.secrets.base import SecretsProvider  # noqa: E402
from urisolver.secrets.exchange import ExchangeSecrets  # noqa: E402
from urisolver.selection import Selection  # noqa: E402

ZENODO_RECORD_URI = "https://zenodo.org/records/23025715"
ZENODO_CONTENT_URI = (
    "https://zenodo.org/api/records/23025715/files/pdb_cells.duckdb/content"
)
ZENODO_FILENAME = "pdb_cells.duckdb"
ZENODO_SIZE = 54_538_240
ZENODO_MD5 = "cdabd111595d9fcd5a3700603063f7aa"

_RECORD_HOST = "zenodo.org"
_USER_AGENT = "urisolver-testdrive/0.1"


def _https_host(url: str) -> str:
    parts = urllib.parse.urlparse(url)
    return (parts.hostname or "").lower() if parts.scheme == "https" else ""


def _opener(error: type[Exception]) -> urllib.request.OpenerDirector:
    class _ZenodoOnly(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
            if _https_host(newurl) != _RECORD_HOST:
                raise error(f"refusing redirect off https://{_RECORD_HOST}: {newurl}")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return urllib.request.build_opener(_ZenodoOnly())


def _request(url: str, *, accept: str | None = None) -> urllib.request.Request:
    headers = {"User-Agent": _USER_AGENT}
    if accept is not None:
        headers["Accept"] = accept
    return urllib.request.Request(url, headers=headers)


def _parse_record_uri(uri: str) -> str:
    """Return the Zenodo record id, or raise InvalidURIError."""
    parts = urllib.parse.urlparse(uri)
    if parts.scheme.lower() != "https" or (parts.hostname or "").lower() != _RECORD_HOST:
        raise InvalidURIError(
            f"this example accepts only https://{_RECORD_HOST}/records/<id>: {uri!r}"
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise InvalidURIError(
            f"Zenodo record URI must not carry userinfo, a query, or a fragment: {uri!r}"
        )
    match_path = parts.path.rstrip("/")
    prefix = "/records/"
    if not match_path.startswith(prefix) or "/" in match_path[len(prefix):]:
        raise InvalidURIError(
            f"Zenodo record URI path must be /records/<id>: {uri!r}"
        )
    record_id = match_path[len(prefix):]
    if not record_id.isdigit():
        raise InvalidURIError(f"Zenodo record id must be numeric: {uri!r}")
    return record_id


class _ZenodoFile(ResourceBase):
    def __init__(
        self,
        *,
        uri: str,
        resolved_uri: str,
        filename: str,
        size_bytes: int,
        md5: str,
        context: Any,
    ) -> None:
        super().__init__(
            uri=uri,
            resolved_uri=resolved_uri,
            protocol="https",
            context=context,
            native=None,
            capabilities=frozenset(),
            facets=frozenset(),
            allow_native=False,
        )
        self._filename = filename
        self._size_bytes = size_bytes
        self._md5 = md5
        media = mimetypes.guess_type(filename)[0]
        self._media_type = media
        self._canonical_media_type = media or "application/octet-stream"

    def info(self) -> ResourceInfo:
        self._ensure_valid()
        return ResourceInfo(
            uri=self._uri,
            resolved_uri=self._resolved_uri,
            protocol="https",
            kind=Kind.FILE,
            exists=True,
            media_type=self._media_type,
            size_bytes=self._size_bytes,
            canonical_media_type=self._canonical_media_type,
            label=self._filename,
        )

    def materialize(
        self,
        destination: FileDestination | MemoryDestination,
        *,
        selection: Selection | None = None,
        **kwargs: object,
    ) -> MaterializedResult:
        self._ensure_valid()
        if selection is not None:
            raise SelectionNotSupportedError("Zenodo record files do not support selection")
        info = self.info()
        if destination.media_type is not None and info.canonical_media_type is not None:
            if destination.media_type != info.canonical_media_type:
                raise UnsupportedFormError(
                    f"requested media_type {destination.media_type!r} unsupported"
                )
        if isinstance(destination, MemoryDestination):
            return self._to_memory(destination, info)
        if isinstance(destination, FileDestination):
            return self._to_file(destination, info)
        raise UnsupportedDestinationError(type(destination).__name__)

    def _to_memory(self, destination: MemoryDestination, info: ResourceInfo) -> MaterializedResult:
        if destination.form in (Form.ARRAY, Form.TABLE):
            raise UnsupportedFormError(str(destination.form))
        if destination.form not in (Form.NATIVE, Form.BYTES):
            raise UnsupportedFormError(str(destination.form))
        max_bytes = destination.max_bytes
        if max_bytes is None:
            max_bytes = getattr(self._context, "memory_limit", None)
        if max_bytes is not None and self._size_bytes > max_bytes:
            raise MemoryLimitError(
                f"resource size {self._size_bytes} exceeds memory limit {max_bytes}"
            )
        buf = bytearray()

        def _write(chunk: bytes) -> None:
            buf.extend(chunk)

        size, _digest = _stream_content(self._resolved_uri, self._size_bytes, self._md5, _write)
        form = Form.BYTES if destination.form is Form.BYTES else Form.NATIVE
        return MaterializedResult(
            value=bytes(buf),
            source_uri=self._uri,
            resolved_uri=self._resolved_uri,
            protocol="https",
            destination=destination,
            form=form,
            media_type=info.canonical_media_type,
            size_bytes=size,
            selection=None,
            is_reference=False,
            strategy="native",
        )

    def _to_file(self, destination: FileDestination, info: ResourceInfo) -> MaterializedResult:
        if destination.reference is not ReferencePolicy.COPY:
            raise UnsupportedDestinationError(
                f"Zenodo files are remote; reference policy {destination.reference.value!r} "
                "is unavailable (only copy)"
            )
        dest = Path(destination.path)
        if dest.exists() and not destination.overwrite:
            raise FileExistsError(str(dest))
        if destination.make_parents:
            dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.parent / f".urisolver-{uuid.uuid4().hex}.tmp"
        try:
            with tmp.open("wb") as fh:
                size, _digest = _stream_content(
                    self._resolved_uri, self._size_bytes, self._md5, fh.write
                )
            if destination.mode is not None:
                os.chmod(tmp, destination.mode)
            os.replace(tmp, dest)
        except Exception:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            raise
        return MaterializedResult(
            value=dest,
            source_uri=self._uri,
            resolved_uri=self._resolved_uri,
            protocol="https",
            destination=destination,
            form=Form.PATH,
            media_type=info.canonical_media_type,
            size_bytes=size,
            selection=None,
            is_reference=False,
            strategy="native",
        )


def _stream_content(url: str, expected_size: int, expected_md5: str, write: Any) -> tuple[int, str]:
    """Stream *url* through *write(chunk)*. Fail if size or MD5 disagrees."""
    opener = _opener(MaterializationError)
    digest = hashlib.md5()
    total = 0
    try:
        with opener.open(_request(url), timeout=120) as resp:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > expected_size:
                    raise MaterializationError(
                        f"download exceeded record size {expected_size} bytes"
                    )
                digest.update(chunk)
                write(chunk)
    except MaterializationError:
        raise
    except urllib.error.HTTPError as exc:
        raise MaterializationError(f"Zenodo file download returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise MaterializationError(f"Zenodo file download failed: {exc.reason}") from exc
    got = digest.hexdigest()
    if total != expected_size or got != expected_md5.lower():
        raise MaterializationError(
            f"download does not match the Zenodo record: "
            f"size {total} (expected {expected_size}), md5 {got} (expected {expected_md5})"
        )
    return total, got


class ZenodoRecordResolver:
    """Resolve ``https://zenodo.org/records/<id>`` when the record has one file."""

    api_version = 1
    opaque_payload = False

    def resolve(self, uri: str, context: Any) -> _ZenodoFile:
        record_id = _parse_record_uri(uri)
        meta = _fetch_record(record_id)
        return _ZenodoFile(
            uri=uri,
            resolved_uri=meta["content_uri"],
            filename=meta["filename"],
            size_bytes=meta["size_bytes"],
            md5=meta["md5"],
            context=context,
        )

    def close(self) -> None:
        return None


def _fetch_record(record_id: str) -> dict[str, Any]:
    url = f"https://{_RECORD_HOST}/api/records/{record_id}"
    opener = _opener(ResolutionError)
    try:
        with opener.open(_request(url, accept="application/json"), timeout=60) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise ResolutionError(f"Zenodo record {record_id} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ResolutionError(f"Zenodo record {record_id} unreachable: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ResolutionError(f"Zenodo record {record_id} did not return JSON") from exc
    files = payload.get("files")
    if not isinstance(files, list) or len(files) != 1:
        count = len(files) if isinstance(files, list) else "no"
        raise ResolutionError(
            f"Zenodo record {record_id} has {count} files; "
            "this example resolves only a single-file record"
        )
    entry = files[0]
    if not isinstance(entry, dict):
        raise ResolutionError(f"Zenodo record {record_id} file entry is not an object")
    try:
        filename = entry["key"]
        size_bytes = int(entry["size"])
        checksum = str(entry["checksum"])
        content_uri = str(entry["links"]["self"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ResolutionError(f"Zenodo record {record_id} is missing file metadata") from exc
    if not isinstance(filename, str) or not filename or "/" in filename or "\\" in filename:
        raise ResolutionError(f"Zenodo record {record_id} has an unusable file key")
    prefix = "md5:"
    if not checksum.lower().startswith(prefix) or len(checksum) != len(prefix) + 32:
        raise ResolutionError(
            f"Zenodo record {record_id} has no md5 checksum ({checksum!r})"
        )
    md5 = checksum[len(prefix):].lower()
    if any(char not in "0123456789abcdef" for char in md5):
        raise ResolutionError(f"Zenodo record {record_id} md5 is not hexadecimal ({checksum!r})")
    if _https_host(content_uri) != _RECORD_HOST:
        raise ResolutionError(
            f"Zenodo record {record_id} content URL is not on {_RECORD_HOST}: {content_uri}"
        )
    return {
        "filename": filename,
        "size_bytes": size_bytes,
        "md5": md5,
        "content_uri": content_uri,
    }


def make_context(*, secrets: SecretsProvider | None = None) -> Context:
    """A private registry: built-in file plus this example's Zenodo resolver."""
    registry = Registry()
    registry.register("file", FileResolver(), source="testdrive")
    registry.register("https", ZenodoRecordResolver(), source="testdrive")
    return Context(registry=registry, secrets=secrets)


def deliver(resource: Any, dest: Path) -> MaterializedResult:
    """Copy an already-resolved resource onto *dest*. Scheme-agnostic."""
    return resource.materialize(FileDestination(dest, overwrite=True))


def stage(uri: str, dest: Path, *, context: Context) -> MaterializedResult:
    """Deliver *uri* as a local file. The caller does not inspect the scheme."""
    return deliver(resolve(uri, context=context), dest)


def _delivery_report(
    uri: str,
    dest: Path,
    *,
    memory: bool,
    secrets: SecretsProvider | None = None,
) -> dict[str, Any]:
    with make_context(secrets=secrets) as ctx:
        resource = resolve(uri, context=ctx)
        info = resource.info()
        result = deliver(resource, dest)
        report: dict[str, Any] = {
            "uri": resource.uri,
            "resolved_uri": result.resolved_uri,
            "kind": info.kind.value,
            "exists": info.exists,
            "size_bytes": info.size_bytes,
            "label": info.label,
            "media_type": info.media_type,
            "canonical_media_type": info.canonical_media_type,
            "supports_info": resource.supports("info"),
            "supports_materialize": resource.supports("materialize"),
            "value": str(result.value),
            "form": result.form.value,
            "source_uri": result.source_uri,
            "is_reference": result.is_reference,
            "strategy": result.strategy,
            "result_size_bytes": result.size_bytes,
        }
        if memory:
            mem = resource.materialize(MemoryDestination())
            if not isinstance(mem.value, (bytes, bytearray)):
                raise MaterializationError("MemoryDestination did not return bytes")
            report["memory_form"] = mem.form.value
            report["memory_bytes_b64"] = base64.b64encode(bytes(mem.value)).decode("ascii")
        return report


def _run_worker(uri: str, dest: Path, *, memory: bool) -> dict[str, Any]:
    cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", uri, str(dest)]
    if memory:
        cmd.append("--memory")
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"worker failed for {uri} ({proc.returncode})\n{detail}")
    return json.loads(proc.stdout)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_file_delivery(report: dict[str, Any], uri: str, dest: Path, size: int) -> None:
    _require(report["uri"] == uri, f"uri {report['uri']!r} != shipped {uri!r}")
    _require(report["kind"] == Kind.FILE.value, f"kind {report['kind']!r}")
    _require(report["exists"] is True, "exists is not true")
    _require(report["size_bytes"] == size, f"size_bytes {report['size_bytes']} != {size}")
    _require(report["supports_info"] is True, "supports(info) is false")
    _require(report["supports_materialize"] is True, "supports(materialize) is false")
    _require(Path(report["value"]) == dest, f"value {report['value']!r} != {dest}")
    _require(report["form"] == Form.PATH.value, f"form {report['form']!r}")
    _require(report["source_uri"] == uri, f"source_uri {report['source_uri']!r}")
    _require(report["is_reference"] is False, "is_reference is true")
    _require(report["strategy"] == "native", f"strategy {report['strategy']!r}")
    _require(
        report["result_size_bytes"] == size,
        f"result size {report['result_size_bytes']} != {size}",
    )
    _require(dest.is_file(), f"staged path missing: {dest}")
    _require(dest.stat().st_size == size, f"staged file size {dest.stat().st_size} != {size}")


def run_stories() -> None:
    """Parent process: ship each URI to a fresh worker and check delivery."""
    import tempfile

    print("Case 1 — file on local disc")
    with tempfile.TemporaryDirectory(prefix="urisolver-testdrive-") as tmp:
        root = Path(tmp)
        payload = b"testdrive-local\n"
        source = root / "source.dat"
        source.write_bytes(payload)
        dest = root / "work" / "input.dat"
        uri = source.resolve().as_uri()
        print(f"  shipped: {uri}")
        report = _run_worker(uri, dest, memory=True)
        _check_file_delivery(report, uri, dest, len(payload))
        _require(dest.read_bytes() == payload, "staged bytes differ from the local file")
        _require(report.get("memory_form") == Form.NATIVE.value, "memory form is not native")
        got = base64.b64decode(report["memory_bytes_b64"])
        _require(got == payload, "MemoryDestination bytes differ from the local file")
        print(f"  staged:  {dest} ({len(payload)} bytes, strategy=native, is_reference=false)")
        print(f"  memory:  {len(got)} bytes, form=native")

    print("Case 2 — Zenodo record")
    print(f"  shipped: {ZENODO_RECORD_URI}")
    print(f"  downloading {ZENODO_FILENAME} ({ZENODO_SIZE} bytes)")
    with tempfile.TemporaryDirectory(prefix="urisolver-testdrive-zenodo-") as tmp:
        dest = Path(tmp) / ZENODO_FILENAME
        report = _run_worker(ZENODO_RECORD_URI, dest, memory=False)
        _check_file_delivery(report, ZENODO_RECORD_URI, dest, ZENODO_SIZE)
        _require(
            report["resolved_uri"] == ZENODO_CONTENT_URI,
            f"resolved_uri {report['resolved_uri']!r}",
        )
        _require(report["label"] == ZENODO_FILENAME, f"label {report['label']!r}")
        _require("memory_bytes_b64" not in report, "Zenodo delivery pulled the file into memory")
        digest = _md5_file(dest)
        _require(digest == ZENODO_MD5, f"md5 {digest} != {ZENODO_MD5}")
        print(f"  resolved: {report['resolved_uri']}")
        print(f"  staged:   {dest}")
        print(f"  size {ZENODO_SIZE}, md5 {digest}, strategy=native, is_reference=false")
    print("both deliveries match the Tier 0 contract")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ship a URI to a worker and materialize it.")
    parser.add_argument("--worker", action="store_true", help="resolve URI and write DEST")
    parser.add_argument("uri", nargs="?")
    parser.add_argument("dest", nargs="?")
    parser.add_argument("--memory", action="store_true", help="also materialize MemoryDestination")
    parser.add_argument(
        "--exchange-fd",
        type=int,
        default=None,
        help="inherited stream for an opaque byte exchange (optional)",
    )
    args = parser.parse_args(argv)
    if args.worker:
        if not args.uri or not args.dest:
            parser.error("--worker requires URI and DEST")
        secrets = None
        exchange = None
        if args.exchange_fd is not None:
            stream = os.fdopen(args.exchange_fd, "r+b", buffering=0)
            exchange = StreamExchange(stream)
            secrets = ExchangeSecrets(exchange)
        try:
            report = _delivery_report(
                args.uri, Path(args.dest), memory=args.memory, secrets=secrets
            )
        finally:
            if exchange is not None:
                exchange.close()
        json.dump(report, sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.uri or args.dest or args.memory:
        parser.error("run with no arguments for both stories, or --worker URI DEST")
    run_stories()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
