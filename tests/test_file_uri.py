"""file: URI mapping (RFC 8089, RFC 3986 §2.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from urisolver import Context, InvalidURIError
from urisolver.plugins import ensure_builtin_file_resolver
from urisolver.resolvers.file import FileResolver, _uri_to_path


@pytest.fixture(autouse=True)
def _builtins():
    ensure_builtin_file_resolver()
    yield


def test_double_encoding_not_traversed():
    path = _uri_to_path("file:///tmp/%252e%252e/x")
    assert "%2e%2e" in str(path) or "%252e%252e" in str(path)
    assert ".." not in path.parts


def test_encoded_slash_rejected_on_posix():
    with pytest.raises(InvalidURIError, match="separator"):
        _uri_to_path("file:///tmp/a%2Fb.txt")


def test_tilde_path_rejected():
    with pytest.raises(InvalidURIError, match="absolute"):
        _uri_to_path("file:~/x")


def test_localhost_case_insensitive(tmp_path: Path):
    f = tmp_path / "x.dat"
    f.write_bytes(b"1")
    assert _uri_to_path(f"file://LOCALHOST{tmp_path}/x.dat") == f
    assert _uri_to_path(f"file://localhost{tmp_path}/x.dat") == f


def test_non_local_host_rejected_on_posix():
    with pytest.raises(InvalidURIError, match="non-local"):
        _uri_to_path("file://server/share/x")


def test_query_rejected():
    with pytest.raises(InvalidURIError, match="query"):
        _uri_to_path("file:///tmp/x?a=b")


def test_fragment_excluded_from_path(tmp_path: Path):
    f = tmp_path / "x.dat"
    f.write_bytes(b"1")
    uri = f.resolve().as_uri() + "#frag"
    assert _uri_to_path(uri) == f
    with Context() as ctx:
        r = ctx.resolve(uri)
        assert r.uri == uri


def test_wrong_scheme_rejected():
    with pytest.raises(InvalidURIError):
        FileResolver().resolve("tiled://x", Context())
