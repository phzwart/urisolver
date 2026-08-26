"""Error hierarchy (§25)."""
from __future__ import annotations
from datetime import timedelta

class URIResolverError(Exception):
    """Base error for all urisolver failures."""

class InvalidURIError(URIResolverError):
    """URI is malformed for scheme dispatch."""

class UnknownSchemeError(URIResolverError):
    """No resolver registered for the scheme."""

class AccessError(URIResolverError):
    """Raisable by resolve(), info(), or materialize()."""

class AuthenticationError(AccessError):
    """Caller identity not established."""

class AuthorizationError(AccessError):
    """Caller established but not permitted."""

class ResourceUnavailableError(AccessError):
    """Permitted but not currently retrievable."""
    def __init__(self, message: str = "resource unavailable", *, retry_after: timedelta | None = None):
        super().__init__(message)
        self.retry_after = retry_after

class ResolutionError(URIResolverError):
    """Failure resolving a URI to a resource."""

class ContextClosedError(ResolutionError):
    """ResolveContext that produced this resource is closed."""

class NamespaceResolutionError(URIResolverError):
    """Failure in namespace indirection."""

class NamespaceNotFoundError(NamespaceResolutionError):
    """Identifier unknown to the namespace authority."""

class NamespaceUnavailableError(NamespaceResolutionError):
    """Identifier exists but not currently retrievable."""
    def __init__(self, message: str = "namespace target unavailable", *, retry_after: timedelta | None = None):
        super().__init__(message)
        self.retry_after = retry_after

class NamespaceRestrictedError(NamespaceResolutionError):
    """Identifier exists; this caller may not have it."""

class ResolutionLoopError(NamespaceResolutionError):
    """Namespace resolution encountered a cycle."""

class MaterializationError(URIResolverError):
    """Failure materializing a resource."""

class UnsupportedDestinationError(MaterializationError):
    """Destination type not supported."""

class UnsupportedFormError(MaterializationError):
    """Requested Form or media_type unavailable."""

class MemoryLimitError(MaterializationError):
    """Would exceed configured memory limit."""

class InefficientOperationError(MaterializationError):
    """Would require read-then-select under strict_efficiency."""

class SelectionError(URIResolverError):
    """Failure applying a selection."""

class SelectionNotSupportedError(SelectionError):
    """Selection not supported for this resource."""

class NativeAccessDenied(URIResolverError):
    """Policy denies access to the native backend object."""

class SecretLookupError(URIResolverError):
    """SecretsProvider failed to retrieve a secret."""

class PluginError(URIResolverError):
    """Plugin discovery or loading failure."""

class PluginConflictError(PluginError):
    """Two distributions registered the same scheme."""

class PluginVersionError(PluginError):
    """Resolver api_version not supported by this core."""
