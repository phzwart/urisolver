"""Tiled resolver tests with a mock node (no tiled SDK required)."""

from __future__ import annotations

from typing import Any

import pytest

from urisolver import (
    AuthenticationError,
    AuthorizationError,
    Context,
    FileDestination,
    Form,
    InefficientOperationError,
    InvalidURIError,
    Kind,
    MaterializationError,
    MemoryDestination,
    NativeAccessDenied,
    ResolutionError,
    UnsupportedFormError,
)
from urisolver.plugins import ensure_builtin_file_resolver
from urisolver.registry import register_resolver
from urisolver.resolvers.tiled import TiledResolver, _wrapper_for
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
        protocol_name="com.urisolver.test.tiled",
        client=Root(),
        allow_native=True,
    )
    from urisolver.registry import get_global_registry

    get_global_registry().override("com.urisolver.test.tiled", resolver)
    return resolver


def test_tiled_array_tier0(tiled_array_setup):
    with Context() as ctx:
        r = ctx.resolve("com.urisolver.test.tiled://catalog/run/12345")
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
        r = ctx.resolve("com.urisolver.test.tiled://catalog/run/12345")
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
        return "com.urisolver.test.tiled://catalog/run/12345"

    run_baseline_suite(
        make_uri,
        context_factory=lambda **kw: Context(**kw),
        expect_array_selection=True,
        expect_bytes=True,
    )


def _resolve(node: Any, uri: str) -> Any:
    return TiledResolver(client=node, protocol_name="ex").resolve(uri, Context())


class _StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        self.response = type("Response", (), {"status_code": status_code})()


def test_http_status_mapping():
    assert _wrapper_for(_StatusError(401)) is AuthenticationError
    assert _wrapper_for(_StatusError(403)) is AuthorizationError
    assert _wrapper_for(_StatusError(404)) is ResolutionError
    assert _wrapper_for(_StatusError(400)) is MaterializationError
    assert _wrapper_for(_StatusError(422)) is MaterializationError


def test_array_chunks_tolerate_none():
    class Node:
        structure_family = "array"
        shape = (4,)
        dtype = "float64"
        chunks = ((4,), None, None)

        def structure(self) -> Any:
            return self

        def read(self) -> list[float]:
            return [1.0]

    resource = _resolve(Node(), "ex:")
    assert resource.info().kind is Kind.ARRAY
    assert resource._facet_objects["array"].chunks == ((4,), None, None)


def test_special_nodes_are_opaque_and_container_children_are_lazy(tmp_path):
    built = {"n": 0}

    class Ragged:
        structure_family = "ragged"

        def __init__(self) -> None:
            built["n"] += 1

        def read(self) -> list[int]:
            return [1]

    class Box:
        structure_family = "container"

        def keys(self):
            return ["ragged_array", "awkward_array", "sparse_image"]

        def __getitem__(self, key: str) -> Any:
            families = {
                "ragged_array": "ragged",
                "awkward_array": "awkward",
                "sparse_image": "sparse",
            }
            node = Ragged()
            node.structure_family = families[key]
            return node

        def __len__(self) -> int:
            return 3

    resource = _resolve(Box(), "ex:")
    children = resource.materialize(MemoryDestination()).value
    assert built["n"] == 0
    for name in ("ragged_array", "awkward_array", "sparse_image"):
        child = children[name]
        assert child.info().kind is Kind.OPAQUE
        assert child.info().canonical_media_type is None
    assert built["n"] == 3
    with pytest.raises(UnsupportedFormError):
        children["ragged_array"].materialize(FileDestination(tmp_path / "nope"))


def test_typeerror_from_materialize_is_wrapped():
    class Node:
        structure_family = "array"
        shape = (1,)
        dtype = "float64"

        def structure(self) -> Any:
            return self

        def read(self) -> Any:
            raise TypeError("boom")

    resource = _resolve(Node(), "ex:")
    with pytest.raises(MaterializationError):
        resource.materialize(MemoryDestination())


def test_table_file_is_arrow_ipc(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pd = pytest.importorskip("pandas")

    frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})

    class Node:
        structure_family = "table"
        columns = ("a", "b")

        def read(self) -> pd.DataFrame:
            return frame

    dest = tmp_path / "short_table.arrow"
    resource = _resolve(Node(), "ex:")
    result = resource.materialize(FileDestination(dest))
    assert result.media_type == "application/vnd.apache.arrow.file"
    table = pa.ipc.open_file(dest).read_all()
    assert table.column("a").to_pylist() == [1, 2]
    assert table.column("b").to_pylist() == ["x", "y"]


def test_path_percent_decodes_and_rejects_empty_segments():
    seen: list[str] = []

    class Leaf:
        structure_family = "array"
        shape = (1,)
        dtype = "float64"

        def structure(self) -> Any:
            return self

        def read(self) -> list[int]:
            return [1]

    class Root:
        def __getitem__(self, key: str) -> Any:
            seen.append(key)
            if key == "/":
                return Leaf()
            return self

    resource = _resolve(Root(), "ex://foo/%2F")
    assert seen == ["foo", "/"]
    assert resource.info().kind is Kind.ARRAY
    with pytest.raises(InvalidURIError):
        _resolve(Root(), "ex://foo//bar")


def test_session_cache_key_includes_secret_id(monkeypatch):
    calls: list[str | None] = []

    class FakeClient:
        @staticmethod
        def from_uri(uri: str, **kwargs: Any) -> object:
            calls.append(kwargs.get("api_key"))
            return object()

    monkeypatch.setattr("urisolver.resolvers.tiled._require_tiled", lambda: FakeClient)

    class Secrets:
        def __init__(self, api_key: str) -> None:
            self._api_key = api_key

        def get_secret(self, secret_id: str) -> dict[str, str]:
            return {"api_key": self._api_key}

    alpha = TiledResolver(base_uri="http://tiled.example", secret_id="alpha")
    beta = TiledResolver(base_uri="http://tiled.example", secret_id="beta")
    alpha_ctx = Context(secrets=Secrets("aaa"))
    beta_ctx = Context(secrets=Secrets("bbb"))
    alpha._get_client(alpha_ctx)
    alpha._get_client(alpha_ctx)
    beta._get_client(beta_ctx)
    assert calls == ["aaa", "bbb"]
    assert ("http://tiled.example", "alpha") in alpha._sessions
    assert ("http://tiled.example", "beta") in beta._sessions


def test_native_modes_refuse_staged_file_when_strict(tmp_path):
    pytest.importorskip("numpy")

    class Node:
        structure_family = "array"
        shape = (2,)
        dtype = "float64"

        def structure(self) -> Any:
            return self

        def read(self) -> list[float]:
            return [1.0, 2.0]

    resolver = TiledResolver(client=Node(), protocol_name="ex", native_modes=frozenset({"memory"}))
    with Context(strict_efficiency=True) as ctx:
        resource = resolver.resolve("ex:", ctx)
        assert resource.materialize(MemoryDestination()).strategy == "native"
        with pytest.raises(InefficientOperationError, match="file delivery is not native"):
            resource.materialize(FileDestination(tmp_path / "staged.npy"))
    with Context() as ctx:
        resource = resolver.resolve("ex:", ctx)
        staged = resource.materialize(FileDestination(tmp_path / "ok.npy"))
        assert staged.strategy == "converted"
