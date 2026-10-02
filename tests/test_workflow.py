"""Offline checks for the shared frontend and the per-job holder/worker."""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from urisolver import Context, FileDestination, Form, MemoryDestination, Registry
from urisolver.errors import SecretLookupError
from urisolver.results import MaterializedResult
from urisolver.secrets.exchange import secrets_handler

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "examples" / "frontend.py"
WORKER = ROOT / "examples" / "workflow" / "worker.py"
OFFLINE = ROOT / "examples" / "workflow" / "offline.py"
ORCH = ROOT / "examples" / "workflow" / "orchestrate.py"
CANARY = "CANARY-refresh-7f3a"
OFFLINE_URI = "com.urisolver.example.offline:///globus-example"
DENIED = b'{"ok": false, "error": "denied"}'


class Array:
    """Stand-in for a native in-memory value."""


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake(file_strategy: str, memory_strategy: str, memory_value: object):
    class _Resolver:
        def resolve(self, uri: str, context: object) -> "_Resource":
            return _Resource(uri)

        def close(self) -> None:
            return None

    class _Resource:
        def __init__(self, uri: str) -> None:
            self.uri = uri

        def materialize(self, destination: object, **kwargs: object) -> MaterializedResult:
            if isinstance(destination, MemoryDestination):
                value: object = memory_value
                strategy = memory_strategy
                size = None
                form = Form.NATIVE
            else:
                assert isinstance(destination, FileDestination)
                path = Path(destination.path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
                value = path
                strategy = file_strategy
                size = 1
                form = Form.PATH
            return MaterializedResult(
                value=value,
                source_uri=self.uri,
                resolved_uri=self.uri,
                protocol="example",
                destination=destination,
                form=form,
                media_type=None,
                size_bytes=size,
                selection=None,
                is_reference=False,
                strategy=strategy,
            )

    return _Resolver()


def _fake_context() -> Context:
    registry = Registry()
    registry.register(
        "com.urisolver.example.tiled",
        _fake("converted", "native", Array()),
        source="example",
    )
    registry.register("https", _fake("native", "native", b"zenodo"), source="example")
    registry.register(
        "com.urisolver.example.globus",
        _fake("native", "staged", b"globus"),
        source="example",
    )
    return Context(registry=registry)


def _run(script: Path, args: list[str], *, stdin: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        input=stdin,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _home_env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = str(home)
    return env


def _endpoint_port(stderr: str) -> int:
    for line in stderr.splitlines():
        if line.startswith("endpoint "):
            return int(line.rsplit(":", 1)[-1].rstrip("/"))
    raise AssertionError(stderr)


def _assert_port_closed(port: int) -> None:
    sock = socket.socket()
    sock.settimeout(1)
    try:
        with pytest.raises(OSError):
            sock.connect(("127.0.0.1", port))
    finally:
        sock.close()


def test_frontend_same_code_three_resolvers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mod = _load(FRONTEND, "frontend_same")
    monkeypatch.chdir(tmp_path)
    with _fake_context() as ctx:
        staged = [mod.stage(uri, dest, ctx) for uri, dest in mod.URIS]
    assert [item.strategy for item in staged] == ["converted", "native", "native"]
    text = FRONTEND.read_text(encoding="utf-8")
    assert "def stage(uri, dest, ctx):" in text
    assert "r = ctx.resolve(uri)" in text
    assert "return r.materialize(FileDestination(dest))" in text


def test_frontend_reports_strategy_per_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    mod = _load(FRONTEND, "frontend_strategy")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "build_context", _fake_context)
    assert mod.main([]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "astronaut.npy 1 converted",
        "pdb_cells.duckdb 1 native",
        "file1.txt 1 native",
    ]
    assert mod.main(["--memory"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Array native",
        "bytes native",
        "bytes staged",
    ]


def test_worker_and_frontend_name_no_scheme():
    banned = ("scheme", "tiled", "zenodo", "globus", "https", "://")
    for path in (FRONTEND, WORKER):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = ast.get_source_segment(source, node.test) or ""
            lowered = test.lower()
            assert not any(word in lowered for word in banned), (path.name, test)


def test_orchestrator_never_resolves():
    source = ORCH.read_text(encoding="utf-8")
    assert "resolve" not in source
    assert "materialize" not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            continue
        assert name not in {"resolve", "materialize"}


def test_worker_never_imports_local_store():
    for path in (WORKER, OFFLINE):
        source = path.read_text(encoding="utf-8")
        assert "LocalSecretsManager" not in source
        assert "JsonFileSecrets" not in source
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            assert all("jsonfile" not in name for name in modules)


def test_worker_writes_nothing_under_home(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    source = tmp_path / "source.dat"
    payload = b"public\n"
    source.write_bytes(payload)
    dest = tmp_path / "out" / "staged.dat"
    proc = _run(
        WORKER,
        [source.resolve().as_uri(), str(dest), "http://127.0.0.1:9/"],
        stdin="unused-token\n",
        env=_home_env(home),
    )
    assert proc.returncode == 0, proc.stderr
    assert dest.read_bytes() == payload
    assert not (home / ".config" / "urisolver").exists()


def test_local_workflow_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    from urisolver.secrets.jsonfile import LocalSecretsManager

    LocalSecretsManager.default().put_secret("globus-example", {"token": CANARY})
    dest = tmp_path / "staged.txt"
    proc = _run(
        ORCH,
        ["--local", "--allow", "globus-example", OFFLINE_URI, str(dest)],
        stdin="",
        env=_home_env(home),
    )
    assert proc.returncode == 0, proc.stderr
    assert dest.read_bytes() == b"offline\n"
    report = json.loads(proc.stdout)
    assert report["strategy"] == "native"
    assert report["source_uri"] == OFFLINE_URI
    assert CANARY not in proc.stdout
    assert CANARY not in proc.stderr
    _assert_port_closed(_endpoint_port(proc.stderr))


def test_no_tunnel_fails_closed_even_with_local_store_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    from urisolver.secrets.jsonfile import LocalSecretsManager

    path = LocalSecretsManager.default().put_secret("globus-example", {"token": CANARY})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    before = sorted(item.relative_to(home) for item in home.rglob("*"))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    dest = tmp_path / "should-not-exist"
    proc = _run(
        WORKER,
        [OFFLINE_URI, str(dest), f"http://127.0.0.1:{port}/"],
        stdin="unused-token\n",
        env=_home_env(home),
    )
    assert proc.returncode != 0
    assert "SecretLookupError" in proc.stderr
    assert CANARY not in proc.stderr
    assert not dest.exists()
    after = sorted(item.relative_to(home) for item in home.rglob("*"))
    assert after == before


def test_public_resource_resolves_without_tunnel(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    source = tmp_path / "source.dat"
    payload = b"public-no-tunnel\n"
    source.write_bytes(payload)
    dest = tmp_path / "staged.dat"
    proc = _run(
        WORKER,
        [source.resolve().as_uri(), str(dest), "http://127.0.0.1:9/"],
        stdin="unused-token\n",
        env=_home_env(home),
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["strategy"] == "native"
    assert report["source_uri"] == source.resolve().as_uri()
    assert dest.read_bytes() == payload


def test_unlisted_secret_id_is_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mod = _load(ORCH, "workflow_orchestrate_deny")

    class _Store:
        def get_secret(self, secret_id: str) -> dict[str, str]:
            if secret_id == "globus-example":
                return {"token": CANARY}
            raise SecretLookupError("secret file is not readable")

    handler = secrets_handler(mod.job_lookup(_Store(), {"globus-example"}))
    unlisted = handler(json.dumps({"secret_id": "other-id"}).encode("utf-8"))
    unknown = handler(json.dumps({"secret_id": "missing"}).encode("utf-8"))
    assert unlisted == unknown == DENIED
    assert CANARY not in unlisted.decode("utf-8")

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    dest = tmp_path / "denied"
    proc = _run(
        ORCH,
        [
            "--local",
            "--allow",
            "globus-example",
            "com.urisolver.example.offline:///other-id",
            str(dest),
        ],
        stdin="",
        env=_home_env(home),
    )
    assert proc.returncode != 0
    assert "SecretLookupError" in proc.stderr
    assert CANARY not in proc.stderr
    assert not dest.exists()


def test_token_not_in_argv_or_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    mod = _load(ORCH, "workflow_orchestrate_argv")
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = [str(part) for part in cmd]
        captured["input"] = kwargs.get("input")
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod.main(["--local", OFFLINE_URI, str(tmp_path / "out")]) == 0
    token = str(captured["input"]).strip()
    assert token
    assert token not in "\n".join(captured["cmd"])  # type: ignore[arg-type]
    assert captured["env"] is None
    assert all(token not in value for value in os.environ.values())


def test_endpoint_closed_after_worker_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    from urisolver.secrets.jsonfile import LocalSecretsManager

    LocalSecretsManager.default().put_secret("globus-example", {"token": CANARY})
    dest = tmp_path / "staged.txt"
    success = _run(
        ORCH,
        ["--local", "--allow", "globus-example", OFFLINE_URI, str(dest)],
        stdin="",
        env=_home_env(home),
    )
    assert success.returncode == 0, success.stderr
    _assert_port_closed(_endpoint_port(success.stderr))

    failed = _run(
        ORCH,
        ["--local", "com.urisolver.example.offline:///other-id", str(tmp_path / "nope")],
        stdin="",
        env=_home_env(home),
    )
    assert failed.returncode != 0
    assert "SecretLookupError" in failed.stderr
    _assert_port_closed(_endpoint_port(failed.stderr))


def test_canary_absent_from_worker_stdio_and_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    from urisolver.secrets.jsonfile import LocalSecretsManager

    LocalSecretsManager.default().put_secret("globus-example", {"token": CANARY})
    dest = tmp_path / "staged.txt"
    success = _run(
        ORCH,
        ["--local", "--allow", "globus-example", OFFLINE_URI, str(dest)],
        stdin="",
        env=_home_env(home),
    )
    assert success.returncode == 0, success.stderr
    assert CANARY not in success.stdout
    assert CANARY not in success.stderr

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    failed = _run(
        WORKER,
        [OFFLINE_URI, str(tmp_path / "missing"), f"http://127.0.0.1:{port}/"],
        stdin=CANARY + "\n",
        env=_home_env(home),
    )
    assert failed.returncode != 0
    assert "SecretLookupError" in failed.stderr
    assert CANARY not in failed.stdout
    assert CANARY not in failed.stderr
