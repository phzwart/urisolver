#!/usr/bin/env python3
"""Reference a file the server can already read.

Skips unless URISOLVER_SITE, URISOLVER_FILE_URI, and URISOLVER_INTO are set.
"""
from __future__ import annotations

import os


def main() -> int:
    uri = os.environ.get("URISOLVER_FILE_URI")
    into = os.environ.get("URISOLVER_INTO")
    if not uri or not into or not os.environ.get("URISOLVER_SITE"):
        print("skip: set URISOLVER_SITE, URISOLVER_FILE_URI, and URISOLVER_INTO")
        return 0
    from tiled.client import from_uri

    from urisolver import register
    from urisolver.context import BindContext
    from urisolver.site import Site

    binding = register(uri, from_uri(into), context=BindContext(site=Site.load()))
    print(binding.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
