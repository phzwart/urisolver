"""Baseline suite against file: resolver."""

from __future__ import annotations

from pathlib import Path

from urisolver.context import ResolveContext
from urisolver.plugins import ensure_builtin_file_resolver
from urisolver.testing.baseline import run_baseline_suite


def test_file_baseline(tmp_path: Path):
    ensure_builtin_file_resolver()
    f = tmp_path / "baseline.bin"
    f.write_bytes(b"baseline-data")

    def make_uri() -> str:
        return f.resolve().as_uri()

    def ctx_factory() -> ResolveContext:
        ensure_builtin_file_resolver()
        return ResolveContext()

    run_baseline_suite(make_uri, context_factory=ctx_factory, expect_bytes=True)
