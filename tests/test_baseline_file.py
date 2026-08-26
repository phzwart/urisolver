"""Baseline suite against file: resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from urisolver.context import ResolveContext
from urisolver.plugins import ensure_builtin_file_resolver
from urisolver.testing.baseline import run_baseline_suite
from urisolver import Context


def test_file_baseline(tmp_path: Path):
    ensure_builtin_file_resolver()
    f = tmp_path / "baseline.bin"
    f.write_bytes(b"baseline-data")

    def make_uri() -> str:
        return f.resolve().as_uri()

    def ctx_factory(**kwargs) -> ResolveContext:
        ensure_builtin_file_resolver()
        return ResolveContext(**kwargs)

    run_baseline_suite(make_uri, context_factory=ctx_factory, expect_bytes=True)


def test_container_key_guard(tmp_path: Path):
    ensure_builtin_file_resolver()
    (tmp_path / "child.txt").write_text("c")
    with Context() as ctx:
        r = ctx.resolve(tmp_path.resolve().as_uri())
        container = r.facet("container")
        for bad in ("../x", "/etc/passwd", "..", ""):
            with pytest.raises(KeyError):
                container[bad]


def test_container_encoded_name_roundtrip(tmp_path: Path):
    ensure_builtin_file_resolver()
    name = "a b#c"
    (tmp_path / name).write_bytes(b"x")
    with Context() as ctx:
        r = ctx.resolve(tmp_path.resolve().as_uri())
        child = r.facet("container")[name]
        from urisolver.resolvers.file import _uri_to_path

        assert _uri_to_path(child.uri).name == name
