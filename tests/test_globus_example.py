"""Example Globus catalog, scripts, and the worker secret pipe."""
from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESOLVE = ROOT / "examples" / "globus" / "resolve.py"
WORKER = ROOT / "examples" / "globus" / "worker.py"
LOGIN = ROOT / "examples" / "globus" / "login.py"
SETUP = ROOT / "examples" / "globus" / "setup.py"
CATALOG = ROOT / "examples" / "catalog.yaml"
TUTORIAL = "6c54cade-bde5-45c1-bdea-f4bd71dba2cc"
CANARY = "globus-refresh-canary-value"
OTHER = "globus-client-secret-canary"


def test_import_urisolver_does_not_load_globus() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys\n"
            "import urisolver\n"
            "bad = [name for name in sys.modules if name == 'globus_sdk' "
            "or name.startswith('globus_sdk.') or name.startswith('urisolver.resolvers')]\n"
            "raise SystemExit(0 if not bad else ','.join(bad))\n",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout or proc.stderr


def test_scripts_do_not_name_the_sdk_or_the_collection() -> None:
    for path in (RESOLVE, WORKER, SETUP):
        text = path.read_text(encoding="utf-8")
        assert "globus_sdk" not in text
        assert "globus-sdk" not in text
        assert TUTORIAL not in text
        assert "refresh_token" not in text
        assert "client_secret" not in text
    login = LOGIN.read_text(encoding="utf-8")
    assert TUTORIAL not in login
    assert CANARY not in login


def test_catalog_entry_parses_staging() -> None:
    pytest.importorskip("yaml")
    from urisolver.resolvers._catalog import entry

    found = entry("com.urisolver.example.globus", protocol="globus", catalog_path=str(CATALOG))
    assert found["collection"] == TUTORIAL
    assert found["native"] == frozenset({"file"})
    assert found["secret_id"] == "globus-example"
    staging = found["staging"]
    assert staging["root"] == "/"
    assert staging["accessible"] == ["/CHANGE_ME"]
    assert staging["collection"] == "00000000-0000-0000-0000-000000000000"


def test_json_file_secrets_refuses_group_readable(tmp_path: Path) -> None:
    from urisolver.errors import SecretLookupError
    from urisolver.secrets.jsonfile import JsonFileSecrets

    path = tmp_path / "globus-example.json"
    path.write_text(json.dumps({"client_id": "cid", "refresh_token": CANARY}), encoding="utf-8")
    path.chmod(0o644)
    store = JsonFileSecrets(tmp_path)
    with pytest.raises(SecretLookupError, match="group or world readable"):
        store.get_secret("globus-example")
    assert CANARY not in repr(store)
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    secret = store.get_secret("globus-example")
    assert secret["refresh_token"] == CANARY


def test_worker_round_trip_leaves_the_secret_off_stdio(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    from urisolver.exchange import serve_stream
    from urisolver.secrets.exchange import secrets_handler

    seen: list[str] = []

    def translate(secret_id: str) -> dict[str, str]:
        seen.append(secret_id)
        return {"client_id": "cid", "refresh_token": CANARY, "client_secret": OTHER}

    parent, child = socket.socketpair()
    parent_stream = parent.makefile("rwb", buffering=0)
    thread = threading.Thread(
        target=serve_stream,
        args=(parent_stream, secrets_handler(translate)),
        daemon=True,
    )
    thread.start()
    fd = child.fileno()
    env = dict(os.environ)
    env["HTTP_PROXY"] = "http://127.0.0.1:1"
    env["HTTPS_PROXY"] = "http://127.0.0.1:1"
    env["ALL_PROXY"] = "http://127.0.0.1:1"
    proc = subprocess.run(
        [
            sys.executable,
            str(WORKER),
            "--worker",
            str(tmp_path / "file1.txt"),
            "--exchange-fd",
            str(fd),
        ],
        check=False,
        capture_output=True,
        text=True,
        pass_fds=(fd,),
        env=env,
    )
    child.close()
    thread.join(timeout=5)
    parent_stream.close()
    parent.close()
    combined = proc.stdout + proc.stderr
    assert CANARY not in combined
    assert OTHER not in combined
    assert seen == ["globus-example"]
    assert proc.returncode == 1
    assert "delivery failed" in proc.stderr


def test_local_secrets_manager_stores_a_private_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from urisolver.errors import SecretLookupError
    from urisolver.secrets.jsonfile import LocalSecretsManager

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    manager = LocalSecretsManager.default()
    path = manager.put_secret("globus-example", {"client_id": "cid", "refresh_token": CANARY})
    assert path == tmp_path / ".config" / "urisolver" / "secrets" / "globus-example.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert manager.get_secret("globus-example")["refresh_token"] == CANARY
    assert CANARY not in repr(manager)
    with pytest.raises(SecretLookupError, match="string map") as raised:
        manager.put_secret("globus-example", {"token": CANARY, "n": 1})  # type: ignore[dict-item]
    assert CANARY not in str(raised.value)
    with pytest.raises(SecretLookupError, match="path-safe"):
        manager.put_secret("../globus-example", {"client_id": "cid"})


def test_setup_writes_user_catalog_over_the_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("yaml")
    from urisolver.resolvers._catalog import entry

    collection = "11111111-1111-1111-1111-111111111111"
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env.pop("URISOLVER_CATALOG", None)
    proc = subprocess.run(
        [sys.executable, str(SETUP), "--collection", collection, "--accessible", "/data/stage"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    written = Path(proc.stdout.strip())
    assert written == tmp_path / ".config" / "urisolver" / "catalog.yaml"
    assert "CHANGE_ME" in CATALOG.read_text(encoding="utf-8")
    monkeypatch.delenv("URISOLVER_CATALOG", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    found = entry("com.urisolver.example.globus", protocol="globus")
    assert found["staging"]["collection"] == collection
    assert found["staging"]["accessible"] == ["/data/stage"]
