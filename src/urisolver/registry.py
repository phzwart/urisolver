"""Scheme → resolver registry (§18)."""
from __future__ import annotations
from typing import TYPE_CHECKING, Callable
from urisolver.errors import PluginConflictError, UnknownSchemeError
from urisolver.redaction import register_opaque_scheme
if TYPE_CHECKING:
    from urisolver.protocols import Resolver

ResolverFactory = Callable[[], "Resolver"]

class Registry:
    def __init__(self) -> None:
        self._instances: dict[str, Resolver] = {}
        self._factories: dict[str, ResolverFactory] = {}
        self._sources: dict[str, str] = {}
        self._overrides: dict[str, Resolver | ResolverFactory] = {}

    def register(self, scheme: str, resolver: Resolver | ResolverFactory, *, source: str = "explicit", allow_override: bool = False) -> None:
        key = scheme.lower()
        if (key in self._instances or key in self._factories) and not allow_override and key not in self._overrides:
            raise PluginConflictError(
                f"scheme {key!r} already registered by {self._sources.get(key)!r}; conflicting source {source!r}"
            )
        self._sources[key] = source
        if callable(resolver) and not hasattr(resolver, "resolve"):
            self._factories[key] = resolver  # type: ignore[assignment]
            self._instances.pop(key, None)
        else:
            self._instances[key] = resolver  # type: ignore[assignment]
            self._factories.pop(key, None)
            if getattr(resolver, "opaque_payload", False):
                register_opaque_scheme(key)

    def override(self, scheme: str, resolver: Resolver | ResolverFactory) -> None:
        key = scheme.lower()
        self._overrides[key] = resolver
        self.register(key, resolver, source="override", allow_override=True)

    def get(self, scheme: str) -> Resolver:
        key = scheme.lower()
        if key in self._overrides:
            item = self._overrides[key]
            if callable(item) and not hasattr(item, "resolve"):
                inst = item()
                self._overrides[key] = inst
                return inst  # type: ignore[return-value]
            return item  # type: ignore[return-value]
        if key in self._instances:
            return self._instances[key]
        if key in self._factories:
            inst = self._factories[key]()
            self._instances[key] = inst
            if getattr(inst, "opaque_payload", False):
                register_opaque_scheme(key)
            return inst
        raise UnknownSchemeError(f"no resolver registered for scheme {key!r}")

    def schemes(self) -> frozenset[str]:
        return frozenset(self._instances) | frozenset(self._factories) | frozenset(self._overrides)

    def close_all(self) -> None:
        seen: set[int] = set()
        for resolver in list(self._instances.values()):
            if id(resolver) in seen:
                continue
            seen.add(id(resolver))
            close = getattr(resolver, "close", None)
            if callable(close):
                close()
        self._instances.clear()

_GLOBAL = Registry()

def get_global_registry() -> Registry:
    return _GLOBAL

def register_resolver(scheme: str, resolver: "Resolver | ResolverFactory", *, source: str = "explicit") -> None:
    _GLOBAL.register(scheme, resolver, source=source)

get_global_registry = get_global_registry
