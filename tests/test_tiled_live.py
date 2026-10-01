"""Checks against a local ``tiled serve demo`` process."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("tiled.server")

from urisolver import Context, FileDestination, Kind, MemoryDestination  # noqa: E402
from urisolver.resolvers.example_tiled import ExampleCatalogResolver  # noqa: E402

PORT = int(os.environ.get("URISOLVER_TILED_DEMO_PORT", "8766"))
HOST = "127.0.0.1"
API_KEY = "secret"
SCHEME = "com.urisolver.example.tiled"
BASE = f"http://{HOST}:{PORT}?api_key={API_KEY}"


def _port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.2):
            return True
    except OSError:
        return False


def _drain(stream, lines: list[str]) -> None:
    for raw in stream:
        lines.append(raw.decode("utf-8", errors="replace").rstrip())
        if len(lines) > 40:
            del lines[:-40]


def _wait_ready(proc: subprocess.Popen[bytes], lines: list[str], timeout: float = 30) -> None:
    url = f"http://{HOST}:{PORT}/api/v1/"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            detail = "\n".join(lines[-20:])
            pytest.fail(f"tiled serve demo exited {proc.returncode}\n{detail}")
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status < 500:
                    return
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return
        except OSError:
            pass
        time.sleep(0.15)
    pytest.fail(f"tiled serve demo did not answer on {HOST}:{PORT}")


@pytest.fixture(scope="module")
def demo_catalog(tmp_path_factory):
    if _port_open():
        pytest.skip(f"{HOST}:{PORT} is already in use")
    env = os.environ.copy()
    env["TILED_SINGLE_USER_API_KEY"] = API_KEY
    proc = subprocess.Popen(
        [sys.executable, "-m", "tiled", "serve", "demo", "--host", HOST, "--port", str(PORT)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    lines: list[str] = []
    assert proc.stderr is not None
    threading.Thread(target=_drain, args=(proc.stderr, lines), daemon=True).start()
    catalog = tmp_path_factory.mktemp("catalog") / "catalog.yaml"
    catalog.write_text(
        f"{SCHEME}:\n  protocol: tiled\n  base_uri: {BASE}\n  native: [memory]\n",
        encoding="utf-8",
    )
    try:
        _wait_ready(proc, lines)
        yield catalog
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def _resolve(catalog: Path, path: str, monkeypatch):
    monkeypatch.setenv("URISOLVER_CATALOG", str(catalog))
    resolver = ExampleCatalogResolver()
    return resolver.resolve(f"{SCHEME}://{path}", Context())


def test_live_flat_array(demo_catalog, monkeypatch):
    resource = _resolve(demo_catalog, "flat_array", monkeypatch)
    assert resource.info().kind is Kind.ARRAY
    assert resource.info().shape == (100,)
    value = resource.materialize(MemoryDestination()).value
    assert tuple(value.shape) == (100,)


def test_live_short_table_arrow_roundtrip(demo_catalog, monkeypatch, tmp_path):
    pa = pytest.importorskip("pyarrow")
    resource = _resolve(demo_catalog, "tables/short_table", monkeypatch)
    dest = tmp_path / "short_table.arrow"
    result = resource.materialize(FileDestination(dest))
    assert result.media_type == "application/vnd.apache.arrow.file"
    table = pa.ipc.open_file(dest).read_all()
    assert table.column("A").to_pylist()


def test_live_nested_special_nodes_are_opaque(demo_catalog, monkeypatch):
    resource = _resolve(demo_catalog, "nested", monkeypatch)
    children = resource.materialize(MemoryDestination()).value
    for name in ("ragged_array", "awkward_array", "sparse_image"):
        child = children[name]
        info = child.info()
        assert info.kind is Kind.OPAQUE
        assert info.canonical_media_type is None
        child.materialize(MemoryDestination())
