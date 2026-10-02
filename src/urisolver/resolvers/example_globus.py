"""Example Globus scheme. The collection comes from the local catalog.

``import urisolver`` does not import this module. The Globus SDK is imported
by ``GlobusResolver`` on the first transfer, not when this module loads.
"""
from __future__ import annotations

from urisolver.resolvers._catalog import entry
from urisolver.resolvers.globus import GlobusResolver, StagingCollection

SCHEME = "com.urisolver.example.globus"


def _staging(raw: object) -> StagingCollection | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    accessible = raw.get("accessible") or ()
    return StagingCollection(
        collection=str(raw["collection"]),
        root=str(raw.get("root", "/")),
        accessible=tuple(accessible),
    )


class ExampleGlobusResolver(GlobusResolver):
    """Globus collection named by the local resolution catalog."""

    def __init__(self) -> None:
        found = entry(SCHEME, protocol="globus")
        super().__init__(
            collection=found["collection"],
            protocol_name=SCHEME,
            secret_id=found.get("secret_id"),
            staging=_staging(found.get("staging")),
            native_modes=found.get("native"),
        )
