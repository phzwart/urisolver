#!/usr/bin/env python3
"""Proxy an upstream Tiled array or table.

Skips unless URISOLVER_SITE, URISOLVER_TILED_URI, and URISOLVER_INTO are set.
TILED_UPSTREAM_API_KEY is the site secret used at registration. The server
process reads a different file, written by ``urisolver proxy credentials``
and named by URISOLVER_PROXY_CREDENTIALS. The worker client never receives
that upstream key.
"""
from __future__ import annotations

import os


def main() -> int:
    uri = os.environ.get("URISOLVER_TILED_URI")
    into = os.environ.get("URISOLVER_INTO")
    if not uri or not into or not os.environ.get("URISOLVER_SITE"):
        print("skip: set URISOLVER_SITE, URISOLVER_TILED_URI, and URISOLVER_INTO")
        return 0
    from tiled.client import from_uri

    from urisolver import register
    from urisolver.context import BindContext
    from urisolver.site import Site

    class Secrets:
        def get_secret(self, secret_id: str):
            return {"api_key": os.environ.get("TILED_UPSTREAM_API_KEY", "")}

    binding = register(
        uri,
        from_uri(into),
        context=BindContext(site=Site.load(), secrets=Secrets()),
    )
    print(binding.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
