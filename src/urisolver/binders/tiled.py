"""tiled: binder. EXISTING, PROXY, and ACQUIRE are filled in by later phases."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from urisolver.bind import Acquisition, BinderPlan, Mode
from urisolver.context import BindContext
from urisolver.site import Source


class TiledBinder:
    api_version = 2
    protocol = "tiled"
    opaque_payload = False

    def validate_source(self, source: Source) -> None:
        return None

    def feasible_modes(
        self, uri: str, source: Source | None, into: Any, ctx: BindContext
    ) -> list[tuple[Mode, str | None]]:
        raise NotImplementedError("tiled binder is not implemented yet")

    def plan(
        self, uri: str, source: Source | None, into: Any, ctx: BindContext, *, mode: Mode, key: str | None
    ) -> BinderPlan:
        raise NotImplementedError("tiled binder is not implemented yet")

    def acquire(self, acquisition: Acquisition, ctx: BindContext, *, timeout: float | None) -> Path:
        raise NotImplementedError("tiled binder is not implemented yet")
