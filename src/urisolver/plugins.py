"""Entry-point plugin discovery (§19)."""
from __future__ import annotations
from importlib.metadata import entry_points
from typing import Any
from urisolver.errors import PluginConflictError, PluginError, PluginVersionError
from urisolver.registry import Registry, get_global_registry

SUPPORTED_API_VERSIONS = frozenset({1})
_ENUMERATED: dict[str, Any] = {}
_SOURCES: dict[str, str] = {}
_CONFLICTS: dict[str, tuple[str, str]] = {}
_LOADED = False

def _entry_points(group: str):
    eps = entry_points()
    if hasattr(eps, "select"):
        return list(eps.select(group=group))
    return list(eps.get(group, []))  # type: ignore[arg-type]

def clear_plugin_conflict(scheme: str) -> None:
    """Clear a deferred entry-point conflict after explicit registration (§19.3)."""
    _CONFLICTS.pop(scheme.lower(), None)

def get_plugin_conflicts() -> dict[str, tuple[str, str]]:
    return dict(_CONFLICTS)

def enumerate_resolver_entry_points() -> dict[str, Any]:
    global _LOADED
    found: dict[str, Any] = {}
    sources: dict[str, str] = {}
    _CONFLICTS.clear()
    for ep in _entry_points("urisolver.resolvers"):
        scheme = ep.name.lower()
        dist = getattr(ep, "dist", None)
        source = dist.name if dist is not None else ep.value
        if scheme in found:
            _CONFLICTS[scheme] = (sources[scheme], source)
            continue
        found[scheme] = ep
        sources[scheme] = source
    _ENUMERATED.clear(); _ENUMERATED.update(found)
    _SOURCES.clear(); _SOURCES.update(sources)
    _LOADED = True
    return dict(found)

def _load_resolver(scheme: str) -> Any:
    if not _LOADED:
        enumerate_resolver_entry_points()
    key = scheme.lower()
    if key in _CONFLICTS:
        a, b = _CONFLICTS[key]
        raise PluginConflictError(
            f"scheme {key!r} registered by both {a!r} and {b!r}"
        )
    if key not in _ENUMERATED:
        raise PluginError(f"no entry point for scheme {key!r}")
    try:
        obj = _ENUMERATED[key].load()
    except ImportError as exc:
        raise PluginError(f"failed to import resolver for scheme {key!r}") from exc
    resolver = obj() if isinstance(obj, type) else obj
    api_version = getattr(resolver, "api_version", None)
    if api_version not in SUPPORTED_API_VERSIONS:
        raise PluginVersionError(
            f"resolver for {key!r} declares api_version={api_version!r}; "
            f"supported={sorted(SUPPORTED_API_VERSIONS)}"
        )
    return resolver

class LazyResolverProxy:
    def __init__(self, scheme: str) -> None:
        self._scheme = scheme
        self._resolver: Any | None = None
    def _ensure(self) -> Any:
        if self._resolver is None:
            self._resolver = _load_resolver(self._scheme)
        return self._resolver
    @property
    def api_version(self) -> int:
        return self._ensure().api_version
    @property
    def opaque_payload(self) -> bool:
        return bool(getattr(self._ensure(), "opaque_payload", False))
    def resolve(self, uri: str, context: Any) -> Any:
        return self._ensure().resolve(uri, context)
    def close(self) -> None:
        if self._resolver is not None:
            self._resolver.close()

def install_entry_points(registry: Registry | None = None) -> None:
    registry = registry or get_global_registry()
    enumerated = enumerate_resolver_entry_points()
    for scheme in enumerated:
        if scheme in registry.schemes():
            continue
        registry.register(scheme, LazyResolverProxy(scheme), source=_SOURCES.get(scheme, "entry_point"))

def ensure_builtin_file_resolver(registry: Registry | None = None) -> None:
    from urisolver.resolvers.file import FileResolver
    registry = registry or get_global_registry()
    if "file" not in registry.schemes():
        registry.register("file", FileResolver(), source="urisolver")
