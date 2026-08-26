"""Shared ResolvedResource binding helper (not a required ABC — §35)."""
from __future__ import annotations
from typing import Any
from urisolver.errors import ContextClosedError, NativeAccessDenied
from urisolver.redaction import is_opaque_scheme, redact_uri

class ResourceBase:
    _TIER0 = frozenset({"info", "materialize", "facets", "facet", "supports", "capabilities"})

    def __init__(
        self,
        *,
        uri: str,
        resolved_uri: str,
        protocol: str,
        context: Any,
        native: Any = None,
        capabilities: frozenset[str] | None = None,
        facets: frozenset[str] | None = None,
        allow_native: bool = True,
        resolution_trail: tuple[str, ...] = (),
    ) -> None:
        self._uri = uri
        self._resolved_uri = resolved_uri
        self._protocol = protocol
        self._context = context
        self._native = native
        self._capabilities = frozenset(capabilities or ())
        self._facets = frozenset(facets or ())
        self._allow_native = allow_native
        self._resolution_trail = resolution_trail
        self._invalid = False
        self._facet_objects: dict[str, Any] = {}

    def _bind_request_uri(self, uri: str, *, trail: tuple[str, ...] = ()) -> None:
        self._uri = uri
        if trail:
            self._resolution_trail = trail

    def _invalidate(self) -> None:
        self._invalid = True

    def _ensure_valid(self) -> None:
        if self._invalid or getattr(self._context, "closed", False):
            raise ContextClosedError("resource is bound to a closed ResolveContext")

    @property
    def uri(self) -> str:
        return self._uri

    @property
    def resolved_uri(self) -> str:
        return self._resolved_uri

    @property
    def protocol(self) -> str:
        return self._protocol

    def facets(self) -> frozenset[str]:
        self._ensure_valid()
        return self._facets

    def facet(self, name: str) -> object:
        self._ensure_valid()
        if name not in self._facets:
            raise KeyError(name)
        return self._facet_objects[name]

    def supports(self, name: str) -> bool:
        self._ensure_valid()
        if name in self._TIER0:
            return True
        return name in self._capabilities

    def capabilities(self) -> frozenset[str]:
        self._ensure_valid()
        return self._capabilities

    @property
    def native(self) -> object:
        self._ensure_valid()
        if not self._allow_native:
            raise NativeAccessDenied("native access denied by resolver policy")
        return self._native

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        self._ensure_valid()
        if name not in self._capabilities:
            raise AttributeError(name)
        target = getattr(self._native, name, None)
        if target is None:
            raise AttributeError(name)
        return target

    def __getstate__(self) -> None:
        raise TypeError(
            "ResolvedResource is not picklable; ship the URI and re-resolve "
            "inside the worker against a worker-local context"
        )

    def __repr__(self) -> str:
        scheme = self._uri.split(":", 1)[0] if ":" in self._uri else ""
        opaque = is_opaque_scheme(self._protocol) or is_opaque_scheme(scheme)
        return (
            f"{type(self).__name__}(uri={redact_uri(self._uri, opaque=opaque)!r}, "
            f"protocol={self._protocol!r})"
        )
