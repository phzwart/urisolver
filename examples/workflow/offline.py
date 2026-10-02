"""Offline stand-in for a resolver that must ask for one secret id.

A script registers it explicitly for ``com.urisolver.example.offline``.
It is not a package entry point and not one of the three frontend backends.
The path segment is the secret id. The delivered bytes are a fixed payload.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from urisolver._resource import ResourceBase
from urisolver.destinations import FileDestination, Form
from urisolver.errors import InvalidURIError, SecretLookupError, UnsupportedDestinationError
from urisolver.info import Kind, ResourceInfo
from urisolver.results import MaterializedResult

SCHEME = "com.urisolver.example.offline"
PAYLOAD = b"offline\n"


def _secret_id(uri: str) -> str:
    path = urlparse(uri).path.strip("/")
    if not path or "/" in path or urlparse(uri).query or urlparse(uri).fragment:
        raise InvalidURIError("offline URI path must be one secret id")
    return path


class _OfflineFile(ResourceBase):
    def info(self) -> ResourceInfo:
        self._ensure_valid()
        return ResourceInfo(
            uri=self._uri,
            resolved_uri=self._resolved_uri,
            protocol=self._protocol,
            kind=Kind.FILE,
            exists=True,
            media_type="application/octet-stream",
            size_bytes=len(PAYLOAD),
            canonical_media_type="application/octet-stream",
            label=PAYLOAD.decode("ascii").strip(),
        )

    def materialize(
        self,
        destination: FileDestination,
        *,
        selection: Any = None,
        **kwargs: object,
    ) -> MaterializedResult:
        self._ensure_valid()
        if selection is not None:
            raise UnsupportedDestinationError("offline files do not support selection")
        if not isinstance(destination, FileDestination):
            raise UnsupportedDestinationError(type(destination).__name__)
        dest = Path(destination.path)
        if dest.exists() and not destination.overwrite:
            raise FileExistsError(str(dest))
        if destination.make_parents:
            dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(PAYLOAD)
        return MaterializedResult(
            value=dest,
            source_uri=self._uri,
            resolved_uri=self._resolved_uri,
            protocol=self._protocol,
            destination=destination,
            form=Form.PATH,
            media_type="application/octet-stream",
            size_bytes=len(PAYLOAD),
            selection=None,
            is_reference=False,
            strategy="native",
        )


class OfflineResolver:
    """Ask for the secret id in the URI path, then deliver a fixed payload."""

    api_version = 1
    opaque_payload = False

    def resolve(self, uri: str, context: Any) -> _OfflineFile:
        secret_id = _secret_id(uri)
        provider = getattr(context, "secrets", None)
        if provider is None:
            raise SecretLookupError("secret lookup failed")
        secret = provider.get_secret(secret_id)
        if isinstance(secret, (str, bytes)) or not hasattr(secret, "items"):
            raise SecretLookupError("secret lookup failed")
        return _OfflineFile(
            uri=uri,
            resolved_uri=uri,
            protocol=SCHEME,
            context=context,
            native=None,
            capabilities=frozenset(),
            facets=frozenset(),
            allow_native=False,
        )

    def close(self) -> None:
        return None
