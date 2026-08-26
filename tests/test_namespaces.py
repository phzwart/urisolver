"""Namespace resolution, cache, server, recursion."""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path

import pytest

from urisolver import (
    Context,
    InvalidURIError,
    MemoryDestination,
    NamespaceConfig,
    NamespaceNotFoundError,
    NamespaceRestrictedError,
    NamespaceUnavailableError,
    ResolutionLoopError,
)
from urisolver.namespaces.base import (
    NamespaceRequestContext,
    NamespaceResolution,
    Principal,
    ResolutionStatus,
)
from urisolver.namespaces.client import NamespaceClient
from urisolver.namespaces.server import NullAuthenticator, ServerConfig, serve
from urisolver.plugins import ensure_builtin_file_resolver
from urisolver.resolvers.file import FileResolver


class MapRouter:
    def __init__(self, mapping: dict[str, NamespaceResolution]) -> None:
        self.mapping = mapping
        self.calls: list[tuple[str, str | None]] = []

    def resolve_namespace(
        self, identifier: str, context: NamespaceRequestContext
    ) -> NamespaceResolution:
        principal_id = context.principal.id if context.principal else None
        self.calls.append((identifier, principal_id))
        assert not hasattr(context, "token")
        assert not hasattr(context, "password")
        if identifier not in self.mapping:
            return NamespaceResolution(status=ResolutionStatus.NOT_FOUND)
        return self.mapping[identifier]


def test_namespace_available(tmp_path: Path):
    ensure_builtin_file_resolver()
    data = tmp_path / "n.dat"
    data.write_bytes(b"ns")
    target = data.resolve().as_uri()
    router = MapRouter(
        {"abc": NamespaceResolution(status=ResolutionStatus.AVAILABLE, uri=target)}
    )
    with Context(
        namespaces=NamespaceConfig(resolvers={"lbl-mbib": router}),
        principal=Principal(id="alice"),
    ) as ctx:
        r = ctx.resolve("lbl-mbib:abc")
        assert r.uri == "lbl-mbib:abc"
        assert r.resolved_uri == target
        assert r.materialize(MemoryDestination()).value == b"ns"


def test_namespace_statuses():
    router = MapRouter(
        {
            "gone": NamespaceResolution(status=ResolutionStatus.NOT_FOUND),
            "nope": NamespaceResolution(status=ResolutionStatus.RESTRICTED),
            "tape": NamespaceResolution(
                status=ResolutionStatus.UNAVAILABLE, retry_after=timedelta(hours=1)
            ),
        }
    )
    with Context(namespaces=NamespaceConfig(resolvers={"ns": router})) as ctx:
        with pytest.raises(NamespaceNotFoundError):
            ctx.resolve("ns:gone")
        with pytest.raises(NamespaceRestrictedError):
            ctx.resolve("ns:nope")
        with pytest.raises(NamespaceUnavailableError):
            ctx.resolve("ns:tape")


def test_namespace_cache_keyed_by_principal(tmp_path: Path):
    ensure_builtin_file_resolver()
    data = tmp_path / "c.dat"
    data.write_bytes(b"c")
    target = data.resolve().as_uri()
    router = MapRouter(
        {"x": NamespaceResolution(status=ResolutionStatus.AVAILABLE, uri=target)}
    )
    cfg = NamespaceConfig(resolvers={"ns": router})
    with Context(namespaces=cfg, principal=Principal(id="a"), namespace_cache=True) as ctx:
        ctx.resolve("ns:x")
        ctx.resolve("ns:x")
    assert len(router.calls) == 1
    assert router.calls[0][1] == "a"

    with Context(namespaces=cfg, principal=Principal(id="b"), namespace_cache=True) as ctx:
        ctx.resolve("ns:x")
    assert router.calls[-1][1] == "b"


def test_resolution_loop():
    router = MapRouter(
        {"a": NamespaceResolution(status=ResolutionStatus.AVAILABLE, uri="ns:b")},
    )
    router.mapping["b"] = NamespaceResolution(
        status=ResolutionStatus.AVAILABLE, uri="ns:a"
    )
    with Context(namespaces=NamespaceConfig(resolvers={"ns": router})) as ctx:
        with pytest.raises(ResolutionLoopError):
            ctx.resolve("ns:a")


def test_namespace_fragment_not_in_identifier(tmp_path: Path):
    ensure_builtin_file_resolver()
    data = tmp_path / "frag.dat"
    data.write_bytes(b"frag")
    target = data.resolve().as_uri()
    router = MapRouter(
        {"abc123": NamespaceResolution(status=ResolutionStatus.AVAILABLE, uri=target)}
    )
    with Context(namespaces=NamespaceConfig(resolvers={"ns": router})) as ctx:
        r = ctx.resolve("ns:abc123#/entry/data")
        assert router.calls[-1][0] == "abc123"
        assert r.uri == "ns:abc123#/entry/data"


def test_namespace_fragment_inherited(tmp_path: Path):
    ensure_builtin_file_resolver()
    data = tmp_path / "frag.dat"
    data.write_bytes(b"frag")
    target = data.resolve().as_uri()
    seen_file_uris: list[str] = []

    class RecordingFileResolver(FileResolver):
        def resolve(self, uri: str, context: object):
            seen_file_uris.append(uri)
            return super().resolve(uri, context)

    from urisolver.registry import get_global_registry

    get_global_registry().override("file", RecordingFileResolver())
    router = MapRouter(
        {"abc": NamespaceResolution(status=ResolutionStatus.AVAILABLE, uri=target)}
    )
    with Context(namespaces=NamespaceConfig(resolvers={"ns": router})) as ctx:
        r = ctx.resolve("ns:abc#frag")
        assert seen_file_uris[-1] == f"{target}#frag"
        assert r.uri == "ns:abc#frag"


def test_namespace_fragment_target_wins(tmp_path: Path):
    ensure_builtin_file_resolver()
    data = tmp_path / "frag.dat"
    data.write_bytes(b"frag")
    target = data.resolve().as_uri()
    seen_file_uris: list[str] = []

    class RecordingFileResolver(FileResolver):
        def resolve(self, uri: str, context: object):
            seen_file_uris.append(uri)
            return super().resolve(uri, context)

    from urisolver.registry import get_global_registry

    get_global_registry().override("file", RecordingFileResolver())
    router = MapRouter(
        {"abc": NamespaceResolution(status=ResolutionStatus.AVAILABLE, uri=f"{target}#own")}
    )
    with Context(namespaces=NamespaceConfig(resolvers={"ns": router})) as ctx:
        r = ctx.resolve("ns:abc#frag")
        assert seen_file_uris[-1] == f"{target}#own"
        assert r.uri == "ns:abc#frag"


def test_resolution_loop_case_insensitive_scheme():
    router = MapRouter(
        {"abc": NamespaceResolution(status=ResolutionStatus.AVAILABLE, uri="NS:abc")},
    )
    with Context(namespaces=NamespaceConfig(resolvers={"ns": router})) as ctx:
        with pytest.raises(ResolutionLoopError, match="loop"):
            ctx.resolve("ns:abc")
    assert len(router.calls) <= 2


def test_namespace_rejects_double_slash():
    router = MapRouter({})
    with Context(namespaces=NamespaceConfig(resolvers={"ns": router})) as ctx:
        with pytest.raises(InvalidURIError, match="RFC 7595"):
            ctx.resolve("ns://abc")


def test_namespace_single_slash_identifier(tmp_path: Path):
    ensure_builtin_file_resolver()
    data = tmp_path / "slash.dat"
    data.write_bytes(b"s")
    target = data.resolve().as_uri()
    router = MapRouter(
        {"/abc": NamespaceResolution(status=ResolutionStatus.AVAILABLE, uri=target)}
    )
    with Context(namespaces=NamespaceConfig(resolvers={"ns": router})) as ctx:
        r = ctx.resolve("ns:/abc")
        assert router.calls[-1][0] == "/abc"
        assert r.materialize(MemoryDestination()).value == b"s"


def test_namespace_client_requires_https():
    with pytest.raises(ValueError, match="https"):
        NamespaceClient("http://example.com")
    NamespaceClient("https://example.com")
    NamespaceClient("http://127.0.0.1:8765", allow_insecure_transport=True)
    with pytest.raises(ValueError, match="http\\(s\\)"):
        NamespaceClient("ftp://example.com")


def test_namespace_server_and_client(tmp_path: Path):
    ensure_builtin_file_resolver()
    data = tmp_path / "s.dat"
    data.write_bytes(b"srv")
    target = data.resolve().as_uri()
    router = MapRouter(
        {
            "id1": NamespaceResolution(status=ResolutionStatus.AVAILABLE, uri=target),
            "missing": NamespaceResolution(status=ResolutionStatus.NOT_FOUND),
        }
    )
    config = ServerConfig(
        namespace="lbl-mbib",
        resolver=router,
        authenticator=NullAuthenticator(),
        host="127.0.0.1",
        port=0,
        include_detail=False,
    )
    server = serve(config, blocking=False)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = NamespaceClient(f"http://{host}:{port}", allow_insecure_transport=True)
        req = NamespaceRequestContext(
            principal=Principal(id="client"), secrets=None, request_id="1"
        )
        ok = client.resolve_namespace("id1", req)
        assert ok.status is ResolutionStatus.AVAILABLE
        assert ok.uri == target
        assert ok.detail is None
        missing = client.resolve_namespace("missing", req)
        assert missing.status is ResolutionStatus.NOT_FOUND
    finally:
        server.shutdown()
