"""Example tiled scheme. The server address comes from the local catalog.

``import urisolver`` does not import this module. The tiled SDK is imported
by ``TiledResolver`` on the first resolve, not when this module loads.
"""
from __future__ import annotations

from urisolver.resolvers._catalog import entry
from urisolver.resolvers.tiled import TiledResolver

SCHEME = "com.urisolver.example.tiled"


def tiled_base_uri(catalog_path: str | None = None) -> str:
    """Read this scheme's server from the local resolution catalog."""
    return entry(SCHEME, protocol="tiled", catalog_path=catalog_path)["base_uri"]


class ExampleCatalogResolver(TiledResolver):
    """Tiled server named by the local resolution catalog."""

    def __init__(self) -> None:
        found = entry(SCHEME, protocol="tiled")
        super().__init__(
            base_uri=found["base_uri"],
            protocol_name=SCHEME,
            secret_id=found.get("secret_id"),
            native_modes=found.get("native"),
        )
