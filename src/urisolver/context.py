"""ResolveContext — session ownership (§5, §23)."""
from __future__ import annotations
import uuid
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urisolver.errors import (
    ContextClosedError, InvalidURIError, NamespaceNotFoundError, NamespaceResolutionError,
    NamespaceRestrictedError, NamespaceUnavailableError, ResolutionLoopError,
)
from urisolver.namespaces.base import (
    NamespaceCache, NamespaceRequestContext, NamespaceResolver, Principal, ResolutionStatus,
)
from urisolver._uriparse import SplitURI, split_uri
from urisolver.registry import Registry, get_global_registry
if TYPE_CHECKING:
    from urisolver.protocols import ResolvedResource
    from urisolver.secrets.base import SecretsProvider

@dataclass
class NamespaceConfig:
    resolvers: dict[str, NamespaceResolver] = field(default_factory=dict)
    default_ttl_seconds: int = 300

@dataclass
class ResolveContext:
    secrets: SecretsProvider | None = None
    registry: Registry | None = None
    namespaces: NamespaceConfig | None = None
    memory_limit: int | None = 2 * 2**30
    strict_efficiency: bool = False
    allow_recursive: bool = True
    namespace_cache: bool = True
    max_resolution_depth: int = 4
    tmpdir: Path | None = None
    retain_raw_exceptions: bool = False
    principal: Principal | None = None

    _closed: bool = field(default=False, init=False, repr=False)
    _instantiated: list[Any] = field(default_factory=list, init=False, repr=False)
    _resources: weakref.WeakSet[Any] = field(default_factory=weakref.WeakSet, init=False, repr=False)
    _cache: NamespaceCache | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.registry is None:
            self.registry = get_global_registry()
        if self.namespace_cache:
            from datetime import timedelta
            ttl = self.namespaces.default_ttl_seconds if self.namespaces else 300
            self._cache = NamespaceCache(default_ttl=timedelta(seconds=ttl))

    def __enter__(self) -> ResolveContext:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for resource in list(self._resources):
            inv = getattr(resource, "_invalidate", None)
            if callable(inv):
                inv()
        self._resources.clear()
        for resolver in self._instantiated:
            close = getattr(resolver, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        self._instantiated.clear()
        if self._cache is not None:
            self._cache.clear()

    def _ensure_open(self) -> None:
        if self._closed:
            raise ContextClosedError("ResolveContext is closed")

    def track_resource(self, resource: Any) -> None:
        self._resources.add(resource)

    def track_resolver(self, resolver: Any) -> None:
        if resolver not in self._instantiated:
            self._instantiated.append(resolver)

    def _parse_uri(self, uri: str) -> SplitURI:
        try:
            return split_uri(uri)
        except ValueError as exc:
            raise InvalidURIError(str(exc)) from exc

    def resolve(self, uri: str) -> ResolvedResource:
        self._ensure_open()
        self._parse_uri(uri)
        return self._resolve_chain(uri, depth=0, seen=set())

    def _resolve_chain(self, uri: str, *, depth: int, seen: set[str], trail: list[str] | None = None) -> ResolvedResource:
        if trail is None:
            trail = []
        if depth > self.max_resolution_depth:
            raise ResolutionLoopError(f"resolution depth exceeded max_resolution_depth={self.max_resolution_depth}")
        parts = self._parse_uri(uri)
        key = parts.scheme + ":" + uri[len(parts.raw_scheme) + 1 :]
        if key in seen:
            raise ResolutionLoopError(f"resolution loop detected at {uri!r}")
        seen = set(seen); seen.add(key)
        scheme = parts.scheme

        if self.namespaces is not None and scheme in self.namespaces.resolvers:
            identifier = parts.body
            if parts.body.startswith("//"):
                raise InvalidURIError(
                    f"namespace scheme {scheme!r} defines no authority component; "
                    f"{uri!r} uses '//' after the scheme (RFC 7595 §3.2). "
                    f"Use the opaque form {scheme}:<identifier>."
                )
            ns = self._resolve_namespace(scheme, identifier)
            if ns.status is ResolutionStatus.NOT_FOUND:
                raise NamespaceNotFoundError(f"namespace {scheme!r}: not found")
            if ns.status is ResolutionStatus.RESTRICTED:
                raise NamespaceRestrictedError(ns.detail or f"namespace {scheme!r}: restricted")
            if ns.status is ResolutionStatus.UNAVAILABLE:
                raise NamespaceUnavailableError(
                    ns.detail or f"namespace {scheme!r}: unavailable", retry_after=ns.retry_after
                )
            if ns.uri is None:
                raise NamespaceResolutionError(f"namespace {scheme!r} returned AVAILABLE without uri")
            trail = trail + [uri]
            target = _inherit_fragment(ns.uri, parts.fragment)
            resource = self._resolve_chain(target, depth=depth + 1, seen=seen, trail=trail)
            bind = getattr(resource, "_bind_request_uri", None)
            if callable(bind):
                bind(uri, trail=tuple(trail))
            return resource

        assert self.registry is not None
        resolver = self.registry.get(scheme)
        self.track_resolver(resolver)
        resource = resolver.resolve(uri, self)
        self.track_resource(resource)
        return resource

    def _resolve_namespace(self, namespace: str, identifier: str):
        assert self.namespaces is not None
        principal_id = self.principal.id if self.principal else None
        if self._cache is not None:
            cached = self._cache.get(namespace, identifier, principal_id)
            if cached is not None:
                return cached
        resolver = self.namespaces.resolvers[namespace]
        req = NamespaceRequestContext(
            principal=self.principal, secrets=self.secrets, request_id=str(uuid.uuid4())
        )
        result = resolver.resolve_namespace(identifier, req)
        if self._cache is not None:
            self._cache.put(namespace, identifier, principal_id, result)
        return result

Context = ResolveContext


def _inherit_fragment(target: str, fragment: str | None) -> str:
    """Carry a request fragment onto a namespace target.

    Mirrors RFC 9110 §10.2.2: a target that names its own fragment keeps it;
    otherwise the fragment of the request is inherited.
    """
    if fragment is None:
        return target
    if "#" in target:
        return target
    return f"{target}#{fragment}"
