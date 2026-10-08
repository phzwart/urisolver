"""Example resolver for public objects on one CryoET Data Portal origin.

The origin comes from the local resolution catalog. ``import urisolver`` does
not import this module. ``zarr`` is imported only when an array is read.
"""
from __future__ import annotations

import io
import itertools
import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from urisolver._resource import ResourceBase
from urisolver._uriparse import split_uri
from urisolver.destinations import FileDestination, Form, MemoryDestination, ReferencePolicy
from urisolver.errors import (
    InefficientOperationError,
    InvalidURIError,
    MaterializationError,
    MemoryLimitError,
    PluginError,
    ResolutionError,
    SelectionError,
    SelectionNotSupportedError,
    UnsupportedDestinationError,
    UnsupportedFormError,
)
from urisolver.info import Kind, ResourceInfo
from urisolver.resolvers._catalog import entry
from urisolver.results import MaterializedResult
from urisolver.selection import Native, Selection

SCHEME = "com.urisolver.example.cryoet"
_USER_AGENT = "urisolver-example-cryoet/0.1"
_NPY = "application/x-npy"


@dataclass(frozen=True)
class ScaleLevel:
    """One dataset in an OME-Zarr multiscale group, in listed order."""

    path: str
    shape: tuple[int, ...]
    dtype: str
    chunks: tuple[int, ...]
    separator: str

    @property
    def nbytes(self) -> int:
        return _itemsize(self.dtype) * _prod(self.shape)


def _itemsize(dtype: str) -> int:
    digits = ""
    for char in reversed(dtype.strip()):
        if not char.isdigit():
            break
        digits = char + digits
    if not digits:
        raise ResolutionError(f"OME-Zarr dtype {dtype!r} has no item size")
    return int(digits)


def _prod(shape: tuple[int, ...]) -> int:
    total = 1
    for dim in shape:
        total *= dim
    return total


def _https_host(url: str) -> str:
    parts = urllib.parse.urlparse(url)
    if parts.scheme != "https" or not parts.hostname:
        return ""
    return parts.hostname.lower()


def _check_redirect(host: str, newurl: str, error: type[Exception]) -> None:
    if _https_host(newurl) != host:
        raise error(f"refusing redirect off https://{host}: {newurl}")


def _opener(host: str, error: type[Exception]) -> urllib.request.OpenerDirector:
    class _SameHostOnly(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
            _check_redirect(host, newurl, error)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return urllib.request.build_opener(_SameHostOnly())


def _request(url: str, *, method: str = "GET") -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": _USER_AGENT}, method=method)


def join_url(base: str, rel: str) -> str:
    return urllib.parse.urljoin(base.rstrip("/") + "/", rel.lstrip("/"))


def object_path(uri: str) -> str:
    """Return the portal object key, or raise InvalidURIError.

    Accepted paths end in ``.zarr`` or ``.mrc``. No query. The fragment is
    split off by the core and ignored. Each segment is percent-decoded once.
    """
    try:
        body = split_uri(uri).body
    except ValueError as exc:
        raise InvalidURIError(str(exc)) from None
    if "?" in body:
        raise InvalidURIError(f"CryoET URI has no query: {uri!r}")
    path = body[2:] if body.startswith("//") else body
    segments = path.strip("/").split("/")
    if not segments or any(segment == "" for segment in segments):
        raise InvalidURIError(f"CryoET URI has an empty path segment: {uri!r}")
    decoded: list[str] = []
    for segment in segments:
        if segment in {".", ".."}:
            raise InvalidURIError(f"CryoET URI rejects dot segments: {uri!r}")
        piece = urllib.parse.unquote(segment)
        if not piece or piece in {".", ".."} or "/" in piece or "\\" in piece:
            raise InvalidURIError(f"CryoET URI has an unusable path segment: {uri!r}")
        decoded.append(piece)
    rel = "/".join(decoded)
    if not (rel.endswith(".zarr") or rel.endswith(".mrc")):
        raise InvalidURIError(f"CryoET URI must name a .zarr dataset or an .mrc file: {uri!r}")
    return rel


def fetch(url: str, host: str) -> bytes:
    """GET *url*. Redirects must stay on *host*."""
    opener = _opener(host, ResolutionError)
    try:
        with opener.open(_request(url), timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise ResolutionError(f"GET {url} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ResolutionError(f"GET {url} failed: {exc.reason}") from exc


def content_length(url: str, host: str) -> int:
    """Return Content-Length from a HEAD request."""
    opener = _opener(host, ResolutionError)
    try:
        with opener.open(_request(url, method="HEAD"), timeout=60) as resp:
            raw = resp.headers.get("Content-Length")
    except urllib.error.HTTPError as exc:
        raise ResolutionError(f"HEAD {url} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ResolutionError(f"HEAD {url} failed: {exc.reason}") from exc
    if raw is None or not str(raw).isdigit():
        raise ResolutionError(f"HEAD {url} did not report Content-Length")
    return int(raw)


def stream_to(url: str, host: str, write: Callable[[bytes], None], expected: int) -> int:
    """Stream *url* through *write*. Fail when the byte count is not *expected*."""
    opener = _opener(host, MaterializationError)
    total = 0
    try:
        with opener.open(_request(url), timeout=120) as resp:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > expected:
                    raise MaterializationError(f"download exceeded Content-Length {expected}")
                write(chunk)
    except MaterializationError:
        raise
    except urllib.error.HTTPError as exc:
        raise MaterializationError(f"download returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise MaterializationError(f"download failed: {exc.reason}") from exc
    if total != expected:
        raise MaterializationError(f"download size {total} != Content-Length {expected}")
    return total


def parse_levels(zattrs: Any, arrays: dict[str, Any]) -> tuple[ScaleLevel, ...]:
    """Build scale levels from OME-Zarr ``.zattrs`` and each level's ``.zarray``."""
    if not isinstance(zattrs, dict):
        raise ResolutionError("OME-Zarr .zattrs is not an object")
    scales = zattrs.get("multiscales")
    if not isinstance(scales, list) or not scales or not isinstance(scales[0], dict):
        raise ResolutionError("OME-Zarr metadata has no multiscales")
    datasets = scales[0].get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ResolutionError("OME-Zarr multiscale lists no datasets")
    levels: list[ScaleLevel] = []
    for item in datasets:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"]:
            raise ResolutionError("OME-Zarr dataset path is missing")
        path = item["path"]
        if "/" in path or "\\" in path or path in {".", ".."}:
            raise ResolutionError(f"OME-Zarr dataset path {path!r} is not a single segment")
        meta = arrays.get(path)
        if not isinstance(meta, dict):
            raise ResolutionError(f"OME-Zarr level {path!r} has no .zarray")
        levels.append(_level_from_zarray(path, meta))
    return tuple(levels)


def _level_from_zarray(path: str, meta: dict) -> ScaleLevel:
    shape_raw = meta.get("shape")
    chunks_raw = meta.get("chunks")
    dtype = meta.get("dtype")
    if (
        not isinstance(shape_raw, list)
        or not shape_raw
        or not isinstance(chunks_raw, list)
        or len(chunks_raw) != len(shape_raw)
        or not isinstance(dtype, str)
    ):
        raise ResolutionError(f"OME-Zarr level {path!r} .zarray is missing shape, chunks, or dtype")
    try:
        shape = tuple(int(dim) for dim in shape_raw)
        chunks = tuple(int(dim) for dim in chunks_raw)
    except (TypeError, ValueError) as exc:
        raise ResolutionError(f"OME-Zarr level {path!r} shape is not integral") from exc
    if any(dim <= 0 for dim in shape) or any(dim <= 0 for dim in chunks):
        raise ResolutionError(f"OME-Zarr level {path!r} shape and chunks must be positive")
    separator = meta.get("dimension_separator", ".")
    if separator not in {".", "/"}:
        raise ResolutionError(f"OME-Zarr level {path!r} dimension_separator {separator!r} is unsupported")
    level = ScaleLevel(path=path, shape=shape, dtype=dtype, chunks=chunks, separator=separator)
    _itemsize(level.dtype)
    return level


def chunk_names(level: ScaleLevel) -> tuple[str, ...]:
    """Chunk keys relative to the level directory."""
    counts = [range((size + chunk - 1) // chunk) for size, chunk in zip(level.shape, level.chunks)]
    return tuple(level.separator.join(str(index) for index in coord) for coord in itertools.product(*counts))


def _load_json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResolutionError(f"{label} is not JSON") from exc


def load_zarr(url: str, host: str) -> tuple[tuple[ScaleLevel, ...], dict[str, bytes]]:
    """Fetch multiscale metadata. Chunks stay unread."""
    files: dict[str, bytes] = {}
    zattrs_raw = fetch(join_url(url, ".zattrs"), host)
    zgroup_raw = fetch(join_url(url, ".zgroup"), host)
    files[".zattrs"] = zattrs_raw
    files[".zgroup"] = zgroup_raw
    zattrs = _load_json(zattrs_raw, ".zattrs")
    if not isinstance(zattrs, dict):
        raise ResolutionError("OME-Zarr .zattrs is not an object")
    scales = zattrs.get("multiscales")
    datasets = scales[0].get("datasets") if isinstance(scales, list) and scales and isinstance(scales[0], dict) else None
    if not isinstance(datasets, list):
        raise ResolutionError("OME-Zarr metadata has no multiscales")
    arrays: dict[str, Any] = {}
    for item in datasets:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"]:
            raise ResolutionError("OME-Zarr dataset path is missing")
        path = item["path"]
        if "/" in path or "\\" in path or path in {".", ".."}:
            raise ResolutionError(f"OME-Zarr dataset path {path!r} is not a single segment")
        raw = fetch(join_url(url, f"{path}/.zarray"), host)
        files[f"{path}/.zarray"] = raw
        arrays[path] = _load_json(raw, f"{path}/.zarray")
    return parse_levels(zattrs, arrays), files


def _npy_bytes(value: Any) -> bytes:
    try:
        import numpy as np
    except ImportError as exc:
        raise UnsupportedFormError("application/x-npy requires numpy") from exc
    buf = io.BytesIO()
    np.save(buf, np.asarray(value))
    return buf.getvalue()


def _require_zarr() -> Any:
    try:
        import zarr
    except ImportError as exc:
        raise PluginError("reading an OME-Zarr array requires zarr; install urisolver[cryoet]") from exc
    return zarr


def read_level(url: str, level: str, selection: Any) -> Any:
    """Read one scale, pushing *selection* into the array when it is not None."""
    zarr = _require_zarr()
    target = join_url(url, level)
    opener = getattr(zarr, "open_array", None)
    array = opener(target, mode="r") if opener is not None else zarr.open(target, mode="r")
    if selection is None:
        return array[:]
    return array[selection]


def _is_basic_item(item: object) -> bool:
    if isinstance(item, bool):
        return False
    return item is Ellipsis or isinstance(item, (int, slice))


def _require_basic(selection: object) -> None:
    if _is_basic_item(selection):
        return
    if isinstance(selection, tuple) and selection and all(_is_basic_item(item) for item in selection):
        return
    raise SelectionNotSupportedError("selection must be numpy basic indexing or Native(scale)")


def interpret_selection(selection: Selection | None) -> tuple[int, Any, str]:
    """Return ``(scale_index, array_index, strategy)``.

    ``None`` reads scale 0. Basic indexing is applied to scale 0 and pushed to
    the store (``native-selection``). ``Native(n)`` reads scale ``n``.
    ``Native((n, index))`` applies basic indexing to that scale.
    """
    if selection is None:
        return 0, None, "native"
    if isinstance(selection, Native):
        value = selection.value
        if isinstance(value, int) and not isinstance(value, bool):
            return value, None, "native"
        if (
            isinstance(value, tuple)
            and len(value) == 2
            and isinstance(value[0], int)
            and not isinstance(value[0], bool)
        ):
            _require_basic(value[1])
            return value[0], value[1], "native-selection"
        raise SelectionNotSupportedError("Native selection must be a scale index or (index, basic index)")
    _require_basic(selection)
    return 0, selection, "native-selection"


class ZarrArrayFacet:
    """Array facet for scale 0, plus ``levels`` for the rest of the pyramid."""

    def __init__(self, levels: tuple[ScaleLevel, ...], read: Callable[[int, Any], Any]) -> None:
        self.levels = levels
        self._read = read
        top = levels[0]
        self.shape = top.shape
        self.dtype = top.dtype
        self.chunks = (top.chunks,)

    def __getitem__(self, selection: object) -> object:
        _require_basic(selection)
        return self._read(0, selection)


class CryoetResource(ResourceBase):
    def __init__(
        self,
        *,
        uri: str,
        resolved_uri: str,
        protocol: str,
        context: Any,
        host: str,
        native_modes: frozenset[str] | None,
        kind: Kind,
        label: str,
        size_bytes: int | None,
        shape: tuple[int, ...] | None = None,
        dtype: str | None = None,
        canonical_media_type: str | None = None,
        levels: tuple[ScaleLevel, ...] = (),
        meta_files: dict[str, bytes] | None = None,
    ) -> None:
        super().__init__(
            uri=uri,
            resolved_uri=resolved_uri,
            protocol=protocol,
            context=context,
            native=None,
            capabilities=frozenset(),
            facets=frozenset({"array"}) if kind is Kind.ARRAY else frozenset(),
            allow_native=False,
        )
        self._host = host
        self._native_modes = native_modes
        self._kind = kind
        self._label = label
        self._size_bytes = size_bytes
        self._shape = shape
        self._dtype = dtype
        self._canonical_media_type = canonical_media_type
        self._levels = levels
        self._meta_files = dict(meta_files or {})
        if kind is Kind.ARRAY:
            self._facet_objects["array"] = ZarrArrayFacet(levels, self._read_scale)

    def info(self) -> ResourceInfo:
        self._ensure_valid()
        media = self._canonical_media_type
        return ResourceInfo(
            uri=self._uri,
            resolved_uri=self._resolved_uri,
            protocol=self._protocol,
            kind=self._kind,
            exists=True,
            media_type=media,
            size_bytes=self._size_bytes,
            shape=self._shape,
            dtype=self._dtype,
            canonical_media_type=media,
            label=self._label,
        )

    def materialize(
        self,
        destination: FileDestination | MemoryDestination,
        *,
        selection: Selection | None = None,
        **kwargs: object,
    ) -> MaterializedResult:
        self._ensure_valid()
        self._require_mode(destination)
        if self._kind is Kind.FILE and selection is not None:
            raise SelectionNotSupportedError("MRC files do not support selection")
        info = self.info()
        if isinstance(destination, MemoryDestination):
            return self._to_memory(destination, info, selection)
        if isinstance(destination, FileDestination):
            return self._to_file(destination, info, selection)
        raise UnsupportedDestinationError(type(destination).__name__)

    def _require_mode(self, destination: FileDestination | MemoryDestination) -> None:
        modes = self._native_modes
        if not modes or not getattr(self._context, "strict_efficiency", False):
            return
        mode = "file" if isinstance(destination, FileDestination) else "memory"
        if isinstance(destination, MemoryDestination) and destination.form is Form.BYTES:
            mode = "file"
        if mode not in modes:
            raise InefficientOperationError(f"{mode} delivery is not native for this server")

    def _limit(self, destination: MemoryDestination) -> int | None:
        if destination.max_bytes is not None:
            return destination.max_bytes
        return getattr(self._context, "memory_limit", None)

    def _check_limit(self, destination: MemoryDestination, nbytes: int) -> None:
        limit = self._limit(destination)
        if limit is not None and nbytes > limit:
            raise MemoryLimitError(f"resource size {nbytes} exceeds memory limit {limit}")

    def _read_scale(self, index: int, array_index: Any) -> Any:
        if index < 0 or index >= len(self._levels):
            raise SelectionError(f"scale index {index} is outside 0..{len(self._levels) - 1}")
        level = self._levels[index]
        return read_level(self._resolved_uri, level.path, array_index)

    def _to_memory(
        self,
        destination: MemoryDestination,
        info: ResourceInfo,
        selection: Selection | None,
    ) -> MaterializedResult:
        if self._kind is Kind.FILE:
            return self._file_to_memory(destination, info)
        if destination.form is Form.TABLE:
            raise UnsupportedFormError(str(destination.form))
        if destination.form not in (Form.NATIVE, Form.ARRAY, Form.BYTES):
            raise UnsupportedFormError(str(destination.form))
        index, array_index, strategy = interpret_selection(selection)
        if array_index is None:
            if index < 0 or index >= len(self._levels):
                raise SelectionError(f"scale index {index} is outside 0..{len(self._levels) - 1}")
            self._check_limit(destination, self._levels[index].nbytes)
        value = self._read_scale(index, array_index)
        nbytes = getattr(value, "nbytes", None)
        if isinstance(nbytes, int):
            self._check_limit(destination, nbytes)
        if destination.form is Form.BYTES:
            if destination.media_type is not None and destination.media_type != _NPY:
                raise UnsupportedFormError(f"requested media_type {destination.media_type!r} unsupported")
            data = _npy_bytes(value)
            self._check_limit(destination, len(data))
            reported = "converted" if strategy == "native" else strategy
            return self._memory_result(
                destination, data, Form.BYTES, _NPY, len(data), selection, reported
            )
        form = Form.ARRAY if destination.form is Form.ARRAY else Form.NATIVE
        size = nbytes if isinstance(nbytes, int) else None
        return self._memory_result(destination, value, form, None, size, selection, strategy)

    def _file_to_memory(self, destination: MemoryDestination, info: ResourceInfo) -> MaterializedResult:
        if destination.form not in (Form.NATIVE, Form.BYTES):
            raise UnsupportedFormError(str(destination.form))
        if destination.media_type is not None and destination.media_type != info.canonical_media_type:
            raise UnsupportedFormError(f"requested media_type {destination.media_type!r} unsupported")
        assert info.size_bytes is not None
        self._check_limit(destination, info.size_bytes)
        buf = bytearray()
        stream_to(self._resolved_uri, self._host, buf.extend, info.size_bytes)
        data = bytes(buf)
        form = Form.BYTES if destination.form is Form.BYTES else Form.NATIVE
        return self._memory_result(
            destination, data, form, info.canonical_media_type, len(data), None, "native"
        )

    def _memory_result(
        self,
        destination: MemoryDestination,
        value: object,
        form: Form,
        media_type: str | None,
        size_bytes: int | None,
        selection: Selection | None,
        strategy: str,
    ) -> MaterializedResult:
        return MaterializedResult(
            value=value,
            source_uri=self._uri,
            resolved_uri=self._resolved_uri,
            protocol=self._protocol,
            destination=destination,
            form=form,
            media_type=media_type,
            size_bytes=size_bytes,
            selection=selection,
            is_reference=False,
            strategy=strategy,
        )

    def _to_file(
        self,
        destination: FileDestination,
        info: ResourceInfo,
        selection: Selection | None,
    ) -> MaterializedResult:
        if destination.reference is not ReferencePolicy.COPY:
            raise UnsupportedDestinationError(
                f"CryoET objects are remote; reference policy {destination.reference.value!r} "
                "is unavailable (only copy)"
            )
        if self._kind is Kind.ARRAY and selection is not None:
            raise SelectionNotSupportedError("FileDestination copies the zarr store, not a selection")
        if destination.media_type is not None and self._kind is Kind.FILE:
            if destination.media_type != info.canonical_media_type:
                raise UnsupportedFormError(f"requested media_type {destination.media_type!r} unsupported")
        if destination.media_type is not None and self._kind is Kind.ARRAY:
            raise UnsupportedFormError("zarr FileDestination copies the store and has no media_type")
        dest = Path(destination.path)
        if dest.exists() and not destination.overwrite:
            raise FileExistsError(str(dest))
        if destination.make_parents:
            dest.parent.mkdir(parents=True, exist_ok=True)
        if self._kind is Kind.FILE:
            size = self._copy_file(dest, destination.mode, info.size_bytes or 0)
            media: str | None = info.canonical_media_type
        else:
            size = self._copy_zarr(dest, destination.mode)
            media = None
        return MaterializedResult(
            value=dest,
            source_uri=self._uri,
            resolved_uri=self._resolved_uri,
            protocol=self._protocol,
            destination=destination,
            form=Form.PATH,
            media_type=media,
            size_bytes=size,
            selection=None,
            is_reference=False,
            strategy="native",
        )

    def _copy_file(self, dest: Path, mode: int | None, expected: int) -> int:
        tmp = dest.parent / f".urisolver-{uuid.uuid4().hex}.tmp"
        try:
            with tmp.open("wb") as handle:
                size = stream_to(self._resolved_uri, self._host, handle.write, expected)
            if mode is not None:
                os.chmod(tmp, mode)
            if dest.exists():
                dest.unlink()
            os.replace(tmp, dest)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise
        return size

    def _copy_zarr(self, dest: Path, mode: int | None) -> int:
        tmp = dest.parent / f".urisolver-{uuid.uuid4().hex}.tmp"
        total = 0
        try:
            tmp.mkdir()
            for rel, raw in self._meta_files.items():
                target = tmp / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                total += len(raw)
            for level in self._levels:
                for name in chunk_names(level):
                    rel = f"{level.path}/{name}"
                    try:
                        raw = fetch(join_url(self._resolved_uri, rel), self._host)
                    except ResolutionError as exc:
                        raise MaterializationError(str(exc)) from exc
                    target = tmp / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                    total += len(raw)
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            os.replace(tmp, dest)
            if mode is not None:
                os.chmod(dest, mode)
        except Exception:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            raise
        return total


class CryoetResolver:
    """Public ``.zarr`` and ``.mrc`` objects under one HTTPS origin."""

    api_version = 1
    opaque_payload = False

    def __init__(
        self,
        *,
        base_uri: str,
        protocol_name: str,
        native_modes: frozenset[str] | None = None,
    ) -> None:
        host = _https_host(base_uri)
        if not host:
            raise ResolutionError(f"CryoET base_uri must be an https URL: {base_uri!r}")
        self.base_uri = base_uri.rstrip("/")
        self.protocol_name = protocol_name
        self.native_modes = native_modes
        self._host = host

    def resolve(self, uri: str, context: Any) -> CryoetResource:
        rel = object_path(uri)
        url = join_url(self.base_uri, rel)
        if _https_host(url) != self._host:
            raise ResolutionError(f"CryoET object URL left {self._host}: {url}")
        label = rel.rsplit("/", 1)[-1]
        if rel.endswith(".zarr"):
            levels, files = load_zarr(url, self._host)
            top = levels[0]
            return CryoetResource(
                uri=uri,
                resolved_uri=url,
                protocol=self.protocol_name,
                context=context,
                host=self._host,
                native_modes=self.native_modes,
                kind=Kind.ARRAY,
                label=label,
                size_bytes=top.nbytes,
                shape=top.shape,
                dtype=top.dtype,
                canonical_media_type=_NPY,
                levels=levels,
                meta_files=files,
            )
        size = content_length(url, self._host)
        return CryoetResource(
            uri=uri,
            resolved_uri=url,
            protocol=self.protocol_name,
            context=context,
            host=self._host,
            native_modes=self.native_modes,
            kind=Kind.FILE,
            label=label,
            size_bytes=size,
            canonical_media_type="application/octet-stream",
        )

    def close(self) -> None:
        return None


class ExampleCryoetResolver(CryoetResolver):
    """CryoET base URL named by the local resolution catalog."""

    def __init__(self) -> None:
        found = entry(SCHEME, protocol="cryoet")
        base_uri = found.get("base_uri")
        if not isinstance(base_uri, str) or not _https_host(base_uri):
            raise ResolutionError(f"resolution catalog entry for {SCHEME} needs an https base_uri")
        super().__init__(
            base_uri=base_uri,
            protocol_name=SCHEME,
            native_modes=found.get("native"),
        )
