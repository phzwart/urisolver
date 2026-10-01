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
_NATIVE = frozenset({"memory", "file"})


def _catalog_file(catalog_path: str | None) -> Path:
    if catalog_path is not None:
        return Path(catalog_path)
    env = os.environ.get(CATALOG_ENV)
    if env:
        return Path(env)
    repo_catalog = Path(__file__).resolve().parents[3] / "examples" / "catalog.yaml"
    if repo_catalog.is_file():
        return repo_catalog
    return Path.home() / ".config" / "urisolver" / "catalog.yaml"


def _native_modes(entry: dict, scheme: str) -> frozenset[str] | None:
    raw = entry.get("native")
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        raise ResolutionError(f"resolution catalog native for {scheme} must be a list of modes")
    modes = frozenset(raw)
    unknown = modes - _NATIVE
    if unknown:
        raise ResolutionError(
            f"resolution catalog native for {scheme} has unknown modes: {sorted(unknown)}"
        )
    return modes


def _entry(catalog_path: str | None = None) -> dict:
    catalog = _catalog_file(catalog_path)
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
    secret_id = entry.get("secret_id")
    if secret_id is not None and not isinstance(secret_id, str):
        raise ResolutionError(f"resolution catalog secret_id for {SCHEME} is not a string")
    found: dict = {"base_uri": base_uri.rstrip("/")}
    if isinstance(secret_id, str):
        found["secret_id"] = secret_id
    native = _native_modes(entry, SCHEME)
    if native is not None:
        found["native"] = native
    return found


def tiled_base_uri(catalog_path: str | None = None) -> str:
    """Read this scheme's server from the local resolution catalog."""
    return _entry(catalog_path)["base_uri"]


class ExampleCatalogResolver(TiledResolver):
    """Tiled server named by the local resolution catalog."""

    def __init__(self) -> None:
        entry = _entry()
        super().__init__(
            base_uri=entry["base_uri"],
            protocol_name=SCHEME,
            secret_id=entry.get("secret_id"),
            native_modes=entry.get("native"),
        )
