"""Upstream API keys for the proxy adapters.

``URISOLVER_PROXY_CREDENTIALS`` is a JSON file mapping a normalized upstream
base URI to ``{"api_key": "..."}``. The file mode must be ``0600`` or stricter.
A missing entry means the upstream is anonymous. Keys are never logged.
"""
from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from urllib.parse import urlparse

from urisolver.errors import SecretLookupError

ENV = "URISOLVER_PROXY_CREDENTIALS"
_LOGGED: set[str] = set()
_LOGGER = logging.getLogger("urisolver.tiled_server")


def normalize_base(uri: str) -> str:
    """Scheme, host, port, and path, with the trailing slash removed."""
    parsed = urlparse(uri)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{host}{path}"


def api_key_for(base: str) -> str | None:
    """Return the API key for ``base``, or None when the upstream is anonymous."""
    path = os.environ.get(ENV)
    if not path:
        return None
    file = Path(path)
    try:
        mode = file.stat().st_mode
    except OSError as exc:
        raise SecretLookupError("proxy credential file is not readable") from exc
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        message = f"proxy credential file mode {mode & 0o777:03o} is too open"
        if str(file) not in _LOGGED:
            _LOGGED.add(str(file))
            _LOGGER.error(message)
        raise SecretLookupError(message)
    try:
        loaded = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecretLookupError("proxy credential file is not readable") from exc
    if not isinstance(loaded, dict):
        raise SecretLookupError("proxy credential file is not a mapping")
    entry = loaded.get(normalize_base(base))
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise SecretLookupError("proxy credential entry is not a mapping")
    api_key = entry.get("api_key")
    if api_key is None:
        return None
    if not isinstance(api_key, str) or not api_key:
        raise SecretLookupError("proxy credential entry has no api_key")
    return api_key
