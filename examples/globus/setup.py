#!/usr/bin/env python3
"""Record this machine's Globus Connect Personal collection.

Writes ``~/.config/urisolver/catalog.yaml``. That file is the resolution
catalog when it exists, so the placeholder staging in the repo is left
alone. This command does not store a token. Run ``login.py`` next; that
stores the credential in the local secrets manager.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from urisolver.resolvers.example_globus import SCHEME

_REPO_CATALOG = Path(__file__).resolve().parents[1] / "catalog.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write this machine's Globus staging catalog")
    parser.add_argument(
        "--collection",
        required=True,
        help="Globus Connect Personal collection UUID",
    )
    parser.add_argument(
        "--accessible",
        action="append",
        required=True,
        help="absolute local directory the collection may write (repeatable)",
    )
    parser.add_argument("--root", default="/", help="local path corresponding to collection /")
    args = parser.parse_args(argv)
    if not args.root.startswith("/"):
        print("staging root must be an absolute path", file=sys.stderr)
        return 1
    if not args.accessible or not all(path.startswith("/") for path in args.accessible):
        print("each --accessible value must be an absolute path", file=sys.stderr)
        return 1
    try:
        import yaml
    except ImportError:
        print("writing the catalog requires pyyaml", file=sys.stderr)
        return 1
    destination = Path.home() / ".config" / "urisolver" / "catalog.yaml"
    catalog = _base_catalog(yaml, destination)
    current = catalog.get(SCHEME)
    if not isinstance(current, dict):
        print(f"catalog has no {SCHEME} entry to update", file=sys.stderr)
        return 1
    current["staging"] = {
        "collection": args.collection,
        "root": args.root,
        "accessible": list(args.accessible),
    }
    catalog[SCHEME] = current
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")
    print(destination)
    return 0


def _base_catalog(yaml: object, destination: Path) -> dict:
    if destination.is_file():
        loaded = yaml.safe_load(destination.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    if _REPO_CATALOG.is_file():
        loaded = yaml.safe_load(_REPO_CATALOG.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    return {}


if __name__ == "__main__":
    raise SystemExit(main())
