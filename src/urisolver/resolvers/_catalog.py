"""Local resolution catalog shared by the example schemes.

Lookup order: ``catalog_path``, ``URISOLVER_CATALOG``, the repo
``examples/catalog.yaml``, then ``~/.config/urisolver/catalog.yaml``.
"""
from __future__ import annotations

import os
from pathlib import Path

from urisolver.errors import ResolutionError

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


def _native_modes(raw: dict, scheme: str) -> frozenset[str] | None:
    value = raw.get("native")
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ResolutionError(f"resolution catalog native for {scheme} must be a list of modes")
    modes = frozenset(value)
    unknown = modes - _NATIVE
    if unknown:
        raise ResolutionError(
            f"resolution catalog native for {scheme} has unknown modes: {sorted(unknown)}"
        )
    return modes


def _require_staging(staging: object, scheme: str) -> None:
    if not isinstance(staging, dict):
        raise ResolutionError(f"resolution catalog staging for {scheme} is not a mapping")
    collection = staging.get("collection")
    root = staging.get("root", "/")
    accessible = staging.get("accessible")
    if not isinstance(collection, str) or not collection:
        raise ResolutionError(f"resolution catalog staging for {scheme} has no collection")
    if not isinstance(root, str) or not root.startswith("/"):
        raise ResolutionError(f"resolution catalog staging root for {scheme} must be an absolute path")
    if (
        not isinstance(accessible, list)
        or not accessible
        or not all(isinstance(item, str) and item.startswith("/") for item in accessible)
    ):
        raise ResolutionError(
            f"resolution catalog staging accessible for {scheme} must be a list of absolute paths"
        )


def entry(scheme: str, *, protocol: str, catalog_path: str | None = None) -> dict:
    """Return one scheme entry. ``native`` is a frozenset when present."""
    catalog = _catalog_file(catalog_path)
    if not catalog.is_file():
        raise ResolutionError(f"resolution catalog not found: {catalog}")
    try:
        import yaml
    except ImportError as exc:
        raise ResolutionError("reading the resolution catalog requires pyyaml") from exc
    loaded = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or scheme not in loaded:
        raise ResolutionError(f"resolution catalog has no entry for {scheme}")
    found = loaded[scheme]
    if not isinstance(found, dict):
        raise ResolutionError(f"resolution catalog entry for {scheme} is not a mapping")
    if found.get("protocol") != protocol:
        if protocol == "tiled":
            raise ResolutionError(f"resolution catalog entry for {scheme} is not a tiled server")
        raise ResolutionError(f"resolution catalog entry for {scheme} is not a {protocol} server")
    result = dict(found)
    if protocol == "tiled":
        base_uri = result.get("base_uri")
        if not isinstance(base_uri, str) or not base_uri:
            raise ResolutionError(f"resolution catalog entry for {scheme} is not a tiled server")
        result["base_uri"] = base_uri.rstrip("/")
    elif protocol == "globus":
        collection = result.get("collection")
        if not isinstance(collection, str) or not collection:
            raise ResolutionError(f"resolution catalog entry for {scheme} has no collection")
        if result.get("staging") is not None:
            _require_staging(result.get("staging"), scheme)
    secret_id = result.get("secret_id")
    if secret_id is not None and not isinstance(secret_id, str):
        raise ResolutionError(f"resolution catalog secret_id for {scheme} is not a string")
    if not isinstance(secret_id, str):
        result.pop("secret_id", None)
    native = _native_modes(result, scheme)
    if native is not None:
        result["native"] = native
    else:
        result.pop("native", None)
    return result
