"""Tiled resolver tests with a mock node (no tiled SDK required)."""

from __future__ import annotations

from typing import Any

import pytest

from urisolver import (
    Context,
    Form,
    InefficientOperationError,
    Kind,
    MemoryDestination,
    NativeAccessDenied,
)
from urisolver.plugins import ensure_builtin_file_resolver
from urisolver.registry import register_resolver
from urisolver.resolvers.tiled import TiledResolver
from urisolver.testing.baseline import run_baseline_suite


class MockArrayNode:
    structure_family = "array"

    def __init__(self, data: list[list[float]]) -> None:
        self._data = data
        self.shape = (len(data), len(data[0]) if data else 0)
        self.dtype = "float64"

    def structure(self) -> Any:
        return self

    @property
    def chunks(self) -> None:
        return None

    def read(self) -> list[list[float]]:
        return self._data

    def read_block(self, block: tuple[int, ...]) -> list[list[float]]:
        return self._data

    def __getitem__(self, selection: Any) -> Any:
        if selection == slice(0, 1) or selection == (slice(0, 1),):
            return self._data[:1]
        if selection is Ellipsis or selection == (Ellipsis,):
            return self._data
        if isinstance(selection, tuple) and selection and isinstance(selection[0], slice):
            return self._data[selection[0]]
        return self._data[selection]


class _DictNode:
    structure_family = "container"

    def __init__(self, d: dict) -> None:
        self._d = d

    def keys(self):
        return self._d.keys()

    def __getitem__(self, key: str) -> Any:
        return self._d[key]

    def __len__(self) -> int:
        return len(self._d)


@pytest.fixture
def tiled_array_setup():
    ensure_builtin_file_resolver()
    node = MockArrayNode([[1.0, 2.0], [3.0, 4.0]])

    class Root:
        def __getitem__(self, key: str) -> Any:
            if key == "catalog":
                return _DictNode({"run": _DictNode({"12345": node})})
            raise KeyError(key)

    resolver = TiledResolver(
        protocol_name="tiled-local",
        client=Root(),
        allow_native=True,
    )
    from urisolver.registry import get_global_registry

    get_global_registry().override("tiled-local", resolver)
    return resolver


def test_tiled_array_tier0(tiled_array_setup):
    with Context() as ctx:
        r = ctx.resolve("tiled-local://catalog/run/12345")
        info = r.info()
        assert info.kind is Kind.ARRAY
        assert info.shape == (2, 2)
        assert "array" in r.facets()
        mem = r.materialize(MemoryDestination())
        assert mem.value == [[1.0, 2.0], [3.0, 4.0]]
        assert r.supports("read_block")
        assert r.read_block((0, 0)) == [[1.0, 2.0], [3.0, 4.0]]
        block = r.materialize(MemoryDestination(), selection=slice(0, 1))
        assert block.strategy in {"native-selection", "read-then-select", "native"}
        assert block.value == [[1.0, 2.0]]


def test_tiled_policy_denies_native():
    ensure_builtin_file_resolver()
    node = MockArrayNode([[1.0]])

    class Root:
        def __getitem__(self, key: str) -> Any:
            return node

    resolver = TiledResolver(
        protocol_name="tiled-policy",
        client=Root(),
        allow_native=False,
    )
    register_resolver("tiled-policy", resolver, source="test")
    with Context() as ctx:
        r = ctx.resolve("tiled-policy://x")
        with pytest.raises(NativeAccessDenied):
            _ = r.native
        assert r.supports("materialize")
        assert r.materialize(MemoryDestination()).value == [[1.0]]


def test_tiled_bytes_requires_numpy_or_raises(tiled_array_setup):
    with Context() as ctx:
        r = ctx.resolve("tiled-local://catalog/run/12345")
        try:
            import numpy  # noqa: F401

            result = r.materialize(MemoryDestination(form=Form.BYTES))
            assert isinstance(result.value, (bytes, bytearray))
            assert result.media_type == "application/x-npy"
            with pytest.raises(Exception):
                r.materialize(
                    MemoryDestination(form=Form.BYTES, media_type="application/x-nope")
                )
        except ImportError:
            from urisolver.errors import UnsupportedFormError

            with pytest.raises(UnsupportedFormError):
                r.materialize(MemoryDestination(form=Form.BYTES))


def test_tiled_strict_efficiency():
    ensure_builtin_file_resolver()

    class NoGetItem:
        structure_family = "array"
        shape = (2,)
        dtype = "float64"

        def structure(self):
            return self

        def read(self):
            return [1.0, 2.0]

    class Root:
        def __getitem__(self, key: str) -> Any:
            return NoGetItem()

    register_resolver(
        "tiled-strict",
        TiledResolver(protocol_name="tiled-strict", client=Root()),
        source="test",
    )
    with Context(strict_efficiency=True) as ctx:
        r = ctx.resolve("tiled-strict://x")
        with pytest.raises(InefficientOperationError):
            r.materialize(MemoryDestination(), selection=slice(0, 1))


def test_tiled_baseline(tiled_array_setup):
    pytest.importorskip("numpy")

    def make_uri() -> str:
        return "tiled-local://catalog/run/12345"

    run_baseline_suite(
        make_uri,
        context_factory=lambda **kw: Context(**kw),
        expect_array_selection=True,
        expect_bytes=True,
    )
