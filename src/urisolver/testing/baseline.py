"""Baseline conformance suite (§31) — matches installed API."""

from __future__ import annotations

import pickle
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

from urisolver.context import ResolveContext
from urisolver.destinations import FileDestination, Form, MemoryDestination
from urisolver.errors import ContextClosedError, UnsupportedFormError
from urisolver.info import Kind
from urisolver.plugins import ensure_builtin_file_resolver


def run_baseline_suite(
    make_uri: Callable[[], str],
    *,
    context_factory: Callable[[], ResolveContext] | None = None,
    expect_array_selection: bool = False,
    expect_bytes: bool = True,
) -> None:
    ensure_builtin_file_resolver()

    def _ctx() -> ResolveContext:
        return context_factory() if context_factory is not None else ResolveContext()

    uri = make_uri()
    with _ctx() as ctx:
        resource = ctx.resolve(uri)
        info = resource.info()
        assert info.uri == uri or info.uri == resource.uri
        assert info.protocol
        assert isinstance(info.kind, Kind)
        assert isinstance(info.exists, bool)

        for name in ("info", "materialize", "facets", "facet", "supports", "capabilities"):
            assert resource.supports(name), name
            assert hasattr(resource, name)

        mem = resource.materialize(MemoryDestination())
        assert mem.value is not None
        assert mem.strategy
        assert mem.source_uri
        assert mem.resolved_uri

        if info.kind is not Kind.CONTAINER and expect_bytes:
            if info.canonical_media_type is not None:
                raw = resource.materialize(MemoryDestination(form=Form.BYTES))
                assert isinstance(raw.value, (bytes, bytearray, memoryview))
                assert raw.media_type == info.canonical_media_type
                with tempfile.TemporaryDirectory() as td:
                    dest = Path(td) / "out.bin"
                    file_result = resource.materialize(FileDestination(dest))
                    assert Path(file_result.value).exists()
                    assert file_result.form is Form.PATH
                    with pytest.raises(FileExistsError):
                        resource.materialize(FileDestination(dest, overwrite=False))
                    resource.materialize(FileDestination(dest, overwrite=True))
                    assert dest.exists()
                with pytest.raises(UnsupportedFormError):
                    resource.materialize(
                        MemoryDestination(form=Form.BYTES, media_type="application/x-nope")
                    )
            else:
                with pytest.raises(UnsupportedFormError):
                    resource.materialize(MemoryDestination(form=Form.BYTES))

        if expect_array_selection and info.kind is Kind.ARRAY:
            selection: object = (
                (slice(0, 1), Ellipsis) if (info.shape and len(info.shape) >= 1) else slice(0, 1)
            )
            block = resource.materialize(MemoryDestination(), selection=selection)
            assert block.strategy in {
                "native",
                "native-selection",
                "read-then-select",
                "converted",
            }

        with pytest.raises(TypeError, match="not picklable|not pickle"):
            pickle.dumps(resource)

    with pytest.raises(ContextClosedError):
        resource.info()
