#!/usr/bin/env python3
"""Write a Globus refresh token for the example catalog.

Register a native app at https://app.globus.org. The redirect URL is
https://auth.globus.org/v2/web/auth-code. The client id comes from
URISOLVER_GLOBUS_CLIENT_ID or --client-id.

The local secrets manager stores client_id and refresh_token, mode 0600.
An access token is not stored. After the secret is stored, stdout is the
path and nothing else.
"""
from __future__ import annotations

import argparse
import os
import sys

from urisolver.resolvers._catalog import entry
from urisolver.resolvers.example_globus import SCHEME
from urisolver.secrets.jsonfile import LocalSecretsManager

_TRANSFER_SCOPE = "urn:globus:auth:scope:transfer.api.globus.org:all"
_TRANSFER_RS = "transfer.api.globus.org"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Log in and store a Globus refresh token")
    parser.add_argument("--client-id", default=os.environ.get("URISOLVER_GLOBUS_CLIENT_ID"))
    args = parser.parse_args(argv)
    if not args.client_id:
        print("set URISOLVER_GLOBUS_CLIENT_ID or pass --client-id", file=sys.stderr)
        return 1
    try:
        return _run(args.client_id)
    except Exception as exc:
        status = getattr(exc, "http_status", None)
        if status:
            print(f"login failed: HTTP {status}", file=sys.stderr)
        else:
            print("login failed", file=sys.stderr)
        return 1


def _run(client_id: str) -> int:
    import globus_sdk

    found = entry(SCHEME, protocol="globus")
    collections = [found["collection"]]
    staging = found.get("staging")
    if isinstance(staging, dict) and isinstance(staging.get("collection"), str):
        collections.append(staging["collection"])
    refresh = _login(globus_sdk, client_id, [_TRANSFER_SCOPE])
    extra = _data_access(globus_sdk, client_id, refresh, collections)
    if extra:
        refresh = _login(globus_sdk, client_id, [_TRANSFER_SCOPE, *extra])
    secret_id = found.get("secret_id") or "globus-example"
    path = LocalSecretsManager.default().put_secret(
        secret_id,
        {"client_id": client_id, "refresh_token": refresh},
    )
    print(path)
    return 0


def _data_access(sdk: object, client_id: str, refresh: str, collections: list[str]) -> list:
    authorizer = sdk.RefreshTokenAuthorizer(refresh, sdk.NativeAppAuthClient(client_id))
    client = sdk.TransferClient(authorizer=authorizer)
    probe = getattr(client, "get_endpoint", None)
    if not callable(probe):
        print(
            "TransferClient.get_endpoint is unavailable; requesting the transfer scope only",
            file=sys.stderr,
        )
        return []
    scopes = []
    for collection in collections:
        try:
            info = probe(collection)
        except Exception as exc:
            status = getattr(exc, "http_status", None)
            detail = f"HTTP {status}" if status else "lookup failed"
            print(f"{collection}: {detail}", file=sys.stderr)
            continue
        entity = _entity_type(info)
        if entity == "GCSv5_mapped_collection":
            scopes.append(_data_access_scope(sdk, collection))
    return scopes


def _data_access_scope(sdk: object, collection: str) -> object:
    # globus-sdk 3 names this GCSCollectionScopeBuilder. 4.x names it GCSCollectionScopes.
    builder = getattr(sdk, "GCSCollectionScopeBuilder", None)
    if builder is None:
        from globus_sdk.scopes import GCSCollectionScopes

        builder = GCSCollectionScopes
    return builder(collection).data_access


def _entity_type(info: object) -> object:
    if isinstance(info, dict):
        return info.get("entity_type")
    data = getattr(info, "data", None)
    if isinstance(data, dict):
        return data.get("entity_type")
    return getattr(info, "entity_type", None)


def _login(sdk: object, client_id: str, scopes: list) -> str:
    auth = sdk.NativeAppAuthClient(client_id)
    auth.oauth2_start_flow(requested_scopes=scopes, refresh_tokens=True)
    print(auth.oauth2_get_authorize_url(), file=sys.stderr)
    code = input("code: ").strip()
    tokens = auth.oauth2_exchange_code_for_tokens(code)
    refresh = tokens.by_resource_server[_TRANSFER_RS]["refresh_token"]
    if not isinstance(refresh, str) or not refresh:
        raise RuntimeError("login did not return a refresh token")
    return refresh


if __name__ == "__main__":
    raise SystemExit(main())
