"""The example catalog binds a scheme to a server. Resolve only imports urisolver."""
from __future__ import annotations

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


def test_catalog_binds_scheme_to_tiled_server():
    from urisolver.resolvers.example_tiled import tiled_base_uri

    assert tiled_base_uri(str(CATALOG)) == "https://tiled-demo.nsls2.bnl.gov"


def test_resolver_materializes_astronaut():
    proc = subprocess.run(
        [sys.executable, str(RESOLVE)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
    )
    if proc.returncode != 0:
        detail = proc.stderr or proc.stdout
        lowered = detail.lower()
        if any(token in lowered for token in ("unreachable", "nodename", "timed out", "timeout")):
            pytest.skip(detail.strip())
        raise AssertionError(detail)
    assert "(512, 512, 3)" in proc.stdout
    assert "786432" in proc.stdout
