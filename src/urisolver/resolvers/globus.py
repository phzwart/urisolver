"""Globus Transfer resolver.

The SDK is imported on the first transfer, not when this module loads.
``resolve`` checks the path and returns a resource. Bytes move only in
``materialize``.
"""
from __future__ import annotations

import mimetypes
import os
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, unquote, urlparse

from urisolver._resource import ResourceBase
from urisolver._uriparse import split_uri
from urisolver.destinations import FileDestination, Form, MemoryDestination, ReferencePolicy
from urisolver.errors import (
    AuthenticationError,
    AuthorizationError,
    InefficientOperationError,
    InvalidURIError,
    MaterializationError,
    MemoryLimitError,
    NativeAccessDenied,
    PluginError,
    ResolutionError,
    ResourceUnavailableError,
    SecretLookupError,
    SelectionNotSupportedError,
    UnsupportedDestinationError,
    UnsupportedFormError,
    URIResolverError,
)
from urisolver.info import Kind, ResourceInfo
from urisolver.redaction import sanitize_exception
from urisolver.results import MaterializedResult

_TRANSFER_SCOPE = "urn:globus:auth:scope:transfer.api.globus.org:all"
_TIER2 = frozenset({"transfer_client", "operation_ls", "wait"})


@dataclass(frozen=True)
class StagingCollection:
    """Where a file or memory delivery lands before the caller sees it."""

    collection: str
    root: str = "/"
    accessible: tuple[str, ...] = ()


@dataclass(frozen=True)
class GlobusDestination:
    """Submit a transfer and return its task id. The transfer is not finished."""

    collection: str
    path: str
    overwrite: bool = False
    sync_level: str = "checksum"
    recursive: bool | None = None


@dataclass(frozen=True)
class _Item:
    source_path: str
    destination_path: str
    recursive: bool


@dataclass(frozen=True)
class _Submission:
    source_endpoint: str
    destination_endpoint: str
    sync_level: str
    verify_checksum: bool
    notify_on_succeeded: bool
    notify_on_failed: bool
    notify_on_inactive: bool
    items: tuple[_Item, ...]


def _sdk() -> Any:
    try:
        import globus_sdk
    except ImportError as exc:
        raise PluginError("globus resolver requires the globus extra") from exc
    return globus_sdk


def collection_path(uri: str) -> str:
    """Absolute collection path. An authority or an empty segment is invalid."""
    path, _recursive = _split_collection(uri)
    return path


def _split_collection(uri: str) -> tuple[str, bool]:
    """Return the decoded collection path and whether ``?recursive`` was set.

    The flag is not part of the path. Any other query is invalid.
    """
    try:
        body = split_uri(uri).body
    except ValueError as exc:
        raise InvalidURIError(str(exc)) from None
    path, sep, query = body.partition("?")
    if sep and query != "recursive":
        raise InvalidURIError("globus URI query must be the recursive flag")
    if path.startswith("//"):
        parsed = urlparse("http:" + path)
        if parsed.netloc:
            raise InvalidURIError("globus URI has no authority")
        path = parsed.path
    if not path.startswith("/"):
        raise InvalidURIError("globus path must be absolute")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if path == "/":
        return "/", bool(sep)
    segments = path.split("/")[1:]
    if any(segment == "" for segment in segments):
        raise InvalidURIError(f"empty path segment in {uri!r}")
    decoded = [unquote(segment) for segment in segments]
    if any(segment == "" for segment in decoded):
        raise InvalidURIError(f"empty path segment in {uri!r}")
    return "/" + "/".join(decoded), bool(sep)


def _parent_name(path: str) -> tuple[str, str]:
    if path == "/":
        return "/", ""
    parent, _, name = path.rpartition("/")
    return parent or "/", name


def _rows(payload: object) -> list:
    if isinstance(payload, dict):
        data = payload.get("DATA", payload.get("data", []))
        return list(data or [])
    data = getattr(payload, "data", None)
    if isinstance(data, dict):
        return list(data.get("DATA", []) or [])
    if isinstance(payload, list):
        return payload
    return []


def _task_id(result: object) -> str:
    if isinstance(result, dict) and "task_id" in result:
        return str(result["task_id"])
    data = getattr(result, "data", None)
    if isinstance(data, dict) and "task_id" in data:
        return str(data["task_id"])
    raise MaterializationError("transfer submit did not return a task id")


def _task_status(payload: object) -> str:
    if isinstance(payload, dict):
        return str(payload.get("status", ""))
    data = getattr(payload, "data", None)
    if isinstance(data, dict):
        return str(data.get("status", ""))
    return ""


def _media_type(path: str, kind: Kind) -> str | None:
    if kind is not Kind.FILE:
        return None
    guessed = mimetypes.guess_type(path)[0]
    return guessed or "application/octet-stream"


class _LazyChildren(Mapping[str, Any]):
    """Names from one listing. A child resource is built on lookup."""

    def __init__(self, names: tuple[str, ...], resolve_one: Callable[[str], Any]) -> None:
        self._names = names
        self._resolve_one = resolve_one

    def __getitem__(self, key: str) -> Any:
        if key not in self._names:
            raise KeyError(key)
        return self._resolve_one(key)

    def __iter__(self):
        return iter(self._names)

    def __len__(self) -> int:
        return len(self._names)


class GlobusResource(ResourceBase):
    def __init__(
        self, *, resolver: GlobusResolver, path: str, recursive: bool = False, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._resolver = resolver
        self._path = path
        self._recursive = recursive
        self._collection = resolver.collection

    def __repr__(self) -> str:
        return f"GlobusResource(collection={self._collection!r}, path={self._path!r})"

    def _deny_native(self) -> None:
        if not self._allow_native:
            raise NativeAccessDenied("native access denied by resolver policy")

    def info(self) -> ResourceInfo:
        self._ensure_valid()
        return self._resolver.describe(self._context, self._uri, self._path)

    def materialize(
        self,
        destination: FileDestination | MemoryDestination | GlobusDestination,
        *,
        selection: Any = None,
        **kwargs: object,
    ) -> MaterializedResult:
        del kwargs
        self._ensure_valid()
        if selection is not None:
            raise SelectionNotSupportedError("globus transfer has no selection")
        if isinstance(destination, GlobusDestination):
            return self._submit(destination)
        if isinstance(destination, FileDestination):
            self._require_native(destination)
            return self._to_file(destination)
        if isinstance(destination, MemoryDestination):
            self._require_native(destination)
            return self._to_memory(destination)
        raise UnsupportedDestinationError(f"unsupported destination {type(destination).__name__}")

    def transfer_client(self) -> Any:
        self._ensure_valid()
        self._deny_native()
        return self._resolver.client(self._context, self._uri)

    def operation_ls(self, path: str | None = None) -> list:
        self._ensure_valid()
        self._deny_native()
        target = self._path if path is None else path
        return self._resolver.list_path(self._context, self._uri, target)

    def wait(self, task_id: str, timeout: float | None = None) -> str:
        self._ensure_valid()
        self._deny_native()
        return self._resolver.wait_task(self._context, self._uri, task_id, timeout)

    def _require_native(self, destination: FileDestination | MemoryDestination) -> None:
        modes = self._resolver.native_modes
        if not modes or not getattr(self._context, "strict_efficiency", False):
            return
        mode = "file" if isinstance(destination, FileDestination) else "memory"
        if mode not in modes:
            raise InefficientOperationError(f"{mode} delivery is not native for this server")

    def _submit(self, destination: GlobusDestination) -> MaterializedResult:
        info = self.info()
        if not info.exists:
            raise ResolutionError(f"globus path does not exist: {self._path}")
        recursive = info.kind is Kind.CONTAINER if destination.recursive is None else destination.recursive
        if recursive and not getattr(self._context, "allow_recursive", True):
            recursive = False
        submission = _Submission(
            source_endpoint=self._collection,
            destination_endpoint=destination.collection,
            sync_level=destination.sync_level,
            verify_checksum=True,
            notify_on_succeeded=False,
            notify_on_failed=False,
            notify_on_inactive=False,
            items=(_Item(self._path, destination.path, recursive),),
        )
        result = self._resolver.submit(self._context, self._uri, submission)
        return MaterializedResult(
            value=_task_id(result),
            source_uri=self._uri,
            resolved_uri=self._resolved_uri,
            protocol=self._protocol,
            destination=destination,  # type: ignore[arg-type]
            form=Form.NATIVE,
            media_type=None,
            size_bytes=None,
            selection=None,
            is_reference=False,
            strategy="submitted",
            warnings=("transfer submitted and is not finished",),
        )

    def _to_file(self, destination: FileDestination) -> MaterializedResult:
        info = self.info()
        if not info.exists:
            raise ResolutionError(f"globus path does not exist: {self._path}")
        if destination.reference is not ReferencePolicy.COPY:
            raise UnsupportedDestinationError("globus file delivery is copy only")
        if destination.media_type is not None and info.canonical_media_type is not None:
            if destination.media_type != info.canonical_media_type:
                raise UnsupportedFormError(
                    f"requested media_type {destination.media_type!r} unsupported"
                )
        if info.kind is Kind.CONTAINER:
            if not self._recursive:
                raise UnsupportedDestinationError(
                    "directory copy requires the recursive query flag"
                )
            if not getattr(self._context, "allow_recursive", True):
                raise UnsupportedDestinationError("recursive export is disabled")
        dest = Path(destination.path)
        if dest.exists() and not destination.overwrite:
            raise FileExistsError(str(dest))
        if dest.exists() and dest.is_dir():
            raise IsADirectoryError(str(dest))
        if destination.make_parents:
            dest.parent.mkdir(parents=True, exist_ok=True)
        collection, remote = self._resolver.stage_path(dest)
        recursive = info.kind is Kind.CONTAINER
        tmp = dest.parent / f".urisolver-{uuid.uuid4().hex}.tmp"
        _, tmp_remote = self._resolver.stage_path(tmp)
        submission = _Submission(
            source_endpoint=self._collection,
            destination_endpoint=collection,
            sync_level="checksum",
            verify_checksum=True,
            notify_on_succeeded=False,
            notify_on_failed=False,
            notify_on_inactive=False,
            items=(_Item(self._path, tmp_remote, recursive),),
        )
        try:
            result = self._resolver.submit(self._context, self._uri, submission)
            task = _task_id(result)
            self._resolver.finish(self._context, self._uri, task, tmp)
            if destination.mode is not None and tmp.exists():
                os.chmod(tmp, destination.mode)
            os.replace(tmp, dest)
        except Exception:
            _discard(tmp)
            raise
        return MaterializedResult(
            value=dest,
            source_uri=self._uri,
            resolved_uri=self._resolved_uri,
            protocol=self._protocol,
            destination=destination,
            form=Form.PATH,
            media_type=info.canonical_media_type,
            size_bytes=None if recursive else dest.stat().st_size,
            selection=None,
            is_reference=False,
            strategy="native",
        )

    def _to_memory(self, destination: MemoryDestination) -> MaterializedResult:
        info = self.info()
        if not info.exists:
            raise ResolutionError(f"globus path does not exist: {self._path}")
        if destination.form in (Form.ARRAY, Form.TABLE):
            raise UnsupportedFormError(str(destination.form))
        if info.kind is Kind.CONTAINER:
            if destination.form is Form.BYTES:
                raise UnsupportedFormError("container has no byte encoding")
            names = self._resolver.child_names(self._context, self._uri, self._path)
            mapping = _LazyChildren(names, lambda name: self._child(name))
            return MaterializedResult(
                value=mapping,
                source_uri=self._uri,
                resolved_uri=self._resolved_uri,
                protocol=self._protocol,
                destination=destination,
                form=Form.NATIVE,
                media_type=None,
                size_bytes=None,
                selection=None,
                is_reference=True,
                strategy="reference",
            )
        if info.canonical_media_type is None and destination.form is Form.BYTES:
            raise UnsupportedFormError("no canonical media type")
        if destination.media_type is not None and info.canonical_media_type is not None:
            if destination.media_type != info.canonical_media_type:
                raise UnsupportedFormError(
                    f"requested media_type {destination.media_type!r} unsupported"
                )
        limit = _memory_limit(destination, self._context)
        if info.size_bytes is not None and limit is not None and info.size_bytes > limit:
            raise MemoryLimitError(
                f"resource size {info.size_bytes} exceeds memory limit {limit}"
            )
        staging = self._resolver.staging
        if staging is None or not staging.accessible:
            raise UnsupportedDestinationError(
                "no staging collection; file and memory delivery need a staging collection"
            )
        folder = Path(staging.accessible[0]) / f".urisolver-{uuid.uuid4().hex}.tmp"
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / Path(self._path).name
        collection, remote = self._resolver.stage_path(tmp)
        submission = _Submission(
            source_endpoint=self._collection,
            destination_endpoint=collection,
            sync_level="checksum",
            verify_checksum=True,
            notify_on_succeeded=False,
            notify_on_failed=False,
            notify_on_inactive=False,
            items=(_Item(self._path, remote, False),),
        )
        try:
            result = self._resolver.submit(self._context, self._uri, submission)
            self._resolver.finish(self._context, self._uri, _task_id(result), tmp)
            size = tmp.stat().st_size
            if limit is not None and size > limit:
                raise MemoryLimitError(f"resource size {size} exceeds memory limit {limit}")
            data = tmp.read_bytes()
        finally:
            _discard(folder)
        form = Form.BYTES if destination.form is Form.BYTES else Form.NATIVE
        return MaterializedResult(
            value=data,
            source_uri=self._uri,
            resolved_uri=self._resolved_uri,
            protocol=self._protocol,
            destination=destination,
            form=form,
            media_type=info.canonical_media_type,
            size_bytes=len(data),
            selection=None,
            is_reference=False,
            strategy="staged",
        )

    def _child(self, name: str) -> Any:
        from urisolver.api import resolve

        scheme = self._uri.split(":", 1)[0]
        segments = [segment for segment in self._path.split("/") if segment]
        segments.append(name)
        encoded = "/".join(quote(segment, safe="") for segment in segments)
        return resolve(f"{scheme}:/{encoded}", context=self._context)


def _memory_limit(destination: MemoryDestination, context: Any) -> int | None:
    limits = [
        value
        for value in (destination.max_bytes, getattr(context, "memory_limit", None))
        if isinstance(value, int)
    ]
    return min(limits) if limits else None


def _discard(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
    except OSError:
        return


class GlobusResolver:
    api_version = 1
    opaque_payload = False

    def __init__(
        self,
        *,
        collection: str,
        protocol_name: str,
        secret_id: str | None = None,
        staging: StagingCollection | None = None,
        native_modes: frozenset[str] | None = None,
        allow_native: bool = True,
        transfer_client: Any | None = None,
        transfer_timeout: float | None = None,
    ) -> None:
        self.collection = collection
        self.protocol_name = protocol_name
        self.secret_id = secret_id
        self.staging = staging
        self.native_modes = native_modes
        self.allow_native = allow_native
        self.transfer_timeout = transfer_timeout
        self._injected = transfer_client
        self._clients: dict[tuple[str, str | None], Any] = {}
        self._secret_values: tuple[str, ...] = ()

    def __repr__(self) -> str:
        return f"GlobusResolver(collection={self.collection!r})"

    def resolve(self, uri: str, context: Any) -> GlobusResource:
        path, recursive = _split_collection(uri)
        extra = _TIER2 if self.allow_native else frozenset()
        return GlobusResource(
            resolver=self,
            path=path,
            recursive=recursive,
            uri=uri,
            resolved_uri=uri,
            protocol=self.protocol_name,
            context=context,
            allow_native=self.allow_native,
            capabilities=extra,
        )

    def close(self) -> None:
        self._clients.clear()

    def describe(self, context: Any, uri: str, path: str) -> ResourceInfo:
        if path == "/":
            return self._info(uri, path, Kind.CONTAINER, True, None, "/")
        parent, name = _parent_name(path)

        def _list() -> list:
            return self.list_path(context, uri, parent, name_filter=name)

        try:
            rows = self._call(context, uri, ResolutionError, _list)
        except ResolutionError as exc:
            if getattr(exc, "globus_missing", False):
                return self._info(uri, path, Kind.FILE, False, None, name)
            raise
        match = next((row for row in rows if isinstance(row, dict) and row.get("name") == name), None)
        if match is None:
            return self._info(uri, path, Kind.FILE, False, None, name)
        kind = Kind.CONTAINER if str(match.get("type", "")).lower() in {"dir", "directory"} else Kind.FILE
        size = match.get("size")
        size_bytes = int(size) if kind is Kind.FILE and isinstance(size, int) else None
        return self._info(uri, path, kind, True, size_bytes, name)

    def _info(
        self, uri: str, path: str, kind: Kind, exists: bool, size_bytes: int | None, label: str
    ) -> ResourceInfo:
        return ResourceInfo(
            uri=uri,
            resolved_uri=uri,
            protocol=self.protocol_name,
            kind=kind,
            exists=exists,
            media_type=_media_type(path, kind) if exists else None,
            size_bytes=size_bytes if exists else None,
            canonical_media_type=_media_type(path, kind) if exists else None,
            label=label or None,
        )

    def child_names(self, context: Any, uri: str, path: str) -> tuple[str, ...]:
        rows = self._call(context, uri, ResolutionError, lambda: self.list_path(context, uri, path))
        names = [str(row.get("name")) for row in rows if isinstance(row, dict) and row.get("name")]
        return tuple(names)

    def list_path(self, context: Any, uri: str, path: str, *, name_filter: str | None = None) -> list:
        client = self.client(context, uri)
        kwargs: dict[str, Any] = {"path": path}
        if name_filter is not None:
            kwargs["filter"] = f"name:={name_filter}"

        def _ls() -> list:
            return _rows(client.operation_ls(self.collection, **kwargs))

        return self._call(context, uri, ResolutionError, _ls)

    def stage_path(self, local_path: Path) -> tuple[str, str]:
        staging = self.staging
        if staging is None:
            raise UnsupportedDestinationError(
                "no staging collection; file and memory delivery need a staging collection"
            )
        local = Path(local_path).resolve()
        allowed = False
        for prefix in staging.accessible:
            try:
                local.relative_to(Path(prefix).resolve())
            except ValueError:
                continue
            allowed = True
            break
        if not allowed:
            listed = ", ".join(staging.accessible) or "(none)"
            raise UnsupportedDestinationError(f"path is outside accessible staging prefixes: {listed}")
        root = Path(staging.root).resolve()
        try:
            relative = local.relative_to(root)
        except ValueError as exc:
            raise UnsupportedDestinationError(f"path is outside staging root {staging.root}") from exc
        remote = "/" + "/".join(relative.parts) if relative.parts else "/"
        return staging.collection, remote

    def submit(self, context: Any, uri: str, submission: _Submission) -> object:
        client = self.client(context, uri)

        def _send() -> object:
            module = type(client).__module__
            if module.startswith("globus_sdk"):
                sdk = _sdk()
                data = sdk.TransferData(
                    submission.source_endpoint,
                    submission.destination_endpoint,
                    sync_level=submission.sync_level,
                    verify_checksum=submission.verify_checksum,
                    notify_on_succeeded=submission.notify_on_succeeded,
                    notify_on_failed=submission.notify_on_failed,
                    notify_on_inactive=submission.notify_on_inactive,
                )
                for item in submission.items:
                    data.add_item(item.source_path, item.destination_path, recursive=item.recursive)
                return client.submit_transfer(data)
            return client.submit_transfer(submission)

        return self._call(context, uri, MaterializationError, _send)

    def finish(self, context: Any, uri: str, task_id: str, tmp: Path) -> None:
        client = self.client(context, uri)

        def _wait() -> None:
            finished = client.task_wait(
                task_id, timeout=self.transfer_timeout, polling_interval=2
            )
            if not finished:
                if self.transfer_timeout is not None:
                    self._cancel(client, task_id)
                    raise MaterializationError("transfer timed out")
                raise MaterializationError("transfer did not finish")
            status = _task_status(client.get_task(task_id))
            if status == "SUCCEEDED":
                return
            if status == "FAILED":
                raise MaterializationError(self._fatal(client, task_id))
            raise MaterializationError(f"transfer ended {status or 'unknown'}")

        self._call(context, uri, MaterializationError, _wait)
        if not tmp.exists():
            raise MaterializationError("transfer reported success but the staged file is missing")

    def wait_task(self, context: Any, uri: str, task_id: str, timeout: float | None) -> str:
        client = self.client(context, uri)
        limit = self.transfer_timeout if timeout is None else timeout

        def _wait() -> str:
            finished = client.task_wait(task_id, timeout=limit, polling_interval=2)
            if not finished:
                if limit is None:
                    raise MaterializationError("transfer did not finish")
                raise MaterializationError("transfer timed out")
            return _task_status(client.get_task(task_id))

        return self._call(context, uri, MaterializationError, _wait)

    def _secret_id_for(self, uri: str) -> str | None:
        del uri
        return self.secret_id

    def client(self, context: Any, uri: str | None = None) -> Any:
        secret_id = self._secret_id_for(uri) if uri else self.secret_id
        if self._injected is not None:
            self._note_secret(context, secret_id)
            return self._injected
        key = (self.collection, secret_id)
        cached = self._clients.get(key)
        if cached is not None:
            return cached
        secret = self._require_secret(context, secret_id)
        self._remember(secret)
        built = _transfer_client(secret)
        self._clients[key] = built
        return built

    def _require_secret(self, context: Any, secret_id: str | None) -> Mapping[str, str]:
        if not secret_id or getattr(context, "secrets", None) is None:
            raise SecretLookupError("globus resolver requires a secret")
        secret = context.secrets.get_secret(secret_id)
        if not isinstance(secret, Mapping):
            raise SecretLookupError("secret map is missing client_id")
        return secret

    def _note_secret(self, context: Any, secret_id: str | None) -> None:
        if self._secret_values or not secret_id or getattr(context, "secrets", None) is None:
            return
        try:
            secret = context.secrets.get_secret(secret_id)
        except Exception:
            return
        if isinstance(secret, Mapping):
            self._remember(secret)

    def _remember(self, secret: Mapping[str, str]) -> None:
        self._secret_values = tuple(
            value for value in secret.values() if isinstance(value, str) and value
        )

    def _call(self, context: Any, uri: str, default: type[Exception], fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except URIResolverError:
            raise
        except Exception as exc:
            raise self._wrap(exc, default, uri) from None

    def _wrap(self, exc: BaseException, default: type[Exception], uri: str) -> Exception:
        kind, scopes = _classify(exc)
        if kind == "consent":
            listed = ", ".join(str(scope) for scope in scopes) if scopes else "(unknown)"
            message = f"consent required; required_scopes: {listed}. rerun login.py"
            wrapper: type[Exception] = AuthorizationError
        elif kind == "auth":
            message = "globus authentication failed"
            wrapper = AuthenticationError
        elif kind == "authz":
            message = "globus authorization failed"
            wrapper = AuthorizationError
        elif kind == "missing":
            message = "globus path was not found"
            wrapper = ResolutionError
        elif kind == "unavailable":
            message = "globus transfer service unavailable"
            wrapper = ResourceUnavailableError
        else:
            message = str(exc) or default.__name__
            wrapper = default
        message = self._scrub(message)
        wrapped = sanitize_exception(exc, wrapper_type=wrapper, message=message, opaque_uris=(uri,))
        if kind == "missing":
            wrapped.globus_missing = True  # type: ignore[attr-defined]
        return wrapped

    def _scrub(self, message: str) -> str:
        text = message
        for value in self._secret_values:
            if len(value) >= 6 and value in text:
                text = text.replace(value, "<redacted>")
        return text

    def _cancel(self, client: Any, task_id: str) -> None:
        try:
            client.cancel_task(task_id)
        except Exception:
            return

    def _fatal(self, client: Any, task_id: str) -> str:
        try:
            events = client.task_event_list(task_id)
        except Exception:
            return "transfer failed"
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("is_error") or event.get("is_fatal"):
                detail = event.get("description") or event.get("details") or "transfer failed"
                return self._scrub(str(detail))
        return "transfer failed"


def _transfer_client(secret: Mapping[str, str]) -> Any:
    client_id = secret.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise SecretLookupError("secret map is missing client_id")
    refresh = secret.get("refresh_token")
    client_secret = secret.get("client_secret")
    if not (isinstance(refresh, str) and refresh) and not (
        isinstance(client_secret, str) and client_secret
    ):
        raise SecretLookupError("secret map is missing refresh_token or client_secret")
    sdk = _sdk()
    if isinstance(refresh, str) and refresh:
        authorizer = sdk.RefreshTokenAuthorizer(refresh, sdk.NativeAppAuthClient(client_id))
    else:
        confidential = sdk.ConfidentialAppAuthClient(client_id, client_secret)
        authorizer = sdk.ClientCredentialsAuthorizer(confidential, scopes=_TRANSFER_SCOPE)
    return sdk.TransferClient(authorizer=authorizer)


def _classify(exc: BaseException) -> tuple[str, tuple]:
    info = getattr(exc, "info", None)
    scopes: tuple = ()
    consent = False
    if isinstance(info, dict):
        consent = bool(info.get("consent_required"))
        raw_scopes = info.get("required_scopes") or ()
        scopes = tuple(raw_scopes)
    elif info is not None:
        consent = bool(getattr(info, "consent_required", False))
        raw_scopes = getattr(info, "required_scopes", ()) or ()
        scopes = tuple(raw_scopes)
    code = getattr(exc, "code", None)
    if consent or code == "ConsentRequired":
        return "consent", scopes
    if type(exc).__name__ == "NetworkError":
        return "unavailable", ()
    status = getattr(exc, "http_status", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if status == 401:
        return "auth", ()
    if status == 403:
        return "authz", ()
    if status == 404:
        return "missing", ()
    if isinstance(status, int) and status >= 500:
        return "unavailable", ()
    return "default", ()
