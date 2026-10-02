"""Local resolution catalog shared by the example schemes.

Lookup order: ``catalog_path``, ``URISOLVER_CATALOG``, then the bundled
catalog. The bundled file is the repo ``examples/catalog.yaml`` when that
file exists, otherwise the copy packaged with the wheel.
``~/.config/urisolver/catalog.yaml`` is merged over the bundled catalog.
An explicit path or ``URISOLVER_CATALOG`` is used whole and is not merged.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from urisolver.errors import ResolutionError

CATALOG_ENV = "URISOLVER_CATALOG"
_NATIVE = frozenset({"memory", "file"})


def _bundled_catalog() -> Path:
    repo = Path(__file__).resolve().parents[3] / "examples" / "catalog.yaml"
    if repo.is_file():
        return repo
    return Path(__file__).resolve().parents[1] / "catalog.yaml"


def _user_catalog() -> Path:
    return Path.home() / ".config" / "urisolver" / "catalog.yaml"


def _catalog_file(catalog_path: str | None) -> Path:
    if catalog_path is not None:
        return Path(catalog_path)
    env = os.environ.get(CATALOG_ENV)
    if env:
        return Path(env)
    return _bundled_catalog()


def _merge_catalog(base: dict, overlay: dict) -> dict:
    """User keys replace base keys. A scheme mapping is merged one level deep."""
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            updated = dict(current)
            updated.update(value)
            merged[key] = updated
        else:
            merged[key] = value
    return merged


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


def select_secret_id(
    path: str, *, default: str | None, by_prefix: Mapping[str, str]
) -> str | None:
    """Pick a secret id for one resource path.

    ``by_prefix`` maps a path prefix to a secret id. The longest prefix that
    is the path, or a parent of it, wins. Otherwise ``default`` is used, which
    may be ``None`` when this resource has no credential.
    """
    normalized = path.strip("/")
    best: tuple[int, str] | None = None
    for raw_prefix, secret_id in by_prefix.items():
        prefix = raw_prefix.strip("/")
        if not prefix:
            continue
        if normalized == prefix or normalized.startswith(prefix + "/"):
            if best is None or len(prefix) > best[0]:
                best = (len(prefix), secret_id)
    if best is not None:
        return best[1]
    return default


def _secret_prefixes(raw: object, scheme: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ResolutionError(f"resolution catalog secrets for {scheme} must be a mapping")
    prefixes: dict[str, str] = {}
    for prefix, secret_id in raw.items():
        if not isinstance(prefix, str) or not prefix.strip("/"):
            raise ResolutionError(
                f"resolution catalog secrets for {scheme} need a non-empty path prefix"
            )
        if not isinstance(secret_id, str) or not secret_id:
            raise ResolutionError(
                f"resolution catalog secrets for {scheme} must name a secret id"
            )
        prefixes[prefix.strip("/")] = secret_id
    return prefixes


def entry(scheme: str, *, protocol: str, catalog_path: str | None = None) -> dict:
    """Return one scheme entry. ``native`` is a frozenset when present."""
    explicit = catalog_path is not None or bool(os.environ.get(CATALOG_ENV))
    catalog = _catalog_file(catalog_path)
    if not catalog.is_file():
        raise ResolutionError(f"resolution catalog not found: {catalog}")
    try:
        import yaml
    except ImportError as exc:
        raise ResolutionError("reading the resolution catalog requires pyyaml") from exc
    loaded = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    if not explicit:
        user = _user_catalog()
        if user.is_file() and user.resolve() != catalog.resolve():
            overlay = yaml.safe_load(user.read_text(encoding="utf-8"))
            if overlay is None:
                overlay = {}
            if not isinstance(overlay, dict):
                raise ResolutionError(f"resolution catalog is not a mapping: {user}")
            if isinstance(loaded, dict):
                loaded = _merge_catalog(loaded, overlay)
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
        timeout = result.get("transfer_timeout")
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
                raise ResolutionError(
                    f"resolution catalog transfer_timeout for {scheme} must be a positive number"
                )
            result["transfer_timeout"] = float(timeout)
    secret_id = result.get("secret_id")
    if secret_id is None:
        result.pop("secret_id", None)
    elif not isinstance(secret_id, str):
        raise ResolutionError(f"resolution catalog secret_id for {scheme} is not a string")
    result["secrets"] = _secret_prefixes(result.get("secrets"), scheme)
    native = _native_modes(result, scheme)
    if native is not None:
        result["native"] = native
    else:
        result.pop("native", None)
    return result
