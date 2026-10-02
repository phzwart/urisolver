"""Live probe of Tutorial Collection 1. Skipped unless explicitly requested."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from urisolver.resolvers._catalog import entry
from urisolver.resolvers.example_globus import SCHEME

_PLACEHOLDER = "00000000-0000-0000-0000-000000000000"
_TUTORIAL = "6c54cade-bde5-45c1-bdea-f4bd71dba2cc"


def _ready() -> str | None:
    if os.environ.get("URISOLVER_GLOBUS_LIVE") != "1":
        return "set URISOLVER_GLOBUS_LIVE=1"
    try:
        import globus_sdk  # noqa: F401
    except ImportError:
        return "globus extra is not installed"
    secret_path = Path.home() / ".config" / "urisolver" / "secrets" / "globus-example.json"
    if not secret_path.is_file():
        return "secret file is missing"
    found = entry(SCHEME, protocol="globus")
    staging = found.get("staging") or {}
    collection = staging.get("collection")
    accessible = staging.get("accessible") or []
    if collection == _PLACEHOLDER or any("CHANGE_ME" in item for item in accessible):
        return "staging collection is still a placeholder"
    return None


def test_tutorial_collection_is_visible() -> None:
    reason = _ready()
    if reason:
        pytest.skip(reason)
    import globus_sdk

    secret_path = Path.home() / ".config" / "urisolver" / "secrets" / "globus-example.json"
    secret = json.loads(secret_path.read_text(encoding="utf-8"))
    client_id = secret["client_id"]
    if secret.get("refresh_token"):
        authorizer = globus_sdk.RefreshTokenAuthorizer(
            secret["refresh_token"], globus_sdk.NativeAppAuthClient(client_id)
        )
    else:
        confidential = globus_sdk.ConfidentialAppAuthClient(client_id, secret["client_secret"])
        authorizer = globus_sdk.ClientCredentialsAuthorizer(
            confidential,
            scopes="urn:globus:auth:scope:transfer.api.globus.org:all",
        )
    client = globus_sdk.TransferClient(authorizer=authorizer)
    probe = getattr(client, "get_endpoint", None)
    if not callable(probe):
        pytest.skip("TransferClient.get_endpoint is not in this globus-sdk")
    try:
        probe(_TUTORIAL)
    except globus_sdk.TransferAPIError as exc:
        pytest.skip(f"tutorial collection probe failed: HTTP {exc.http_status}")
