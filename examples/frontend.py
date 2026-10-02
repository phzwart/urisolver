#!/usr/bin/env python3
"""Stage the three example URIs with one function.

The caller does not branch on the scheme. Each resolver is registered
explicitly. None of them is a package entry point.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from urisolver import Context, FileDestination, MemoryDestination, Registry  # noqa: E402
from urisolver.resolvers.example_globus import SCHEME as GLOBUS_SCHEME  # noqa: E402
from urisolver.resolvers.example_globus import ExampleGlobusResolver  # noqa: E402
from urisolver.resolvers.example_tiled import SCHEME as TILED_SCHEME  # noqa: E402
from urisolver.resolvers.example_tiled import ExampleCatalogResolver  # noqa: E402
from urisolver.resolvers.example_zenodo import ZenodoRecordResolver  # noqa: E402

URIS = (
    ("com.urisolver.example.tiled://examples/images/astronaut", "astronaut.npy"),
    ("https://zenodo.org/records/23025715", "pdb_cells.duckdb"),
    ("com.urisolver.example.globus:///share/godata/file1.txt", "file1.txt"),
)


def stage(uri, dest, ctx):
    r = ctx.resolve(uri)                         # access only, no bytes move
    return r.materialize(FileDestination(dest))  # the one delivery call


def build_context() -> Context:
    registry = Registry()
    registry.register(TILED_SCHEME, ExampleCatalogResolver(), source="example")
    registry.register("https", ZenodoRecordResolver(), source="example")
    registry.register(GLOBUS_SCHEME, ExampleGlobusResolver(), source="example")
    return Context(registry=registry)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--memory",
        action="store_true",
        help="materialize MemoryDestination instead of a file",
    )
    args = parser.parse_args(argv)
    with build_context() as ctx:
        for uri, dest in URIS:
            if args.memory:
                result = ctx.resolve(uri).materialize(MemoryDestination())
                print(type(result.value).__name__, result.strategy)
            else:
                result = stage(uri, dest, ctx)
                print(Path(dest).name, result.size_bytes, result.strategy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
