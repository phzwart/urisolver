"""globus: binder. ACQUIRE is filled in by a later phase. The SDK is not imported here."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from urisolver.bind import Acquisition, BinderPlan, Mode
from urisolver.context import BindContext
from urisolver.site import Source


class GlobusBinder:
    api_version = 2
    protocol = "globus"
    opaque_payload = False

    def validate_source(self, source: Source) -> None:
        return None

    def feasible_modes(
        self, uri: str, source: Source | None, into: Any, ctx: BindContext
    ) -> list[tuple[Mode, str | None]]:
        raise NotImplementedError("globus binder is not implemented yet")

    def plan(
        self, uri: str, source: Source | None, into: Any, ctx: BindContext, *, mode: Mode, key: str | None
    ) -> BinderPlan:
        raise NotImplementedError("globus binder is not implemented yet")

    def acquire(self, acquisition: Acquisition, ctx: BindContext, *, timeout: float | None) -> Path:
        raise NotImplementedError("globus binder is not implemented yet")
