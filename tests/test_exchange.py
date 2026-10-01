"""Opaque exchange over a direct call, a byte stream, and HTTP POST."""
from __future__ import annotations

import ast
import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from urisolver.errors import SecretLookupError
from urisolver.exchange import (
    DirectExchange,
    HttpExchange,
    StreamExchange,
    serve_http,
    serve_stream,
)
from urisolver.secrets.exchange import ExchangeSecrets, secrets_handler

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "testdrive.py"
EXCHANGE_SOURCE = ROOT / "src" / "urisolver" / "exchange.py"

CANARY = "super-secret-canary-value"
SAME = {"api_key": "k", "endpoint": "https://example.test/v1"}


def _translate(secret_id: str) -> dict[str, str]:
    if secret_id == "alpha":
        return {"token": CANARY}
    if secret_id == "beta":
        return dict(SAME)
    raise SecretLookupError(f"vault said {CANARY}")


def _check(secrets: ExchangeSecrets) -> None:
    assert secrets.get_secret("alpha") == {"token": CANARY}
    assert secrets.get_secret("beta") == SAME
    with pytest.raises(SecretLookupError, match="refused") as raised:
        secrets.get_secret("missing")
    assert CANARY not in str(raised.value)
    assert CANARY not in repr(secrets)


def test_exchange_module_does_not_name_secret_providers():
    source = EXCHANGE_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            continue
        assert all("secret" not in name for name in modules)
    lowered = source.lower()
    assert "secret" not in lowered
    assert "openbao" not in lowered
    assert "secretsmanager" not in lowered


def test_direct_exchange_same_helper():
    _check(ExchangeSecrets(DirectExchange(secrets_handler(_translate))))


def test_second_call_can_return_a_new_map():
    state = {"n": 0}

    def translate(secret_id: str) -> dict[str, str]:
        state["n"] += 1
        return {"token": f"t{state['n']}", "id": secret_id}

    secrets = ExchangeSecrets(DirectExchange(secrets_handler(translate)))
    assert secrets.get_secret("box") == {"token": "t1", "id": "box"}
    assert secrets.get_secret("box") == {"token": "t2", "id": "box"}


def test_stream_exchange_same_helper():
    handler = secrets_handler(_translate)
    parent, child = socket.socketpair()
    parent_stream = parent.makefile("rwb", buffering=0)
    child_stream = child.makefile("rwb", buffering=0)
    thread = threading.Thread(target=serve_stream, args=(parent_stream, handler), daemon=True)
    thread.start()
    try:
        exchange = StreamExchange(child_stream)
        _check(ExchangeSecrets(exchange))
        raw = exchange.exchange(json.dumps({"secret_id": "missing"}).encode("utf-8"))
    finally:
        child_stream.close()
        child.close()
        thread.join(timeout=5)
        parent_stream.close()
        parent.close()
    assert json.loads(raw) == {"ok": False, "error": "denied"}


def test_http_exchange_same_helper():
    running = serve_http(secrets_handler(_translate))
    try:
        _check(ExchangeSecrets(HttpExchange(running.url)))
    finally:
        running.close()


def test_worker_report_omits_the_exchanged_map(tmp_path: Path):
    parent, child = socket.socketpair()
    parent_stream = parent.makefile("rwb", buffering=0)
    thread = threading.Thread(
        target=serve_stream,
        args=(parent_stream, secrets_handler(_translate)),
        daemon=True,
    )
    thread.start()
    source = tmp_path / "source.dat"
    payload = b"testdrive-local\n"
    source.write_bytes(payload)
    dest = tmp_path / "staged.dat"
    fd = child.fileno()
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--worker",
            source.resolve().as_uri(),
            str(dest),
            "--exchange-fd",
            str(fd),
        ],
        check=False,
        capture_output=True,
        text=True,
        pass_fds=(fd,),
    )
    child.close()
    thread.join(timeout=5)
    parent_stream.close()
    parent.close()
    assert proc.returncode == 0, proc.stderr
    assert CANARY not in proc.stdout
    assert CANARY not in proc.stderr
    assert dest.read_bytes() == payload
    report = json.loads(proc.stdout)
    assert report["source_uri"] == source.resolve().as_uri()
    assert report["form"] == "path"
    assert report["is_reference"] is False
    assert report["strategy"] == "native"
