"""urisolver public exports."""
from __future__ import annotations

from urisolver.api import aresolve, close_default_context, resolve
from urisolver.context import Context, NamespaceConfig, ResolveContext
from urisolver.destinations import Destination, FileDestination, Form, MemoryDestination, ReferencePolicy
from urisolver.errors import (
    AccessError, AuthenticationError, AuthorizationError, ContextClosedError,
    InefficientOperationError, InvalidURIError, MaterializationError, MemoryLimitError,
    NamespaceNotFoundError, NamespaceResolutionError, NamespaceRestrictedError,
    NamespaceUnavailableError, NativeAccessDenied, PluginConflictError, PluginError,
    PluginVersionError, ResolutionError, ResolutionLoopError, ResourceUnavailableError,
    SecretLookupError, SelectionError, SelectionNotSupportedError, URIResolverError,
    UnknownSchemeError, UnsupportedDestinationError, UnsupportedFormError,
)
from urisolver.info import Kind, ResourceInfo
from urisolver.namespaces.base import NamespaceRequestContext, NamespaceResolution, Principal, ResolutionStatus
from urisolver.registry import Registry, register_resolver
from urisolver.results import MaterializedResult
from urisolver.secrets.base import SecretsProvider
from urisolver.selection import Native, Selection

__all__ = [
    "AccessError", "AuthenticationError", "AuthorizationError", "Context", "ContextClosedError",
    "Destination", "FileDestination", "Form", "InefficientOperationError", "InvalidURIError",
    "Kind", "MaterializationError", "MaterializedResult", "MemoryDestination", "MemoryLimitError",
    "Native", "NativeAccessDenied", "NamespaceConfig", "NamespaceNotFoundError",
    "NamespaceRequestContext", "NamespaceResolution", "NamespaceResolutionError",
    "NamespaceRestrictedError", "NamespaceUnavailableError", "PluginConflictError", "PluginError",
    "PluginVersionError", "Principal", "ReferencePolicy", "Registry", "ResolutionError",
    "ResolutionLoopError", "ResolutionStatus", "ResolveContext", "ResourceInfo",
    "ResourceUnavailableError", "SecretLookupError", "SecretsProvider", "Selection",
    "SelectionError", "SelectionNotSupportedError", "URIResolverError", "UnknownSchemeError",
    "UnsupportedDestinationError", "UnsupportedFormError", "aresolve", "close_default_context",
    "register_resolver", "resolve",
]
__version__ = "0.1.0"
