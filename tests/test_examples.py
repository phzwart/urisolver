"""The shipped examples run. Live ones skip unless their env var is set."""
from __future__ import annotations

import io
import os
import runpy
import subprocess
import sys
import textwrap
from contextlib import redirect_stdout
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def _run(script: str, env: dict[str, str]) -> str:
    merged = os.environ.copy()
    for key in (
        "URISOLVER_SITE",
        "URISOLVER_FILE_URI",
        "URISOLVER_INTO",
        "URISOLVER_TILED_URI",
        "URISOLVER_GLOBUS_LIVE",
        "URISOLVER_ZENODO",
        "URISOLVER_GLOBUS_CLIENT_ID",
        "TILED_UPSTREAM_API_KEY",
    ):
        merged.pop(key, None)
    merged.update(env)
    old = os.environ.copy()
    old_argv = sys.argv
    os.environ.clear()
    os.environ.update(merged)
    sys.argv = [script]
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            try:
                runpy.run_path(str(EXAMPLES / script), run_name="__main__")
            except SystemExit as exc:
                if exc.code not in (0, None):
                    raise
    finally:
        os.environ.clear()
        os.environ.update(old)
        sys.argv = old_argv
    return buffer.getvalue()


def test_live_examples_skip_without_env():
    assert "skip:" in _run("acquire_globus.py", {})
    assert "skip:" in _run("acquire_zenodo.py", {})
    assert "skip:" in _run("globus/login.py", {})
    assert "skip:" in _run("reference.py", {})
    assert "skip:" in _run("proxy.py", {})


def test_reference_example_registers(tiled_site, tmp_path):
    client, _site, real, srvview, server = tiled_site
    array = real / "sample.npy"
    np.save(array, np.arange(4, dtype=np.float32))
    site = tmp_path / "site.yaml"
    site.write_text(
        "\n".join(
            [
                "version: 1",
                "readable:",
                f"  - local: {real}",
                f"    server: {srvview}",
            ]
        ),
        encoding="utf-8",
    )
    output = _run(
        "reference.py",
        {
            "URISOLVER_SITE": str(site),
            "URISOLVER_FILE_URI": array.as_uri(),
            "URISOLVER_INTO": server.uri,
        },
    )
    assert "/sample" in output
    assert "sample" in list(client)


def test_proxy_example_registers(tiled_site, tmp_path, monkeypatch):
    from collections import ChainMap

    from urisolver.tiled_server.credentials import ENV
    from urisolver.tiled_server.proxy import PROXY_ARRAY_MIMETYPE, RemoteArrayAdapter, clear_client_cache

    client, _site, real, srvview, server = tiled_site
    base, api_key, proc = _upstream()
    try:
        creds = tmp_path / "creds.json"
        creds.write_text('{"%s": {"api_key": "%s"}}\n' % (base, api_key), encoding="utf-8")
        os.chmod(creds, 0o600)
        monkeypatch.setenv(ENV, str(creds))
        clear_client_cache()
        server.catalog.context.adapters_by_mimetype = ChainMap(
            {PROXY_ARRAY_MIMETYPE: RemoteArrayAdapter},
            server.catalog.context.adapters_by_mimetype,
        )
        site = tmp_path / "site.yaml"
        site.write_text(
            "\n".join(
                [
                    "version: 1",
                    "readable:",
                    f"  - local: {real}",
                    f"    server: {srvview}",
                    "sources:",
                    "  lab.tiled:",
                    "    protocol: tiled",
                    f"    base_uri: {base}",
                    "    proxy: true",
                    "    secret_id: upstream",
                ]
            ),
            encoding="utf-8",
        )
        output = _run(
            "proxy.py",
            {
                "URISOLVER_SITE": str(site),
                "URISOLVER_TILED_URI": "lab.tiled://img",
                "URISOLVER_INTO": server.uri,
                "TILED_UPSTREAM_API_KEY": api_key,
                ENV: str(creds),
            },
        )
    finally:
        if proc.poll() is None:
            proc.terminate()
    assert "/img" in output
    assert "img" in list(client)


def test_example_site_and_server_config_load():
    from urisolver.site import Site

    loaded = yaml.safe_load((EXAMPLES / "site.example.yaml").read_text(encoding="utf-8"))
    site = Site.from_mapping(loaded)
    assert site.sources["lab.globus"].params["secret_id"] == "globus-example"
    server = yaml.safe_load((EXAMPLES / "tiled-server.example.yml").read_text(encoding="utf-8"))
    adapters = server["trees"][0]["args"]["adapters_by_mimetype"]
    assert "urisolver.tiled_server.proxy:RemoteArrayAdapter" in adapters.values()
    assert "urisolver.tiled_server.proxy:RemoteTableAdapter" in adapters.values()


def _upstream():
    script = textwrap.dedent(
        """
        import numpy as np
        from tiled.client import from_uri
        from tiled.server import SimpleTiledServer
        server = SimpleTiledServer(api_key="upstreamkey")
        client = from_uri(server.uri)
        client.write_array(np.arange(6, dtype=np.float32).reshape(2, 3), key="img")
        print(server.uri, flush=True)
        raise SystemExit(server._server.thread.join())
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline().strip()
    if not line:
        err = proc.stderr.read() if proc.stderr is not None else ""
        proc.kill()
        raise RuntimeError(err)
    parsed = urlparse(line)
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    api_key = parse_qs(parsed.query)["api_key"][0]
    return base, api_key, proc
