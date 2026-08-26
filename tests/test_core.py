"""Core unit tests against the installed API."""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

import pytest

from urisolver import (
    Context,
    FileDestination,
    Kind,
    MemoryDestination,
    ReferencePolicy,
    UnknownSchemeError,
    close_default_context,
    resolve,
)
from urisolver.errors import ContextClosedError, MemoryLimitError, PluginConflictError
from urisolver.plugins import ensure_builtin_file_resolver
from urisolver.redaction import redact_message, redact_uri, register_opaque_scheme
from urisolver.registry import Registry
from urisolver.resolvers.file import FileResolver


@pytest.fixture(autouse=True)
def _builtins():
    ensure_builtin_file_resolver()
    yield
    close_default_context()


def test_scheme_preserves_uri(tmp_path: Path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    uri = f.resolve().as_uri()
    with Context() as ctx:
        r = ctx.resolve(uri)
        assert r.uri == uri
        assert r.protocol == "file"
        assert r.info().kind is Kind.FILE


def test_opaque_uri_redaction():
    register_opaque_scheme("private")
    uri = "private:v1:AF31DD91SECRET"
    rendered = redact_uri(uri, opaque=True)
    assert "AF31DD91" not in rendered
    assert "sha256:" in rendered
    assert "SECRET" not in redact_message(f"failed for {uri}", opaque_uris=[uri])


def test_unknown_scheme():
    with Context() as ctx:
        with pytest.raises(UnknownSchemeError):
            ctx.resolve("nosuchscheme://x")


def test_file_memory_and_file_dest(tmp_path: Path):
    src = tmp_path / "data.dat"
    src.write_bytes(b"abc123")
    with Context() as ctx:
        r = ctx.resolve(src.resolve().as_uri())
        mem = r.materialize(MemoryDestination())
        assert mem.value == b"abc123"
        assert mem.strategy == "native"
        out = tmp_path / "out.dat"
        fr = r.materialize(FileDestination(out))
        assert Path(fr.value).read_bytes() == b"abc123"
        with pytest.raises(FileExistsError):
            r.materialize(FileDestination(out, overwrite=False))


def test_file_reference_in_place(tmp_path: Path):
    src = tmp_path / "keep.dat"
    src.write_bytes(b"x")
    with Context() as ctx:
        r = ctx.resolve(src.resolve().as_uri())
        result = r.materialize(
            FileDestination(tmp_path / "ignored", reference=ReferencePolicy.IN_PLACE)
        )
        assert result.is_reference is True
        assert Path(result.value) == src.resolve()
        assert src.exists()


def test_file_symlink_reference(tmp_path: Path):
    src = tmp_path / "src.dat"
    src.write_bytes(b"z")
    link = tmp_path / "link.dat"
    with Context() as ctx:
        r = ctx.resolve(src.resolve().as_uri())
        result = r.materialize(FileDestination(link, reference=ReferencePolicy.SYMLINK))
        assert result.is_reference is True
        assert link.is_symlink()
        assert link.read_bytes() == b"z"


def test_overwrite_false_before_transfer(tmp_path: Path):
    src = tmp_path / "s.dat"
    src.write_bytes(b"1")
    dest = tmp_path / "d.dat"
    dest.write_bytes(b"2")
    with Context() as ctx:
        r = ctx.resolve(src.resolve().as_uri())
        with pytest.raises(FileExistsError):
            r.materialize(FileDestination(dest, overwrite=False))
        assert dest.read_bytes() == b"2"


def test_memory_limit(tmp_path: Path):
    src = tmp_path / "big.dat"
    src.write_bytes(b"x" * 100)
    with Context(memory_limit=50) as ctx:
        r = ctx.resolve(src.resolve().as_uri())
        with pytest.raises(MemoryLimitError):
            r.materialize(MemoryDestination())


def test_container_directory(tmp_path: Path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    with Context() as ctx:
        r = ctx.resolve(tmp_path.resolve().as_uri())
        assert r.info().kind is Kind.CONTAINER
        assert "container" in r.facets()
        mem = r.materialize(MemoryDestination())
        assert set(mem.value) == {"a.txt", "b.txt"}


def test_stream_facet(tmp_path: Path):
    f = tmp_path / "s.bin"
    f.write_bytes(b"0123456789")
    with Context() as ctx:
        r = ctx.resolve(f.resolve().as_uri())
        assert "stream" in r.facets()
        with r.facet("stream").open() as fh:
            assert fh.read(4) == b"0123"


def test_capabilities_agree(tmp_path: Path):
    f = tmp_path / "c.bin"
    f.write_bytes(b"1")
    with Context() as ctx:
        r = ctx.resolve(f.resolve().as_uri())
        tier0 = {"info", "materialize", "facets", "facet", "supports", "capabilities"}
        for name in tier0:
            assert name in r.capabilities()
            assert r.supports(name)
            assert hasattr(r, name)
        for name in r.capabilities():
            assert r.supports(name)
            assert hasattr(r, name)
        assert r.supports("open")
        assert not r.supports("read_block")
        assert not hasattr(r, "read_block")


def test_context_close_invalidates(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"1")
    ctx = Context()
    r = ctx.resolve(f.resolve().as_uri())
    ctx.close()
    with pytest.raises(ContextClosedError):
        r.info()
    ctx.close()


def test_not_picklable(tmp_path: Path):
    f = tmp_path / "p.bin"
    f.write_bytes(b"1")
    with Context() as ctx:
        r = ctx.resolve(f.resolve().as_uri())
        with pytest.raises(TypeError, match="not picklable"):
            pickle.dumps(r)


def test_module_resolve_and_close_default(tmp_path: Path):
    f = tmp_path / "m.bin"
    f.write_bytes(b"ok")
    r = resolve(f.resolve().as_uri())
    assert r.materialize(MemoryDestination()).value == b"ok"
    close_default_context()
    close_default_context()


def test_materialized_result_repr_omits_value(tmp_path: Path):
    f = tmp_path / "r.bin"
    f.write_bytes(b"secret-bytes")
    with Context() as ctx:
        r = ctx.resolve(f.resolve().as_uri())
        result = r.materialize(MemoryDestination())
        text = repr(result)
        assert "secret-bytes" not in text
        assert "omitted" in text


def test_registry_conflict():
    reg = Registry()
    reg.register("filex", FileResolver(), source="a")
    with pytest.raises(PluginConflictError):
        reg.register("filex", FileResolver(), source="b")


def test_copy_failure_preserves_preexisting(tmp_path: Path, monkeypatch):
    src = tmp_path / "src.dat"
    src.write_bytes(b"source")
    dest = tmp_path / "dest.dat"
    dest.write_bytes(b"keep-me")

    def boom(*args, **kwargs):
        raise OSError("simulated copy failure")

    monkeypatch.setattr("urisolver.resolvers.file.shutil.copy2", boom)
    with Context() as ctx:
        r = ctx.resolve(src.resolve().as_uri())
        with pytest.raises(OSError, match="simulated"):
            r.materialize(FileDestination(dest, overwrite=True))
        assert dest.read_bytes() == b"keep-me"
        assert not list(tmp_path.glob(".urisolver-*.tmp"))


def test_memory_limit_before_read(tmp_path: Path, monkeypatch):
    src = tmp_path / "big.dat"
    src.write_bytes(b"x" * 100)

    def should_not_read(self):
        raise AssertionError("read_bytes should not be called when size exceeds limit")

    monkeypatch.setattr(Path, "read_bytes", should_not_read)
    with Context(memory_limit=50) as ctx:
        r = ctx.resolve(src.resolve().as_uri())
        with pytest.raises(MemoryLimitError):
            r.materialize(MemoryDestination())


def test_failure_no_partial_file_directory_dest(tmp_path: Path):
    src = tmp_path / "src.dat"
    src.write_bytes(b"payload")
    dest = tmp_path / "dest-dir"
    dest.mkdir()
    (dest / "keep").write_text("unchanged")
    with Context() as ctx:
        r = ctx.resolve(src.resolve().as_uri())
        with pytest.raises(OSError):
            r.materialize(FileDestination(dest, overwrite=True))
        assert not list(tmp_path.glob(".urisolver-*.tmp"))
        assert (dest / "keep").read_text() == "unchanged"


def test_canary_secret_not_in_logs(caplog: pytest.LogCaptureFixture):
    canary = "CANARY_SECRET_TOKEN_9f2c"
    msg = redact_message(f"Authorization: Bearer {canary}")
    assert canary not in msg
    with caplog.at_level(logging.INFO):
        logging.getLogger("urisolver.test").info(msg)
    assert canary not in caplog.text
