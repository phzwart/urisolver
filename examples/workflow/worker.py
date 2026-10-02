#!/usr/bin/env python3
"""Resolve one URI and materialize it to a file.

This process holds no secrets store. A credential lookup goes to the exchange
URL on argv. The bearer token is one line on stdin.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from offline import SCHEME as OFFLINE_SCHEME  # noqa: E402
from offline import OfflineResolver  # noqa: E402
from urisolver import Context, FileDestination, URIResolverError, register_resolver  # noqa: E402
from urisolver.exchange import HttpExchange  # noqa: E402
from urisolver.resolvers.example_zenodo import ZenodoRecordResolver  # noqa: E402
from urisolver.resolvers.file import FileResolver  # noqa: E402
from urisolver.secrets.exchange import ExchangeSecrets  # noqa: E402


def register() -> None:
    register_resolver("file", FileResolver(), source="example")
    register_resolver("https", ZenodoRecordResolver(), source="example")
    register_resolver(OFFLINE_SCHEME, OfflineResolver(), source="example")
    if importlib.util.find_spec("yaml") is not None:
        from urisolver.resolvers.example_globus import SCHEME as globus_scheme
        from urisolver.resolvers.example_globus import ExampleGlobusResolver
        from urisolver.resolvers.example_tiled import SCHEME as tiled_scheme
        from urisolver.resolvers.example_tiled import ExampleCatalogResolver

        register_resolver(tiled_scheme, ExampleCatalogResolver(), source="example")
        register_resolver(globus_scheme, ExampleGlobusResolver(), source="example")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        print("usage: worker.py URI DEST URL", file=sys.stderr)
        return 2
    uri, dest, url = args
    token = sys.stdin.readline().strip()
    register()
    secrets = ExchangeSecrets(HttpExchange(url, token=token))
    try:
        with Context(secrets=secrets) as ctx:
            result = ctx.resolve(uri).materialize(FileDestination(dest))
        report = {
            "value": str(result.value),
            "strategy": result.strategy,
            "source_uri": result.source_uri,
            "resolved_uri": result.resolved_uri,
        }
        json.dump(report, sys.stdout)
        sys.stdout.write("\n")
    except URIResolverError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
