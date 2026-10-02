"""Example Globus scheme. The collection comes from the local catalog.

``import urisolver`` does not import this module. The Globus SDK is imported
by ``GlobusResolver`` on the first transfer, not when this module loads.
"""
from __future__ import annotations

from urisolver.resolvers._catalog import entry, select_secret_id
from urisolver.resolvers.globus import GlobusResolver, StagingCollection, collection_path

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
    """Globus collection named by the local resolution catalog.

    ``secret_id`` is the credential for every path. ``secrets`` maps a path
    prefix to another id; the longest matching prefix wins.
    """

    def __init__(self) -> None:
        found = entry(SCHEME, protocol="globus")
        super().__init__(
            collection=found["collection"],
            protocol_name=SCHEME,
            secret_id=found.get("secret_id"),
            staging=_staging(found.get("staging")),
            native_modes=found.get("native"),
            transfer_timeout=found.get("transfer_timeout"),
        )
        self._secret_prefixes: dict[str, str] = found.get("secrets") or {}

    def _secret_id_for(self, uri: str) -> str | None:
        return select_secret_id(
            collection_path(uri), default=self.secret_id, by_prefix=self._secret_prefixes
        )
