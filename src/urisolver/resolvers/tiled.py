"""Tiled resolver (§27.2). Optional: urisolver[tiled]."""
from __future__ import annotations
import io
import uuid
from pathlib import Path
from typing import Any, Callable, Sequence, TypeVar
from urllib.parse import urlparse
from urisolver._resource import ResourceBase
from urisolver._uriparse import split_uri
from urisolver.destinations import FileDestination, Form, MemoryDestination, ReferencePolicy
from urisolver.errors import (
    AuthenticationError, AuthorizationError, InefficientOperationError, MaterializationError,
    MemoryLimitError, PluginError, ResolutionError, UnsupportedDestinationError, UnsupportedFormError,
)
from urisolver.info import Kind, ResourceInfo
from urisolver.redaction import sanitize_exception
from urisolver.results import MaterializedResult
from urisolver.selection import Native, Selection

_T = TypeVar("_T")

def _require_tiled():
    try:
        import tiled.client as tiled_client  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PluginError("tiled resolver requires tiled; install urisolver[tiled]") from exc
    return tiled_client

def _wrapper_for(exc: BaseException) -> type[Exception]:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status == 401:
        return AuthenticationError
    if status == 403:
        return AuthorizationError
    if status is not None and 400 <= int(status) < 500:
        return AuthorizationError
    return MaterializationError

def _build_wrapped_error(
    exc: BaseException,
    *,
    context: Any,
    uri: str,
    default: type[Exception] = MaterializationError,
) -> Exception:
    retain = bool(getattr(context, "retain_raw_exceptions", False))
    mapped = _wrapper_for(exc)
    wrapper = mapped if mapped is not MaterializationError else default
    return sanitize_exception(
        exc,
        wrapper_type=wrapper,
        retain_raw=retain,
        opaque_uris=[uri],
    )

def _guard(fn: Callable[..., _T], /, *args: Any, context: Any, uri: str, **kwargs: Any) -> _T:
    err: Exception | None = None
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        err = _build_wrapped_error(exc, context=context, uri=uri)
    if err is not None:
        raise err
    raise RuntimeError("unreachable")

class _ArrayFacet:
    def __init__(self, node: Any) -> None:
        self._node = node
        structure = getattr(node, "structure", None)
        if callable(structure):
            structure = structure()
        self.shape = tuple(getattr(structure, "shape", getattr(node, "shape", ())) or ())
        dtype = getattr(structure, "data_type", None) or getattr(node, "dtype", "float64")
        self.dtype = str(getattr(dtype, "name", dtype))
        chunks = getattr(structure, "chunks", None)
        self.chunks = tuple(tuple(c) for c in chunks) if chunks else None
    def __getitem__(self, selection: object) -> object:
        return self._node[selection]

class _TableFacet:
    def __init__(self, node: Any) -> None:
        self._node = node
        columns = getattr(node, "columns", None)
        if columns is None:
            structure = getattr(node, "structure", None)
            if callable(structure):
                structure = structure()
            columns = getattr(structure, "columns", ())
        self.columns = tuple(columns or ())
        shape = getattr(node, "shape", None)
        self.num_rows = shape[0] if shape else None
    def read(self, columns: Sequence[str] | None = None) -> object:
        if hasattr(self._node, "read"):
            return self._node.read(columns) if columns is not None else self._node.read()
        return self._node[:]

class _ContainerFacet:
    def __init__(self, node: Any, resource: "TiledResolvedResource") -> None:
        self._node = node
        self._resource = resource
    def keys(self):
        return self._node.keys()
    def __getitem__(self, key: str) -> "TiledResolvedResource":
        child = self._node[key]
        child_uri = f"{self._resource.uri.rstrip('/')}/{key}"
        return TiledResolvedResource(
            uri=child_uri, resolved_uri=child_uri, node=child,
            context=self._resource._context, resolver=self._resource._resolver,
            allow_native=self._resource._allow_native,
        )
    def __len__(self) -> int:
        return len(self._node)

def _kind_for(node: Any) -> Kind:
    family = getattr(node, "structure_family", None)
    if family is not None:
        name = str(getattr(family, "value", family)).lower()
        if "array" in name or "xarray" in name:
            return Kind.ARRAY
        if name in {"table", "dataframe", "awkward"}:
            return Kind.TABLE
        if name in {"container", "node"}:
            return Kind.CONTAINER
        if name in {"blob", "file"}:
            return Kind.FILE
    if hasattr(node, "keys") and callable(node.keys) and not hasattr(node, "read"):
        return Kind.CONTAINER
    if hasattr(node, "shape") and hasattr(node, "__getitem__"):
        return Kind.ARRAY
    return Kind.OPAQUE

def _canonical(kind: Kind) -> str | None:
    if kind is Kind.ARRAY:
        return "application/x-npy"
    if kind is Kind.TABLE:
        return "application/vnd.apache.arrow.file"
    if kind is Kind.FILE:
        return "application/octet-stream"
    return None

def _caps(node: Any) -> frozenset[str]:
    return frozenset(a for a in ("read", "read_block", "structure", "search", "export") if hasattr(node, a))

class TiledResolvedResource(ResourceBase):
    def __init__(self, *, uri: str, resolved_uri: str, node: Any, context: Any, resolver: "TiledResolver", allow_native: bool = True) -> None:
        self._node = node
        self._resolver = resolver
        kind = _kind_for(node)
        facets: set[str] = set()
        if kind is Kind.ARRAY: facets.add("array")
        if kind is Kind.TABLE: facets.add("table")
        if kind is Kind.CONTAINER: facets.add("container")
        super().__init__(
            uri=uri, resolved_uri=resolved_uri, protocol=resolver.protocol_name, context=context,
            native=node, capabilities=_caps(node), facets=frozenset(facets), allow_native=allow_native,
        )
        if "array" in facets: self._facet_objects["array"] = _ArrayFacet(node)
        if "table" in facets: self._facet_objects["table"] = _TableFacet(node)
        if "container" in facets: self._facet_objects["container"] = _ContainerFacet(node, self)
        self._kind = kind

    def info(self) -> ResourceInfo:
        self._ensure_valid()
        shape = dtype = None
        if self._kind is Kind.ARRAY and "array" in self._facet_objects:
            facet = self._facet_objects["array"]
            shape, dtype = facet.shape, facet.dtype
        media = _canonical(self._kind)
        return ResourceInfo(
            uri=self._uri, resolved_uri=self._resolved_uri, protocol=self._protocol,
            kind=self._kind, exists=True, media_type=media, shape=shape, dtype=dtype,
            canonical_media_type=media,
        )

    def materialize(self, destination: FileDestination | MemoryDestination, *, selection: Selection | None = None, **kwargs: object) -> MaterializedResult:
        self._ensure_valid()
        info = self.info()
        sel = selection.value if isinstance(selection, Native) else selection
        if isinstance(destination, MemoryDestination):
            return self._to_memory(destination, info, sel)
        if isinstance(destination, FileDestination):
            return self._to_file(destination, info, sel)
        raise UnsupportedDestinationError(type(destination).__name__)

    def _read(self, selection: Any) -> tuple[Any, str, tuple[str, ...]]:
        node = self._node
        if selection is None:
            if hasattr(node, "read"):
                return _guard(node.read, context=self._context, uri=self._uri), "native", ()
            if hasattr(node, "__getitem__"):
                return _guard(node.__getitem__, Ellipsis, context=self._context, uri=self._uri), "native", ()
            return node, "native", ()
        try:
            if hasattr(node, "__getitem__"):
                return _guard(node.__getitem__, selection, context=self._context, uri=self._uri), "native-selection", ()
        except (TypeError, IndexError, KeyError, ValueError):
            pass
        if getattr(self._context, "strict_efficiency", False):
            raise InefficientOperationError("selection requires read-then-select under strict_efficiency")
        if hasattr(node, "read"):
            full = _guard(node.read, context=self._context, uri=self._uri)
        elif hasattr(node, "__getitem__"):
            full = _guard(node.__getitem__, Ellipsis, context=self._context, uri=self._uri)
        else:
            full = node
        return full[selection], "read-then-select", (
            "selection applied locally after full retrieval (strategy=read-then-select)",
        )

    def _to_bytes(self, info: ResourceInfo, selection: Any) -> tuple[bytes, str, tuple[str, ...]]:
        value, strategy, warnings = self._read(selection)
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value), strategy, warnings
        if info.canonical_media_type == "application/x-npy":
            try:
                import numpy as np
            except ImportError as exc:
                raise UnsupportedFormError("application/x-npy requires numpy") from exc
            buf = io.BytesIO(); np.save(buf, value)
            return buf.getvalue(), "converted", warnings
        raise UnsupportedFormError(f"cannot serialize to {info.canonical_media_type!r}")

    def _to_memory(self, destination: MemoryDestination, info: ResourceInfo, selection: Any) -> MaterializedResult:
        form = destination.form
        if info.kind is Kind.CONTAINER:
            if form is Form.BYTES:
                raise UnsupportedFormError("container has no canonical_media_type")
            if form is not Form.NATIVE:
                raise UnsupportedFormError(str(form))
            facet = self._facet_objects["container"]
            mapping = {k: facet[k] for k in facet.keys()}
            return MaterializedResult(
                value=mapping, source_uri=self._uri, resolved_uri=self._resolved_uri, protocol=self._protocol,
                destination=destination, form=Form.NATIVE, media_type=None, size_bytes=None,
                selection=None, is_reference=True, strategy="reference",
            )
        if form is Form.BYTES:
            if info.canonical_media_type is None:
                raise UnsupportedFormError("no canonical_media_type declared")
            if destination.media_type is not None and destination.media_type != info.canonical_media_type:
                raise UnsupportedFormError(f"requested media_type {destination.media_type!r} unsupported")
            data, strategy, warnings = self._to_bytes(info, selection)
            max_bytes = destination.max_bytes if destination.max_bytes is not None else getattr(self._context, "memory_limit", None)
            if max_bytes is not None and len(data) > max_bytes:
                raise MemoryLimitError(f"size {len(data)} exceeds limit {max_bytes}")
            return MaterializedResult(
                value=data, source_uri=self._uri, resolved_uri=self._resolved_uri, protocol=self._protocol,
                destination=destination, form=Form.BYTES, media_type=info.canonical_media_type,
                size_bytes=len(data), selection=selection, is_reference=False,
                strategy="converted" if strategy == "native" else strategy, warnings=warnings,
            )
        if form is Form.ARRAY and info.kind is not Kind.ARRAY:
            raise UnsupportedFormError(str(form))
        if form is Form.TABLE and info.kind is not Kind.TABLE:
            raise UnsupportedFormError(str(form))
        value, strategy, warnings = self._read(selection)
        return MaterializedResult(
            value=value, source_uri=self._uri, resolved_uri=self._resolved_uri, protocol=self._protocol,
            destination=destination, form=form, media_type=None, size_bytes=None,
            selection=selection, is_reference=False, strategy=strategy, warnings=warnings,
        )

    def _to_file(self, destination: FileDestination, info: ResourceInfo, selection: Any) -> MaterializedResult:
        if destination.reference is not ReferencePolicy.COPY:
            raise UnsupportedDestinationError(
                f"Tiled resolver only supports reference={ReferencePolicy.COPY.value!r}"
            )
        if info.kind is Kind.CONTAINER and info.canonical_media_type is None:
            raise UnsupportedDestinationError("container FileDestination requires canonical_media_type")
        if destination.media_type is not None and destination.media_type != info.canonical_media_type:
            raise UnsupportedFormError(f"requested media_type {destination.media_type!r} unsupported")
        if info.canonical_media_type is None:
            raise UnsupportedFormError("no canonical_media_type for byte-level delivery")
        dest = Path(destination.path)
        if dest.exists() and not destination.overwrite:
            raise FileExistsError(str(dest))
        if destination.make_parents:
            dest.parent.mkdir(parents=True, exist_ok=True)
        data, strategy, warnings = self._to_bytes(info, selection)
        tmp = dest.parent / f".urisolver-{uuid.uuid4().hex}.tmp"
        try:
            tmp.write_bytes(data)
            if destination.mode is not None:
                tmp.chmod(destination.mode)
            tmp.replace(dest)
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise
        return MaterializedResult(
            value=dest, source_uri=self._uri, resolved_uri=self._resolved_uri, protocol=self._protocol,
            destination=destination, form=Form.PATH, media_type=info.canonical_media_type,
            size_bytes=len(data), selection=selection, is_reference=False,
            strategy="converted" if strategy == "native" else strategy, warnings=warnings,
        )

class TiledResolver:
    api_version = 1
    opaque_payload = False
    def __init__(self, *, base_uri: str | None = None, protocol_name: str = "tiled", secret_id: str | None = None, allow_native: bool = True, client: Any | None = None) -> None:
        self.base_uri = base_uri
        self.protocol_name = protocol_name
        self.secret_id = secret_id
        self.allow_native = allow_native
        self._client = client
        self._injected_client = client is not None
        self._sessions: dict[str, Any] = {}
    def _get_client(self, context: Any) -> Any:
        if self._client is not None:
            return self._client
        key = self.base_uri or "default"
        if key in self._sessions:
            return self._sessions[key]
        tiled_client = _require_tiled()
        kwargs: dict[str, Any] = {}
        if self.secret_id and getattr(context, "secrets", None) is not None:
            secret = context.secrets.get_secret(self.secret_id)
            if "api_key" in secret: kwargs["api_key"] = secret["api_key"]
            if "token" in secret: kwargs["headers"] = {"Authorization": f"Bearer {secret['token']}"}
        try:
            client = tiled_client.from_uri(self.base_uri or "http://localhost:8000", **kwargs)
        except Exception as exc:
            raise _build_wrapped_error(exc, context=context, uri=self.base_uri or "tiled://") from None
        self._sessions[key] = client
        return client
    def resolve(self, uri: str, context: Any) -> TiledResolvedResource:
        parts = split_uri(uri)
        body = parts.body
        if len(body) >= 2 and body[0:2] == "//":
            parsed = urlparse("http:" + body)
            path = f"{parsed.netloc}{parsed.path}"
        else:
            path = body
        path = path.strip("/")
        try:
            node: Any = self._get_client(context)
            if path:
                for part in path.split("/"):
                    if part:
                        node = _guard(node.__getitem__, part, context=context, uri=uri)
        except Exception as exc:
            raise _build_wrapped_error(exc, context=context, uri=uri, default=ResolutionError) from None
        return TiledResolvedResource(uri=uri, resolved_uri=uri, node=node, context=context, resolver=self, allow_native=self.allow_native)
    def close(self) -> None:
        self._sessions.clear()
        if not self._injected_client:
            self._client = None
