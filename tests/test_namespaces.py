"""Namespace resolution, cache, server, recursion."""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path

import pytest

from urisolver import (
    Context,
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
        client = NamespaceClient(f"http://{host}:{port}")
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
