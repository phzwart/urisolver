"""URI shipped to a worker process: local file, and optionally the Zenodo record."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "testdrive.py"

ZENODO_RECORD_URI = "https://zenodo.org/records/23025715"
ZENODO_CONTENT_URI = (
    "https://zenodo.org/api/records/23025715/files/pdb_cells.duckdb/content"
)
ZENODO_FILENAME = "pdb_cells.duckdb"
ZENODO_SIZE = 54_538_240
ZENODO_MD5 = "cdabd111595d9fcd5a3700603063f7aa"


def _run_worker(uri: str, dest: Path, *, memory: bool) -> dict:
    cmd = [sys.executable, str(SCRIPT), "--worker", uri, str(dest)]
    if memory:
        cmd.append("--memory")
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _assert_file_delivery(report: dict, uri: str, dest: Path, size: int) -> None:
    assert report["uri"] == uri
    assert report["kind"] == "file"
    assert report["exists"] is True
    assert report["size_bytes"] == size
    assert report["supports_info"] is True
    assert report["supports_materialize"] is True
    assert Path(report["value"]) == dest
    assert dest.is_file()
    assert dest.stat().st_size == size
    assert report["form"] == "path"
    assert report["source_uri"] == uri
    assert report["is_reference"] is False
    assert report["strategy"] == "native"
    assert report["result_size_bytes"] == size


def test_local_file_shipped_to_worker(tmp_path: Path):
    payload = b"testdrive-local\n"
    source = tmp_path / "source.dat"
    source.write_bytes(payload)
    dest = tmp_path / "work" / "input.dat"
    uri = source.resolve().as_uri()

    report = _run_worker(uri, dest, memory=True)

    _assert_file_delivery(report, uri, dest, len(payload))
    assert dest.read_bytes() == payload
    assert report["memory_form"] == "native"
    assert base64.b64decode(report["memory_bytes_b64"]) == payload


@pytest.mark.skipif(
    os.environ.get("URISOLVER_ZENODO") != "1",
    reason="set URISOLVER_ZENODO=1 to download the Zenodo record",
)
def test_zenodo_record_shipped_to_worker(tmp_path: Path):
    dest = tmp_path / ZENODO_FILENAME
    report = _run_worker(ZENODO_RECORD_URI, dest, memory=False)

    _assert_file_delivery(report, ZENODO_RECORD_URI, dest, ZENODO_SIZE)
    assert report["resolved_uri"] == ZENODO_CONTENT_URI
    assert report["label"] == ZENODO_FILENAME
    assert report["canonical_media_type"] == "application/octet-stream"
    assert "memory_bytes_b64" not in report
    digest = hashlib.md5()
    with dest.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    assert digest.hexdigest() == ZENODO_MD5
