"""Translate ``get_secret`` onto an :class:`~urisolver.exchange.Exchange`.

The exchange carries opaque bytes. This module is the only side that knows
the bytes are a secret lookup. A deployer supplies ``translate``, which may
wrap any source that can return a string map.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from urisolver.errors import SecretLookupError
from urisolver.exchange import Exchange, Handler

Translate = Callable[[str], Mapping[str, str]]


class ExchangeSecrets:
    """``SecretsProvider`` that asks an exchange for each ``secret_id``."""

    def __init__(self, exchange: Exchange) -> None:
        self._exchange = exchange

    def get_secret(self, secret_id: str) -> Mapping[str, str]:
        request = json.dumps({"secret_id": secret_id}).encode("utf-8")
        try:
            raw = self._exchange.exchange(request)
            payload = json.loads(raw.decode("utf-8"))
        except SecretLookupError:
            raise
        except Exception:
            raise SecretLookupError("secret lookup failed") from None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise SecretLookupError("secret lookup refused")
        secret = payload.get("secret")
        if not _is_string_map(secret):
            raise SecretLookupError("secret lookup failed")
        return {key: secret[key] for key in secret}

    def __repr__(self) -> str:
        return "ExchangeSecrets(exchange=<redacted>)"


def secrets_handler(translate: Translate) -> Handler:
    """Parent-side bytes handler for :class:`ExchangeSecrets` requests.

    ``translate`` raises :class:`SecretLookupError` to refuse an id. The
    refusal is a short status in the response bytes. The exception text is
    not copied onto the wire.
    """

    def handle(request: bytes) -> bytes:
        try:
            payload = json.loads(request.decode("utf-8"))
            if not isinstance(payload, dict):
                return _denied()
            secret_id = payload.get("secret_id")
            if not isinstance(secret_id, str):
                return _denied()
            secret = translate(secret_id)
        except Exception:
            return _denied()
        if not _is_string_map(secret):
            return _denied()
        body = {"ok": True, "secret": {key: secret[key] for key in secret}}
        return json.dumps(body).encode("utf-8")

    return handle


def _denied() -> bytes:
    return json.dumps({"ok": False, "error": "denied"}).encode("utf-8")


def _is_string_map(value: object) -> bool:
    if isinstance(value, (str, bytes)) or not isinstance(value, Mapping):
        return False
    return all(isinstance(key, str) and isinstance(item, str) for key, item in value.items())
