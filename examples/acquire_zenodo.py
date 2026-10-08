#!/usr/bin/env python3
"""Acquire one Zenodo file into the site landing area. Skips without URISOLVER_ZENODO=1."""
from __future__ import annotations

import os


def main() -> int:
    if os.environ.get("URISOLVER_ZENODO") != "1":
        print("skip: set URISOLVER_ZENODO=1")
        return 0
    uri = os.environ.get("URISOLVER_ZENODO_URI")
    into = os.environ.get("URISOLVER_INTO")
    if not uri or not into or not os.environ.get("URISOLVER_SITE"):
        print("skip: set URISOLVER_SITE, URISOLVER_ZENODO_URI, and URISOLVER_INTO")
        return 0
    from tiled.client import from_uri

    from urisolver import register
    from urisolver.context import BindContext
    from urisolver.site import Site

    binding = register(uri, from_uri(into), mode="acquire", context=BindContext(site=Site.load()))
    print(binding.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
