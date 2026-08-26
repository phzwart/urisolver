"""Security-focused redaction tests."""

from __future__ import annotations

import pytest

from urisolver.context import ResolveContext
from urisolver.errors import AuthenticationError, MaterializationError
from urisolver.redaction import redact_message, sanitize_exception
from urisolver.resolvers.tiled import _guard


def test_sanitize_exception_strips_credentials_by_default():
    class BackendError(Exception):
        pass

    exc = BackendError("failed Authorization: Bearer SUPERSECRET download")
    wrapped = sanitize_exception(
        exc, wrapper_type=MaterializationError, retain_raw=False
    )
    assert "SUPERSECRET" not in str(wrapped)
    assert wrapped.__cause__ is None
    assert wrapped.__context__ is None


def test_sanitize_exception_retain_raw():
    class BackendError(Exception):
        pass

    exc = BackendError("token=VISIBLE")
    wrapped = sanitize_exception(
        exc, wrapper_type=MaterializationError, retain_raw=True
    )
    assert wrapped.__cause__ is exc


def test_guard_raises_without_context_leak():
    class BackendError(Exception):
        pass

    canary = "CANARY123"
    ctx = ResolveContext(retain_raw_exceptions=False)

    def backend() -> None:
        raise BackendError(f"Bearer {canary}")

    try:
        _guard(backend, context=ctx, uri="tiled://secret/path")
    except MaterializationError as raised:
        assert canary not in str(raised)
        assert raised.__context__ is None
        assert raised.__cause__ is None
    else:
        raise AssertionError("expected MaterializationError")


def test_guard_maps_auth_status():
    class HttpishError(Exception):
        def __init__(self) -> None:
            self.response = type("R", (), {"status_code": 401})()

    ctx = ResolveContext()

    def fail() -> None:
        raise HttpishError()

    with pytest.raises(AuthenticationError):
        _guard(fail, context=ctx, uri="tiled://x")


def test_guard_chain_walk_canary_not_in_traceback():
    import traceback

    class BackendError(Exception):
        pass

    canary = "CANARY_CHAIN_WALK_9f2c"
    ctx = ResolveContext(retain_raw_exceptions=False)

    def backend() -> None:
        raise BackendError(f"Authorization: Bearer {canary}")

    try:
        _guard(backend, context=ctx, uri="tiled://secret/path")
    except MaterializationError as raised:
        formatted = "".join(traceback.format_exception(type(raised), raised, raised.__traceback__))
        assert canary not in formatted
        assert raised.__context__ is None
    else:
        raise AssertionError("expected MaterializationError")


def test_opaque_payload_in_message():
    uri = "private:v1:OPAQUE_PAYLOAD_SECRET"
    text = redact_message(f"error resolving {uri}", opaque_uris=[uri])
    assert "OPAQUE_PAYLOAD_SECRET" not in text
    assert "sha256:" in text
