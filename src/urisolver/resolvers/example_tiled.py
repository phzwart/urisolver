"""Example tiled scheme. The server address comes from the local catalog.

``import urisolver`` does not import this module. The tiled SDK is imported
by ``TiledResolver`` on the first resolve, not when this module loads.
"""
from __future__ import annotations

import os
from pathlib import Path

from urisolver.errors import ResolutionError
from urisolver.resolvers.tiled import TiledResolver

SCHEME = "com.urisolver.example.tiled"
CATALOG_ENV = "URISOLVER_CATALOG"


def tiled_base_uri(catalog_path: str | None = None) -> str:
    """Read this scheme's server from the local resolution catalog."""
    path = catalog_path if catalog_path is not None else os.environ.get(CATALOG_ENV)
    if not path:
        path = "examples/catalog.yaml"
    catalog = Path(path)
    if not catalog.is_file():
        raise ResolutionError(f"resolution catalog not found: {catalog}")
    try:
        import yaml
    except ImportError as exc:
        raise ResolutionError("reading the resolution catalog requires pyyaml") from exc
    loaded = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or SCHEME not in loaded:
        raise ResolutionError(f"resolution catalog has no entry for {SCHEME}")
    entry = loaded[SCHEME]
    if not isinstance(entry, dict):
        raise ResolutionError(f"resolution catalog entry for {SCHEME} is not a mapping")
    protocol = entry.get("protocol")
    base_uri = entry.get("base_uri")
    if protocol != "tiled" or not isinstance(base_uri, str) or not base_uri:
        raise ResolutionError(f"resolution catalog entry for {SCHEME} is not a tiled server")
    return base_uri.rstrip("/")


class ExampleCatalogResolver(TiledResolver):
    """Tiled server named by the local resolution catalog."""

    def __init__(self) -> None:
        super().__init__(base_uri=tiled_base_uri(), protocol_name=SCHEME)
