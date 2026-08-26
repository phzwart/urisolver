"""Module-level API (§5)."""
from __future__ import annotations
from typing import TYPE_CHECKING
from urisolver.context import ResolveContext
from urisolver.plugins import ensure_builtin_file_resolver, install_entry_points
if TYPE_CHECKING:
    from urisolver.protocols import ResolvedResource

_DEFAULT: ResolveContext | None = None
_PLUGINS_READY = False

def _ensure_plugins() -> None:
    global _PLUGINS_READY
    if not _PLUGINS_READY:
        ensure_builtin_file_resolver()
        try:
            install_entry_points()
        except Exception:
            ensure_builtin_file_resolver()
        _PLUGINS_READY = True

def _default_context() -> ResolveContext:
    global _DEFAULT
    _ensure_plugins()
    if _DEFAULT is None or _DEFAULT.closed:
        _DEFAULT = ResolveContext()
    return _DEFAULT

def resolve(uri: str, *, context: ResolveContext | None = None) -> ResolvedResource:
    """Resolve *uri*. Library code should pass an explicit context."""
    _ensure_plugins()
    ctx = context if context is not None else _default_context()
    return ctx.resolve(uri)

def close_default_context() -> None:
    """Close the process-default context. Idempotent."""
    global _DEFAULT
    if _DEFAULT is not None:
        _DEFAULT.close()
        _DEFAULT = None

async def aresolve(uri: str, *, context: ResolveContext | None = None) -> ResolvedResource:
    """Reserved async resolve name (§26)."""
    raise NotImplementedError("aresolve is reserved; core v0 has no async abstraction")
