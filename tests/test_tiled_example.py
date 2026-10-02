"""The example catalog binds a scheme to a server. Resolve only imports urisolver."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESOLVE = ROOT / "examples" / "tiled" / "resolve.py"
CATALOG = ROOT / "examples" / "catalog.yaml"

pytest.importorskip("tiled")
pytest.importorskip("yaml")


def test_import_urisolver_does_not_load_tiled():
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys\n"
            "import urisolver\n"
            "bad = [name for name in sys.modules if name == 'tiled' or name.startswith('tiled.') "
            "or name.startswith('urisolver.resolvers')]\n"
            "raise SystemExit(0 if not bad else ','.join(bad))\n",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout or proc.stderr


def test_resolve_script_imports_urisolver_only():
    text = RESOLVE.read_text(encoding="utf-8")
    assert "import tiled" not in text
    assert "from tiled" not in text
    assert "TiledResolver" not in text
    assert "tiled-demo.nsls2.bnl.gov" not in text
    assert "LocalSecretsManager.default()" in text
    assert "Context(secrets=secrets)" in text


def test_catalog_binds_scheme_to_tiled_server(monkeypatch, tmp_path):
    from urisolver.resolvers.example_tiled import ExampleCatalogResolver, tiled_base_uri

    assert tiled_base_uri(str(CATALOG)) == "https://tiled-demo.nsls2.bnl.gov"
    monkeypatch.delenv("URISOLVER_CATALOG", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "empty-home"))
    assert tiled_base_uri() == "https://tiled-demo.nsls2.bnl.gov"
    assert ExampleCatalogResolver().native_modes == frozenset({"memory"})

    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        "com.urisolver.example.tiled:\n"
        "  protocol: tiled\n"
        "  base_uri: http://127.0.0.1:9\n"
        "  secret_id: demo\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("URISOLVER_CATALOG", str(catalog))
    resolver = ExampleCatalogResolver()
    assert resolver.base_uri == "http://127.0.0.1:9"
    assert resolver.secret_id == "demo"


@pytest.mark.skipif(
    os.environ.get("URISOLVER_TILED_PUBLIC") != "1",
    reason="set URISOLVER_TILED_PUBLIC=1 to fetch the public astronaut image",
)
def test_resolver_materializes_astronaut(tmp_path):
    httpx = pytest.importorskip("httpx")

    from urisolver.resolvers.example_tiled import tiled_base_uri

    base = tiled_base_uri(str(CATALOG)).rstrip("/")
    try:
        response = httpx.get(f"{base}/api/v1/", timeout=5.0)
    except httpx.HTTPError as exc:
        pytest.skip(str(exc))
    if response.status_code != 200:
        pytest.skip(f"HTTP {response.status_code}")
    proc = subprocess.run(
        [sys.executable, str(RESOLVE)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "(512, 512, 3)" in proc.stdout
    assert "786432" in proc.stdout
