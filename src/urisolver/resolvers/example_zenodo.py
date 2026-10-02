"""Example resolver for one file on a Zenodo record.

``import urisolver`` does not import this module. A script registers it
explicitly for ``https``. It is not a package entry point.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from urisolver._resource import ResourceBase
from urisolver.destinations import (
    FileDestination,
    Form,
    MemoryDestination,
    ReferencePolicy,
)
from urisolver.errors import (
    InvalidURIError,
    MaterializationError,
    MemoryLimitError,
    ResolutionError,
    SelectionNotSupportedError,
    UnsupportedDestinationError,
    UnsupportedFormError,
)
from urisolver.info import Kind, ResourceInfo
from urisolver.results import MaterializedResult
from urisolver.selection import Selection

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
