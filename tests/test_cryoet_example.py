"""The example CryoET scheme: metadata without chunks, delivery against fakes."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from urisolver import Context, FileDestination, MemoryDestination, Registry
from urisolver.errors import (
    InefficientOperationError,
    InvalidURIError,
    MaterializationError,
    MemoryLimitError,
    ResolutionError,
    SelectionNotSupportedError,
)
from urisolver.info import Kind
from urisolver.resolvers import example_cryoet as cryo
from urisolver.selection import Native

ROOT = Path(__file__).resolve().parents[1]
RESOLVE = ROOT / "examples" / "cryoet" / "resolve.py"
CATALOG = ROOT / "examples" / "catalog.yaml"
ZARR = (
    "com.urisolver.example.cryoet:///10000/TS_026/Reconstructions/"
    "VoxelSpacing13.480/Tomograms/100/TS_026.zarr"
)
MRC = ZARR[: -len(".zarr")] + ".mrc"
BASE = "https://files.example"


def _zarray(shape, chunks=(2, 2), separator="/"):
    return {
        "shape": list(shape),
        "chunks": list(chunks),
        "dtype": "<f4",
        "dimension_separator": separator,
        "zarr_format": 2,
    }


def _zattrs(paths=("0", "1")):
    return {"multiscales": [{"datasets": [{"path": path} for path in paths], "version": "0.4"}]}


def _resolver(**kwargs):
    options = {"base_uri": BASE, "protocol_name": cryo.SCHEME}
    options.update(kwargs)
    return cryo.CryoetResolver(**options)


def _context(resolver, *, memory_limit: int | None = None):
    registry = Registry()
    registry.register(cryo.SCHEME, resolver, source="test")
    return Context(registry=registry, memory_limit=memory_limit)


def test_import_urisolver_does_not_load_zarr():
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys\n"
            "import urisolver\n"
            "bad = [name for name in sys.modules if name == 'zarr' or name.startswith('zarr.') "
            "or name.startswith('urisolver.resolvers')]\n"
            "raise SystemExit(0 if not bad else ','.join(bad))\n",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout or proc.stderr


def test_resolve_script_imports_urisolver_only():
    text = RESOLVE.read_text(encoding="utf-8")
    assert "import zarr" not in text
    assert "files.cryoetdataportal" not in text
    assert "ExampleCryoetResolver" in text
    assert "Context()" in text
    assert "levels[2]" in text


@pytest.mark.parametrize(
    "uri",
    [
        ZARR,
        "com.urisolver.example.cryoet:/10000/TS_026.zarr",
        ZARR + "#ignored",
        "com.urisolver.example.cryoet:///a/b.mrc",
    ],
)
def test_object_path_accepts(uri):
    rel = cryo.object_path(uri)
    assert rel.endswith(".zarr") or rel.endswith(".mrc")
    assert "//" not in rel


@pytest.mark.parametrize(
    "uri",
    [
        "com.urisolver.example.cryoet:///a/b.txt",
        "com.urisolver.example.cryoet:///a//b.zarr",
        "com.urisolver.example.cryoet:///a/../b.zarr",
        "com.urisolver.example.cryoet:///a/b.zarr?recursive",
        "com.urisolver.example.cryoet:",
    ],
)
def test_object_path_rejects(uri):
    with pytest.raises(InvalidURIError):
        cryo.object_path(uri)


def test_parse_levels_and_chunk_names():
    arrays = {"0": _zarray((4, 4)), "1": _zarray((2, 2), chunks=(2, 2))}
    levels = cryo.parse_levels(_zattrs(), arrays)
    assert levels[0].shape == (4, 4)
    assert levels[1].nbytes == 2 * 2 * 4
    assert cryo.chunk_names(levels[0]) == ("0/0", "0/1", "1/0", "1/1")
    with pytest.raises(ResolutionError, match="no multiscales"):
        cryo.parse_levels({}, arrays)


def test_redirect_off_host_is_refused():
    with pytest.raises(ResolutionError, match="refusing redirect"):
        cryo._check_redirect("files.example", "https://evil.example/a", ResolutionError)
    cryo._check_redirect("files.example", "https://files.example/a", ResolutionError)


def test_zarr_info_reads_metadata_only(monkeypatch):
    seen = []

    def fake_fetch(url, host):
        seen.append(url)
        if url.endswith(".zattrs"):
            return json.dumps(_zattrs()).encode()
        if url.endswith(".zgroup"):
            return b'{"zarr_format": 2}'
        if url.endswith("/0/.zarray"):
            return json.dumps(_zarray((8, 8), chunks=(4, 4))).encode()
        if url.endswith("/1/.zarray"):
            return json.dumps(_zarray((4, 4), chunks=(4, 4))).encode()
        raise AssertionError(url)

    monkeypatch.setattr(cryo, "fetch", fake_fetch)
    monkeypatch.setattr(cryo, "read_level", lambda *args: (_ for _ in ()).throw(AssertionError("chunk")))
    with _context(_resolver()) as ctx:
        resource = ctx.resolve("com.urisolver.example.cryoet:///set/a.zarr")
        info = resource.info()
        level = resource.facet("array").levels[1]
    assert info.kind is Kind.ARRAY
    assert info.shape == (8, 8)
    assert info.dtype == "<f4"
    assert info.size_bytes == 8 * 8 * 4
    assert info.resolved_uri == BASE + "/set/a.zarr"
    assert level.shape == (4, 4)
    assert level.nbytes == 64
    assert all("/0/0" not in url for url in seen)


def test_scale_selection_is_pushed(monkeypatch):
    calls = []

    def fake_fetch(url, host):
        if url.endswith(".zattrs"):
            return json.dumps(_zattrs(("0",))).encode()
        if url.endswith(".zgroup"):
            return b'{"zarr_format": 2}'
        if url.endswith(".zarray"):
            return json.dumps(_zarray((100, 100), chunks=(10, 10))).encode()
        raise AssertionError(url)

    def fake_read(url, level, selection):
        calls.append((level, selection))
        return b"array"

    monkeypatch.setattr(cryo, "fetch", fake_fetch)
    monkeypatch.setattr(cryo, "read_level", fake_read)
    with _context(_resolver()) as ctx:
        resource = ctx.resolve("com.urisolver.example.cryoet:///a.zarr")
        whole = resource.materialize(MemoryDestination(), selection=Native(0))
        sliced = resource.materialize(
            MemoryDestination(), selection=Native((0, (slice(0, 2), slice(0, 2))))
        )
    assert whole.strategy == "native"
    assert sliced.strategy == "native-selection"
    assert calls == [("0", None), ("0", (slice(0, 2), slice(0, 2)))]


def test_full_scale_respects_memory_limit(monkeypatch):
    def fake_fetch(url, host):
        if url.endswith(".zattrs"):
            return json.dumps(_zattrs(("0",))).encode()
        if url.endswith(".zgroup"):
            return b'{"zarr_format": 2}'
        return json.dumps(_zarray((64, 64), chunks=(32, 32))).encode()

    monkeypatch.setattr(cryo, "fetch", fake_fetch)
    monkeypatch.setattr(cryo, "read_level", lambda *args: (_ for _ in ()).throw(AssertionError("chunk")))
    with _context(_resolver(), memory_limit=1024) as ctx:
        resource = ctx.resolve("com.urisolver.example.cryoet:///a.zarr")
        with pytest.raises(MemoryLimitError):
            resource.materialize(MemoryDestination())


def test_zarr_file_copy_fetches_chunks_and_cleans_up(monkeypatch, tmp_path: Path):
    bodies = {}

    def fake_fetch(url, host):
        if url in bodies:
            return bodies[url]
        if url.endswith(".zattrs"):
            return json.dumps(_zattrs(("0",))).encode()
        if url.endswith(".zgroup"):
            return b'{"zarr_format": 2}'
        if url.endswith(".zarray"):
            return json.dumps(_zarray((2, 2), chunks=(2, 2))).encode()
        if url.endswith("/0/0/0"):
            if bodies.get("fail"):
                raise ResolutionError("missing chunk")
            return b"chunk"
        raise AssertionError(url)

    monkeypatch.setattr(cryo, "fetch", fake_fetch)
    with _context(_resolver()) as ctx:
        resource = ctx.resolve("com.urisolver.example.cryoet:///a.zarr")
        bodies["fail"] = True
        dest = tmp_path / "out.zarr"
        with pytest.raises(MaterializationError, match="missing chunk"):
            resource.materialize(FileDestination(dest))
        assert list(tmp_path.iterdir()) == []
        bodies["fail"] = False
        result = resource.materialize(FileDestination(dest))
    assert result.strategy == "native"
    assert (dest / "0" / "0" / "0").read_bytes() == b"chunk"
    assert (dest / ".zattrs").is_file()


def test_mrc_head_and_copy(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cryo, "content_length", lambda url, host: 5)

    def fake_stream(url, host, write, expected):
        write(b"hello")
        return 5

    monkeypatch.setattr(cryo, "stream_to", fake_stream)
    with _context(_resolver()) as ctx:
        resource = ctx.resolve("com.urisolver.example.cryoet:///a.mrc")
        assert resource.info().kind is Kind.FILE
        assert resource.info().size_bytes == 5
        assert resource.info().label == "a.mrc"
        out = resource.materialize(FileDestination(tmp_path / "a.mrc"))
        assert out.value.read_bytes() == b"hello"
        assert out.strategy == "native"
        data = resource.materialize(MemoryDestination()).value
        assert data == b"hello"


def test_mrc_size_mismatch_leaves_nothing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cryo, "content_length", lambda url, host: 5)

    def fake_stream(url, host, write, expected):
        write(b"HELLO!")
        raise MaterializationError("download size 6 != Content-Length 5")

    monkeypatch.setattr(cryo, "stream_to", fake_stream)
    with _context(_resolver()) as ctx:
        resource = ctx.resolve("com.urisolver.example.cryoet:///a.mrc")
        with pytest.raises(MaterializationError):
            resource.materialize(FileDestination(tmp_path / "a.mrc"))
    assert list(tmp_path.iterdir()) == []


def test_strict_efficiency_refuses_file_when_memory_only(monkeypatch):
    monkeypatch.setattr(cryo, "content_length", lambda url, host: 1)
    with _context(_resolver(native_modes=frozenset({"memory"}))) as ctx:
        ctx.strict_efficiency = True
        resource = ctx.resolve("com.urisolver.example.cryoet:///a.mrc")
        with pytest.raises(InefficientOperationError):
            resource.materialize(FileDestination("a.mrc"))


def test_selection_on_mrc_is_rejected(monkeypatch):
    monkeypatch.setattr(cryo, "content_length", lambda url, host: 1)
    with _context(_resolver()) as ctx:
        resource = ctx.resolve("com.urisolver.example.cryoet:///a.mrc")
        with pytest.raises(SelectionNotSupportedError):
            resource.materialize(MemoryDestination(), selection=slice(0, 1))


def test_catalog_binds_the_portal(monkeypatch, tmp_path: Path):
    pytest.importorskip("yaml")
    monkeypatch.delenv("URISOLVER_CATALOG", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "empty-home"))
    resolver = cryo.ExampleCryoetResolver()
    assert resolver.base_uri == "https://files.cryoetdataportal.cziscience.com"
    assert resolver.native_modes == frozenset({"memory", "file"})
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text("com.urisolver.example.cryoet:\n  protocol: cryoet\n  base_uri: http://nope\n")
    monkeypatch.setenv("URISOLVER_CATALOG", str(catalog))
    with pytest.raises(ResolutionError, match="https base_uri"):
        cryo.ExampleCryoetResolver()
    assert CATALOG.is_file()


def test_read_level_round_trip(tmp_path: Path):
    zarr = pytest.importorskip("zarr")
    store = tmp_path / "tiny.zarr"
    array = zarr.open_array(str(store / "0"), mode="w", shape=(4, 4), chunks=(2, 2), dtype="<f4")
    array[:] = 1
    value = cryo.read_level(str(store), "0", (slice(0, 1), slice(0, 2)))
    assert tuple(value.shape) == (1, 2)


@pytest.mark.skipif(os.environ.get("URISOLVER_CRYOET") != "1", reason="set URISOLVER_CRYOET=1")
def test_live_portal_metadata():
    pytest.importorskip("yaml")
    registry = Registry()
    registry.register(cryo.SCHEME, cryo.ExampleCryoetResolver(), source="test")
    with Context(registry=registry) as ctx:
        zarr = ctx.resolve(ZARR)
        levels = zarr.facet("array").levels
        zarr_size = zarr.info().size_bytes
        mrc = ctx.resolve(MRC)
        mrc_size = mrc.info().size_bytes
        mrc_uri = mrc.info().resolved_uri
    assert [level.shape for level in levels] == [(1000, 928, 960), (500, 464, 480), (250, 232, 240)]
    assert levels[2].dtype == "<f4"
    assert levels[2].nbytes == 55_680_000
    assert zarr_size == 1000 * 928 * 960 * 4
    assert mrc_size == 1_781_761_024
    assert mrc_uri.endswith("/TS_026.mrc")
