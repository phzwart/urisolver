"""The concept graph stays tied to the source tree and to the ledger."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from urisolver.kg.graph import ConceptGraph

ROOT = Path(__file__).resolve().parents[1]
KG = ROOT / "src" / "urisolver" / "kg"
OUT = KG / "out"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_anchors_rebuild_has_zero_problems(tmp_path):
    dest = tmp_path / "anchors.json"
    proc = subprocess.run(
        [sys.executable, str(KG / "anchors.py"), str(ROOT), str(dest)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 problems" in proc.stdout
    payload = json.loads(dest.read_text())
    assert payload["anchors"]


def test_code_evidence_sha256_matches_files():
    payload = json.loads((OUT / "urisolver_concepts.json").read_text())
    seen: dict[str, str] = {}
    for concept in payload["concepts"]:
        assert concept["code_evidence"], concept["id"]
        for anchor in concept["code_evidence"]:
            module = anchor["module"]
            digest = _sha(ROOT / module)
            assert anchor["sha256"] == digest, module
            seen.setdefault(module, digest)
    assert "DESIGN.md" in seen
    assert "src/urisolver/redaction.py" in seen


def test_relation_targets_and_csv_endpoints_exist():
    payload = json.loads((OUT / "urisolver_concepts.json").read_text())
    ids = {concept["id"] for concept in payload["concepts"]}
    for concept in payload["concepts"]:
        for rel in concept["relations"]:
            assert rel["target"] in ids, f"{concept['id']} -> {rel['target']}"
    neo = OUT / "neo4j"
    with (neo / "concept_relations.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            assert row[":START_ID(Concept)"] in ids
            assert row[":END_ID(Concept)"] in ids
    evidence = set()
    with (neo / "code_evidence.csv").open(newline="") as handle:
        evidence = {row["id:ID(Evidence)"] for row in csv.DictReader(handle)}
    with (neo / "code_evidence_edges.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            assert row[":START_ID(Concept)"] in ids
            assert row[":END_ID(Evidence)"] in evidence
    references = set()
    with (neo / "references.csv").open(newline="") as handle:
        references = {row["id:ID(Reference)"] for row in csv.DictReader(handle)}
    with (neo / "reference_edges.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            assert row[":START_ID(Concept)"] in ids
            assert row[":END_ID(Reference)"] in references


def test_search_card_module_and_receipt():
    graph = ConceptGraph.load(OUT)
    assert graph.resolve("Opaque payload") == "opaque_payload"
    hits = graph.search("opaque payload")
    assert hits["hits"][0]["id"] == "opaque_payload"
    card = graph.card("tier_0")
    assert card["id"] == "tier_0"
    assert card["definition_receipt"] == "ent:concept:tier_0"
    assert card["code_evidence"]
    receipt = graph.receipt(card["definition_receipt"])
    assert receipt["node"]["@id"] == "ent:concept:tier_0"
    assert receipt["node"]["how"] == "derived"
    for anchor in card["code_evidence"]:
        node = graph.receipt(anchor["receipt"])["node"]
        assert node["how"] == "quote"
        assert node["target"]["selector"]["exact"] == anchor["quote"]
    redaction = graph.module("src/urisolver/redaction.py")
    assert {row["id"] for row in redaction["concepts"]} >= {"opaque_payload", "redaction"}


def test_ledger_receipts_exist_for_every_claim():
    graph = ConceptGraph.load(OUT)
    for concept in graph.concepts:
        card = graph.card(concept["id"])
        assert card["definition_receipt"] in graph.nodes
        for rel in card["relations"]:
            assert rel["receipt"] in graph.nodes
        for anchor in card["code_evidence"]:
            assert anchor["receipt"] in graph.nodes
        for ref in card["references"]:
            assert ref["receipt"] in graph.nodes
            assert ref["status"] == "citation"


def test_ledger_validates():
    if importlib.util.find_spec("pygrits") is None:
        pytest.skip("pygrits is not installed")
    import pygrits
    ledger = json.loads((OUT / "urisolver_kg.grits.jsonld").read_text())
    pygrits.validate(pygrits.load(ledger))
