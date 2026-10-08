"""CLI exit codes and the plan/register commands."""
from __future__ import annotations

import json

import numpy as np

from urisolver.cli import main


def test_usage_and_binders():
    assert main([]) == 2
    assert main(["plan"]) == 2
    code = main(["binders"])
    assert code == 0


def test_site_check(tmp_path, capsys):
    missing = main(["site", "check", str(tmp_path / "nope.yaml")])
    assert missing == 5
    site = tmp_path / "site.yaml"
    root = tmp_path / "real"
    root.mkdir()
    incoming = root / "incoming"
    incoming.mkdir()
    site.write_text(
        f"version: 1\nreadable:\n  - local: {root}\n    server: /data\n"
        f"landing:\n  local: {incoming}\n  layout: '{{protocol}}/{{sha12}}/{{name}}'\n",
        encoding="utf-8",
    )
    assert main(["site", "check", str(site)]) == 0
    assert "ok sources=0" in capsys.readouterr().out


def test_plan_and_register(tiled_site, tmp_path, capsys, monkeypatch):
    client, _site, real, srvview, server = tiled_site
    array = real / "sample.npy"
    np.save(array, np.arange(4, dtype=np.float32))
    site = tmp_path / "site.yaml"
    site.write_text(
        "\n".join(
            [
                "version: 1",
                "target:",
                f"  base_uri: {str(client.context.api_uri).rstrip('/')}",
                "  secret_id: target",
                "readable:",
                f"  - local: {real}",
                f"    server: {srvview}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TILED_API_KEY", server.api_key)
    args = ["--site", str(site), "--into", str(client.context.api_uri).rstrip("/")]
    assert main(["plan", array.as_uri(), *args]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["origin"]["mode"] == "reference"
    assert main(["register", array.as_uri(), *args]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["created"] is True
    assert created["mode"] == "reference"
    assert np.array_equal(np.asarray(client["sample"].read()), np.arange(4, dtype=np.float32))


def test_infeasible_mode_is_bind_error(tiled_site, tmp_path, monkeypatch):
    client, _site, real, srvview, server = tiled_site
    array = real / "sample.npy"
    np.save(array, np.arange(2, dtype=np.float32))
    site = tmp_path / "site.yaml"
    site.write_text(
        "\n".join(
            [
                "version: 1",
                "target:",
                f"  base_uri: {str(client.context.api_uri).rstrip('/')}",
                "readable:",
                f"  - local: {real}",
                f"    server: {srvview}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TILED_API_KEY", server.api_key)
    code = main(
        [
            "plan",
            array.as_uri(),
            "--site",
            str(site),
            "--into",
            str(client.context.api_uri).rstrip("/"),
            "--mode",
            "existing",
        ]
    )
    assert code == 3
