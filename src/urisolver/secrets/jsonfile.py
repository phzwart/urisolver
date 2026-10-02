"""Read one JSON object per secret id from a directory of mode-0600 files.

Not registered as a default secrets provider. A process that should not see
the files uses :class:`urisolver.secrets.exchange.ExchangeSecrets` instead.
"""
from __future__ import annotations

import json
import stat
from collections.abc import Mapping
from pathlib import Path

from urisolver.errors import SecretLookupError


class JsonFileSecrets:
    """``<directory>/<secret_id>.json`` as a flat string map."""

    def __init__(self, directory: Path | str) -> None:
        self._directory = Path(directory)

    def get_secret(self, secret_id: str) -> Mapping[str, str]:
        path = self._directory / f"{secret_id}.json"
        try:
            mode = path.stat().st_mode
        except OSError as exc:
            raise SecretLookupError("secret file is not readable") from exc
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise SecretLookupError("secret file is group or world readable")
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SecretLookupError("secret file is not readable") from exc
        if isinstance(loaded, (str, bytes)) or not isinstance(loaded, dict):
            raise SecretLookupError("secret file is not a string map")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in loaded.items()):
            raise SecretLookupError("secret file is not a string map")
        return {key: loaded[key] for key in loaded}

    def __repr__(self) -> str:
        return f"JsonFileSecrets({str(self._directory)!r})"
