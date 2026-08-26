"""file: resolver (§27.1)."""
from __future__ import annotations
import mimetypes
import os
import shutil
import uuid
from pathlib import Path
from typing import IO, Any, Literal
from urllib.parse import urlparse
from urllib.request import url2pathname
from urisolver._resource import ResourceBase
from urisolver._uriparse import split_uri
from urisolver.destinations import FileDestination, Form, MemoryDestination, ReferencePolicy
from urisolver.errors import (
    InvalidURIError, MemoryLimitError, SelectionNotSupportedError, UnsupportedDestinationError,
    UnsupportedFormError,
)
from urisolver.info import Kind, ResourceInfo
from urisolver.results import MaterializedResult
from urisolver.selection import Selection

def _uri_to_path(uri: str) -> Path:
    """Map a file: URI to a local path (RFC 8089).

    Percent-decoding happens exactly once, inside url2pathname (RFC 3986 §2.4).
    Never call unquote() on the result or on the input.
    """
    parts = split_uri(uri)
    if parts.scheme != "file":
        raise InvalidURIError(
            f"FileResolver received a URI with scheme {parts.scheme!r}: {uri!r}"
        )
    parsed = urlparse(uri)
    if parsed.query:
        raise InvalidURIError(
            f"file: URIs define no query component (RFC 8089); refusing {uri!r}"
        )
    path_part = parsed.path
    if os.name == "posix" and ("%2F" in path_part.upper() or "%2f" in path_part):
        raise InvalidURIError(
            f"file: URI percent-encodes a path separator (RFC 3986 §2.2): {uri!r}"
        )
    host = parsed.netloc
    if host and host.lower() != "localhost":
        if os.name != "nt":
            raise InvalidURIError(
                f"file: URI names the non-local host {host!r}; only an empty "
                f"authority or 'localhost' is supported on this platform "
                f"(RFC 8089 §2, Appendix E.3.2)"
            )
        path = "//" + host + url2pathname(parsed.path)
    else:
        path = url2pathname(parsed.path)
    result = Path(path)
    if not result.is_absolute():
        raise InvalidURIError(f"file: URI does not name an absolute path: {uri!r}")
    return result

class _StreamFacet:
    def __init__(self, path: Path) -> None:
        self._path = path
    def open(self, mode: Literal["rb"] = "rb") -> IO[bytes]:
        if mode != "rb":
            raise ValueError("stream facet only supports mode='rb'")
        return open(self._path, "rb")
    def readable_ranges(self) -> bool:
        return True

class _ContainerFacet:
    def __init__(self, path: Path, resource: "FileResolvedResource") -> None:
        self._path = path
        self._resource = resource
    def keys(self):
        return (p.name for p in sorted(self._path.iterdir()))
    def __getitem__(self, key: str) -> "FileResolvedResource":
        child = self._path / key
        child_uri = child.resolve().as_uri()
        return FileResolvedResource(uri=child_uri, resolved_uri=child_uri, path=child, context=self._resource._context)
    def __len__(self) -> int:
        return sum(1 for _ in self._path.iterdir())

class FileResolvedResource(ResourceBase):
    def __init__(self, *, uri: str, resolved_uri: str, path: Path, context: Any) -> None:
        self._path = path
        facets: set[str] = set()
        if path.exists() and path.is_file():
            facets.add("stream")
        if path.is_dir():
            facets.add("container")
        super().__init__(
            uri=uri, resolved_uri=resolved_uri, protocol="file", context=context,
            native=path, capabilities=frozenset({"open", "stat"}), facets=frozenset(facets), allow_native=True,
        )
        if "stream" in facets:
            self._facet_objects["stream"] = _StreamFacet(path)
        if "container" in facets:
            self._facet_objects["container"] = _ContainerFacet(path, self)

    def info(self) -> ResourceInfo:
        self._ensure_valid()
        exists = self._path.exists()
        if exists and self._path.is_dir():
            return ResourceInfo(uri=self._uri, resolved_uri=self._resolved_uri, protocol="file",
                                kind=Kind.CONTAINER, exists=True, label=self._path.name)
        media = mimetypes.guess_type(str(self._path))[0] if exists else None
        canonical = (media or "application/octet-stream") if exists else None
        size = self._path.stat().st_size if exists and self._path.is_file() else None
        return ResourceInfo(uri=self._uri, resolved_uri=self._resolved_uri, protocol="file",
                            kind=Kind.FILE, exists=exists, media_type=media, size_bytes=size,
                            canonical_media_type=canonical, label=self._path.name)

    def materialize(self, destination: FileDestination | MemoryDestination, *, selection: Selection | None = None, **kwargs: object) -> MaterializedResult:
        self._ensure_valid()
        if selection is not None:
            raise SelectionNotSupportedError("file: resources do not support selection")
        info = self.info()
        if isinstance(destination, MemoryDestination):
            return self._to_memory(destination, info)
        if isinstance(destination, FileDestination):
            return self._to_file(destination, info)
        raise UnsupportedDestinationError(type(destination).__name__)

    def _to_memory(self, destination: MemoryDestination, info: ResourceInfo) -> MaterializedResult:
        if info.kind is Kind.CONTAINER:
            if destination.form is Form.BYTES:
                raise UnsupportedFormError("container has no byte representation")
            if destination.form is not Form.NATIVE:
                raise UnsupportedFormError(str(destination.form))
            mapping = {
                name: FileResolvedResource(
                    uri=(self._path / name).resolve().as_uri(),
                    resolved_uri=(self._path / name).resolve().as_uri(),
                    path=self._path / name, context=self._context,
                )
                for name in sorted(p.name for p in self._path.iterdir())
            }
            return MaterializedResult(
                value=mapping, source_uri=self._uri, resolved_uri=self._resolved_uri, protocol="file",
                destination=destination, form=Form.NATIVE, media_type=None, size_bytes=None,
                selection=None, is_reference=True, strategy="reference",
            )
        if destination.form in (Form.ARRAY, Form.TABLE):
            raise UnsupportedFormError(str(destination.form))
        if destination.media_type is not None and info.canonical_media_type is not None:
            if destination.media_type != info.canonical_media_type:
                raise UnsupportedFormError(f"requested media_type {destination.media_type!r} unsupported")
        max_bytes = destination.max_bytes
        if max_bytes is None:
            max_bytes = getattr(self._context, "memory_limit", None)
        if info.size_bytes is not None and max_bytes is not None and info.size_bytes > max_bytes:
            raise MemoryLimitError(f"resource size {info.size_bytes} exceeds memory limit {max_bytes}")
        data = self._path.read_bytes()
        if max_bytes is not None and len(data) > max_bytes:
            raise MemoryLimitError(f"resource size {len(data)} exceeds memory limit {max_bytes}")
        form = Form.BYTES if destination.form is Form.BYTES else Form.NATIVE
        return MaterializedResult(
            value=data, source_uri=self._uri, resolved_uri=self._resolved_uri, protocol="file",
            destination=destination, form=form, media_type=info.canonical_media_type,
            size_bytes=len(data), selection=None, is_reference=False, strategy="native",
        )

    def _to_file(self, destination: FileDestination, info: ResourceInfo) -> MaterializedResult:
        if info.kind is Kind.CONTAINER and info.canonical_media_type is None:
            raise UnsupportedDestinationError("directory FileDestination out of scope for v0")
        if destination.media_type is not None and info.canonical_media_type is not None:
            if destination.media_type != info.canonical_media_type:
                raise UnsupportedFormError(f"requested media_type {destination.media_type!r} unsupported")
        dest = Path(destination.path)
        policy = destination.reference
        if dest.exists() and not destination.overwrite:
            raise FileExistsError(str(dest))
        if policy is ReferencePolicy.IN_PLACE:
            return MaterializedResult(
                value=self._path.resolve(), source_uri=self._uri, resolved_uri=self._resolved_uri,
                protocol="file", destination=destination, form=Form.PATH,
                media_type=info.canonical_media_type, size_bytes=info.size_bytes,
                selection=None, is_reference=True, strategy="reference",
            )
        if destination.make_parents:
            dest.parent.mkdir(parents=True, exist_ok=True)
        if policy is ReferencePolicy.SYMLINK:
            if dest.is_symlink() or dest.exists():
                dest.unlink()
            os.symlink(self._path.resolve(), dest)
            return MaterializedResult(
                value=dest, source_uri=self._uri, resolved_uri=self._resolved_uri, protocol="file",
                destination=destination, form=Form.PATH, media_type=info.canonical_media_type,
                size_bytes=info.size_bytes, selection=None, is_reference=True, strategy="reference",
            )
        if policy is ReferencePolicy.HARDLINK:
            if dest.exists():
                dest.unlink()
            try:
                os.link(self._path.resolve(), dest)
            except OSError as exc:
                raise UnsupportedDestinationError(
                    f"hardlink reference unavailable: {exc}"
                ) from exc
            return MaterializedResult(
                value=dest, source_uri=self._uri, resolved_uri=self._resolved_uri, protocol="file",
                destination=destination, form=Form.PATH, media_type=info.canonical_media_type,
                size_bytes=info.size_bytes, selection=None, is_reference=True, strategy="reference",
            )
        if policy is not ReferencePolicy.COPY:
            raise UnsupportedDestinationError(f"unsupported reference policy {policy!r}")
        tmp = dest.parent / f".urisolver-{uuid.uuid4().hex}.tmp"
        try:
            shutil.copy2(self._path, tmp)
            if destination.mode is not None:
                os.chmod(tmp, destination.mode)
            os.replace(tmp, dest)
        except Exception:
            if tmp.exists():
                try: tmp.unlink()
                except OSError: pass
            raise
        return MaterializedResult(
            value=dest, source_uri=self._uri, resolved_uri=self._resolved_uri, protocol="file",
            destination=destination, form=Form.PATH, media_type=info.canonical_media_type,
            size_bytes=info.size_bytes, selection=None, is_reference=False, strategy="native",
        )

class FileResolver:
    api_version = 1
    opaque_payload = False
    def resolve(self, uri: str, context: Any) -> FileResolvedResource:
        path = _uri_to_path(uri)
        try:
            resolved_uri = path.resolve().as_uri()
        except OSError:
            resolved_uri = uri
        return FileResolvedResource(uri=uri, resolved_uri=resolved_uri, path=path, context=context)
    def close(self) -> None:
        return None
