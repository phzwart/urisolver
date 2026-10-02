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
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from urisolver import (  # noqa: E402
    Context,
    FileDestination,
    Form,
    Kind,
    MaterializationError,
    MemoryDestination,
    Registry,
    resolve,
)
from urisolver.exchange import StreamExchange  # noqa: E402
from urisolver.resolvers.example_zenodo import ZenodoRecordResolver  # noqa: E402
from urisolver.resolvers.file import FileResolver  # noqa: E402
from urisolver.results import MaterializedResult  # noqa: E402
from urisolver.secrets.base import SecretsProvider  # noqa: E402
from urisolver.secrets.exchange import ExchangeSecrets  # noqa: E402

ZENODO_RECORD_URI = "https://zenodo.org/records/23025715"
ZENODO_CONTENT_URI = (
    "https://zenodo.org/api/records/23025715/files/pdb_cells.duckdb/content"
)
ZENODO_FILENAME = "pdb_cells.duckdb"
ZENODO_SIZE = 54_538_240
ZENODO_MD5 = "cdabd111595d9fcd5a3700603063f7aa"


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
