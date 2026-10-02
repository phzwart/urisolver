"""Build the urisolver concept knowledge graph.

Outputs (in ./out, which the query module loads):
  urisolver_concepts.json     payload: concepts, relations, evidence, references
  concept-schema.json         JSON Schema of the payload
  urisolver_kg.grits.jsonld   pygrits ledger (receipts for every claim)
  neo4j/*.csv, load.cypher    Neo4j import package + competency queries
  README.md                   counts regenerated from the payload

Also rewrites anchors.json beside this file.

Refuses to write when ``git status --porcelain`` is non-empty unless
``--allow-dirty`` is passed. The payload records the commit hash and dirty flag.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from anchors import extract, repo_root  # noqa: E402
from concepts import CONCEPTS  # noqa: E402
from literature import lookup as literature_lookup  # noqa: E402

REPO = repo_root()
OUT = HERE / "out"


def git_snapshot(allow_dirty: bool) -> dict:
    """Commit the graph was built from. Exit when the tree is dirty."""
    porcelain = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=REPO, text=True,
    )
    dirty = bool(porcelain.strip())
    if dirty and not allow_dirty:
        sys.exit(
            "refusing to build from a dirty tree "
            "(git status --porcelain is non-empty). Commit, or pass --allow-dirty."
        )
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True,
    ).strip()
    return {
        "repository": "https://github.com/phzwart/urisolver",
        "commit": commit,
        "dirty": dirty,
    }


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


AGENT = "urisolver-kg-builder/0.1"
PAYLOAD_SCHEMA_URL = (
    "https://github.com/phzwart/urisolver/blob/main/src/urisolver/kg/out/concept-schema.json"
)
FETCH_DATE = "2026-10-02"
RELATIONS = [
    "IS_A", "PART_OF", "USES", "DUAL_OF", "SPECIALIZES", "EQUIVALENT_TO",
    "RELATED_TO", "DEFINED_BY", "INSTANCE_OF", "CONTRASTS_WITH",
]


def main() -> int:
    snapshot = git_snapshot("--allow-dirty" in sys.argv)
    try:
        import pygrits
    except ImportError:
        sys.exit("pygrits is required to build the ledger (pip install -e '.[kg]', Python >= 3.11)")

    anchors, digests, problems = extract(REPO)
    if problems:
        for problem in problems:
            print("  -", problem, file=sys.stderr)
        sys.exit(f"refusing to build: {len(problems)} anchor problems")
    (HERE / "anchors.json").write_text(
        json.dumps({"anchors": anchors, "files": digests}, indent=1) + "\n",
        encoding="utf-8",
    )
    (OUT / "neo4j").mkdir(parents=True, exist_ok=True)

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PAYLOAD_SCHEMA_URL,
        "title": "urisolver concept graph payload",
        "type": "object",
        "required": ["version", "generated", "concepts"],
        "properties": {
            "version": {"type": "string"},
            "generated": {"type": "string"},
            "source_repository": {"type": "string"},
            "concepts": {"type": "array", "items": {"$ref": "#/$defs/concept"}},
        },
        "$defs": {
            "concept": {
                "type": "object",
                "required": ["id", "label", "kind", "definition", "relations", "code_evidence", "references"],
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                    "label": {"type": "string"},
                    "kind": {"enum": ["architecture", "contract", "protocol", "scheme"]},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "definition": {"type": "string"},
                    "literature": {"type": "array", "items": {"type": "string"}},
                    "relations": {"type": "array", "items": {
                        "type": "object", "required": ["type", "target"],
                        "properties": {
                            "type": {"enum": RELATIONS},
                            "target": {"type": "string"},
                        },
                    }},
                    "code_evidence": {"type": "array", "items": {
                        "type": "object",
                        "required": ["module", "symbol", "line", "quote", "uri", "sha256"],
                        "properties": {
                            "module": {"type": "string"}, "symbol": {"type": "string"},
                            "kind": {"type": "string"}, "line": {"type": "integer"},
                            "quote": {"type": "string"}, "uri": {"type": "string"},
                            "sha256": {"type": "string"},
                        },
                    }},
                    "references": {"type": "array", "items": {
                        "type": "object",
                        "required": ["source", "title", "url", "status"],
                        "properties": {
                            "source": {"enum": ["literature"]},
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "page_title": {"type": "string"},
                            "status": {"enum": ["citation"]},
                            "quote": {"type": "string"},
                            "note": {"type": "string"},
                            "fetched": {"type": "string"},
                        },
                    }},
                },
            }
        },
    }
    schema_bytes = json.dumps(schema, indent=2).encode() + b"\n"
    (OUT / "concept-schema.json").write_bytes(schema_bytes)

    by_concept: dict[str, list] = {}
    for anchor in anchors:
        by_concept.setdefault(anchor["concept"], []).append(anchor)

    payload = {
        "version": "0.1.0",
        "generated": FETCH_DATE,
        "source_repository": snapshot["repository"],
        "snapshot": snapshot,
        "concepts": [],
    }
    for concept in CONCEPTS:
        refs = []
        for citation in concept["refs"]:
            hit = literature_lookup(citation)
            refs.append({
                "source": "literature",
                "title": citation,
                "url": hit.get("url") or "",
                "page_title": hit.get("title") or citation,
                "status": "citation",
                "quote": "",
                "note": "bibliographic pointer; no sentence was fetched",
                "fetched": FETCH_DATE,
            })
        payload["concepts"].append({
            "id": concept["id"],
            "label": concept["label"],
            "kind": concept["kind"],
            "aliases": concept["aliases"],
            "definition": concept["definition"],
            "literature": concept["refs"],
            "relations": [{"type": rel, "target": target} for rel, target in concept["rels"]],
            "code_evidence": [
                {
                    "module": anchor["module"],
                    "symbol": anchor["symbol"],
                    "kind": anchor["kind"],
                    "line": anchor["line"],
                    "quote": anchor["exact"],
                    "uri": anchor["uri"],
                    "sha256": anchor["sha256"],
                }
                for anchor in by_concept.get(concept["id"], [])
            ],
            "references": refs,
        })
    payload_bytes = json.dumps(payload, indent=1, ensure_ascii=False).encode() + b"\n"
    (OUT / "urisolver_concepts.json").write_bytes(payload_bytes)
    payload_ref = {
        "uri": "https://github.com/phzwart/urisolver/blob/main/src/urisolver/kg/out/urisolver_concepts.json",
        "sha256": sha(payload_bytes),
    }

    plan_id = "plan:urisolver-concept-kg-2026-10-02"
    graph = [{
        "@id": plan_id,
        "@type": "prov:Plan",
        "name": (
            "urisolver concept knowledge graph: extract architectural contracts "
            "from DESIGN.md, SCHEMES.md, and package docstrings"
        ),
        "prompt_digest": sha((HERE / "prompt.txt").read_bytes()),
        "schema_digest": sha(schema_bytes),
        "agent": AGENT,
    }]
    n_quote = n_ref = n_rel = 0
    for concept in payload["concepts"]:
        cid = concept["id"]
        used = []
        for index, anchor in enumerate(concept["code_evidence"]):
            eid = f"evi:code:{cid}:{index}"
            graph.append({
                "@id": eid,
                "@type": "prov:Entity",
                "plan": plan_id,
                "how": "quote",
                "agent": AGENT,
                "source": {"uri": anchor["uri"], "sha256": anchor["sha256"], "media_type": _media(anchor["module"])},
                "target": {
                    "hasSource": anchor["uri"],
                    "selector": {"@type": "oa:TextQuoteSelector", "exact": anchor["quote"]},
                },
                "summary": f"{anchor['module']}:{anchor['symbol'] or '<module docstring>'} line {anchor['line']}",
            })
            used.append(eid)
            n_quote += 1
        lit_n = 0
        for ref in concept["references"]:
            lit_n += 1
            eid = f"evi:lit:{cid}:{lit_n}"
            where = ref.get("url") or "no URL confirmed"
            graph.append({
                "@id": eid,
                "@type": "prov:Entity",
                "plan": plan_id,
                "how": "derived",
                "agent": AGENT,
                "rationale": (
                    "Bibliographic pointer copied from the concept's literature list. "
                    "No sentence was fetched, so this is not a quote."
                ),
                "summary": f"{ref['title']} {where}".strip(),
            })
            n_ref += 1
            used.append(eid)
        cent = f"ent:concept:{cid}"
        generated = [cent]
        graph.append({
            "@id": cent,
            "@type": "prov:Entity",
            "plan": plan_id,
            "how": "derived",
            "agent": AGENT,
            "rationale": (
                "Definition paraphrased by the builder from the anchored spec sentences "
                "and docstrings listed in the derivation's 'used'; the wording is the "
                "builder's, not a quotation."
            ),
            "summary": f"{concept['label']}: {concept['definition']}",
            "plan_variable": f"pplan:vars/concept/{cid}",
            "payload": PAYLOAD_SCHEMA_URL,
            "payload_ref": payload_ref,
        })
        for rel in concept["relations"]:
            rid = f"ent:rel:{cid}:{rel['type']}:{rel['target']}"
            graph.append({
                "@id": rid,
                "@type": "prov:Entity",
                "plan": plan_id,
                "how": "inferred",
                "agent": AGENT,
                "rationale": (
                    "Relation asserted by the builder from how the anchored text uses "
                    "or defines the two concepts together; not stated verbatim in any "
                    "single source."
                ),
                "summary": f"{cid} {rel['type']} {rel['target']}",
                "payload": PAYLOAD_SCHEMA_URL,
                "payload_ref": payload_ref,
            })
            generated.append(rid)
            n_rel += 1
        graph.append({
            "@id": f"act:derive:{cid}",
            "@type": "prov:Activity",
            "plan": plan_id,
            "kind": "derivation",
            "performed_by": AGENT,
            "plan_step": "pplan:steps/derive_concept",
            "used": used,
            "generated": generated,
            "started_at": f"{FETCH_DATE}T00:00:00Z",
            "ended_at": f"{FETCH_DATE}T23:59:59Z",
        })

    ledger = {"@context": "https://phzwart.github.io/pygrits/context.jsonld", "@graph": graph}
    bundle = pygrits.load(ledger)
    pygrits.validate(bundle)
    pygrits.dump(bundle, OUT / "urisolver_kg.grits.jsonld")
    print(
        f"ledger ok: {len(graph)} nodes ({n_quote} quotes, {n_ref} citations, "
        f"{n_rel} relations, {len(payload['concepts'])} concepts)"
    )
    _write_neo4j(payload)
    _write_readme(payload, snapshot)
    print("snapshot:", snapshot["commit"], "dirty=" + str(snapshot["dirty"]).lower())
    return 0


def _media(module: str) -> str:
    if module.endswith(".md"):
        return "text/markdown"
    return "text/x-python"


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def _write_neo4j(payload: dict) -> None:
    neo = OUT / "neo4j"
    _write_csv(
        neo / "concepts.csv",
        [
            {
                "id:ID(Concept)": concept["id"],
                "label": concept["label"],
                "kind": concept["kind"],
                "definition": concept["definition"],
                "aliases": ";".join(concept["aliases"]),
                "literature": ";".join(concept["literature"]),
                ":LABEL": "Concept",
            }
            for concept in payload["concepts"]
        ],
        ["id:ID(Concept)", "label", "kind", "definition", "aliases", "literature", ":LABEL"],
    )
    _write_csv(
        neo / "concept_relations.csv",
        [
            {
                ":START_ID(Concept)": concept["id"],
                ":END_ID(Concept)": rel["target"],
                ":TYPE": rel["type"],
                "receipt": f"ent:rel:{concept['id']}:{rel['type']}:{rel['target']}",
            }
            for concept in payload["concepts"]
            for rel in concept["relations"]
        ],
        [":START_ID(Concept)", ":END_ID(Concept)", ":TYPE", "receipt"],
    )
    code_rows = []
    code_edges = []
    for concept in payload["concepts"]:
        for index, anchor in enumerate(concept["code_evidence"]):
            eid = f"evi:code:{concept['id']}:{index}"
            code_rows.append({
                "id:ID(Evidence)": eid,
                "module": anchor["module"],
                "symbol": anchor["symbol"],
                "symbol_kind": anchor["kind"],
                "line:int": anchor["line"],
                "quote": anchor["quote"],
                "uri": anchor["uri"],
                "sha256": anchor["sha256"],
                ":LABEL": "CodeEvidence",
            })
            code_edges.append({
                ":START_ID(Concept)": concept["id"],
                ":END_ID(Evidence)": eid,
                ":TYPE": "HAS_CODE_EVIDENCE",
            })
    evidence_fields = [
        "id:ID(Evidence)", "module", "symbol", "symbol_kind", "line:int",
        "quote", "uri", "sha256", ":LABEL",
    ]
    _write_csv(neo / "code_evidence.csv", code_rows, evidence_fields)
    _write_csv(
        neo / "code_evidence_edges.csv",
        code_edges,
        [":START_ID(Concept)", ":END_ID(Evidence)", ":TYPE"],
    )
    ref_rows = []
    ref_edges = []
    seen: set[str] = set()
    lit_count: dict[str, int] = {}
    for concept in payload["concepts"]:
        for ref in concept["references"]:
            lit_count[concept["id"]] = lit_count.get(concept["id"], 0) + 1
            receipt = f"evi:lit:{concept['id']}:{lit_count[concept['id']]}"
            slug = re.sub(r"[^a-z0-9]+", "", ref["title"].lower())[:48]
            rid = f"ref:literature:{slug}"
            if rid not in seen:
                seen.add(rid)
                ref_rows.append({
                    "id:ID(Reference)": rid,
                    "source": ref["source"],
                    "title": ref["title"],
                    "page_title": ref.get("page_title", ""),
                    "url": ref["url"],
                    "status": ref["status"],
                    "quote": ref.get("quote", ""),
                    "note": ref.get("note", ""),
                    "fetched": ref["fetched"],
                    ":LABEL": "Reference;Literature",
                })
            ref_edges.append({
                ":START_ID(Concept)": concept["id"],
                ":END_ID(Reference)": rid,
                ":TYPE": "DEFINED_IN",
                "receipt": receipt,
            })
    _write_csv(
        neo / "references.csv",
        ref_rows,
        [
            "id:ID(Reference)", "source", "title", "page_title", "url", "status",
            "quote", "note", "fetched", ":LABEL",
        ],
    )
    _write_csv(
        neo / "reference_edges.csv",
        ref_edges,
        [":START_ID(Concept)", ":END_ID(Reference)", ":TYPE", "receipt"],
    )
    (neo / "load.cypher").write_text(
        "// urisolver concept knowledge graph -- Neo4j 5 loader\n"
        "// Copy the CSVs into the import/ directory, then run this file.\n"
        "CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE;\n"
        "CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (e:CodeEvidence) REQUIRE e.id IS UNIQUE;\n"
        "CREATE CONSTRAINT reference_id IF NOT EXISTS FOR (r:Reference) REQUIRE r.id IS UNIQUE;\n"
        "CREATE FULLTEXT INDEX concept_text IF NOT EXISTS "
        "FOR (c:Concept) ON EACH [c.label, c.definition, c.aliases];\n"
        "CREATE FULLTEXT INDEX reference_text IF NOT EXISTS "
        "FOR (r:Reference) ON EACH [r.title, r.quote];\n"
        "\n"
        "LOAD CSV WITH HEADERS FROM 'file:///concepts.csv' AS row\n"
        "MERGE (c:Concept {id: row.`id:ID(Concept)`})\n"
        "SET c.label = row.label, c.kind = row.kind, c.definition = row.definition,\n"
        "    c.aliases = [a IN split(row.aliases, ';') WHERE a <> ''],\n"
        "    c.literature = [l IN split(row.literature, ';') WHERE l <> ''];\n"
        "\n"
        "LOAD CSV WITH HEADERS FROM 'file:///code_evidence.csv' AS row\n"
        "MERGE (e:CodeEvidence {id: row.`id:ID(Evidence)`})\n"
        "SET e.module = row.module, e.symbol = row.symbol, e.symbol_kind = row.symbol_kind,\n"
        "    e.line = toInteger(row.`line:int`), e.quote = row.quote, e.uri = row.uri,\n"
        "    e.sha256 = row.sha256;\n"
        "\n"
        "LOAD CSV WITH HEADERS FROM 'file:///code_evidence_edges.csv' AS row\n"
        "MATCH (c:Concept {id: row.`:START_ID(Concept)`}), "
        "(e:CodeEvidence {id: row.`:END_ID(Evidence)`})\n"
        "MERGE (c)-[:HAS_CODE_EVIDENCE]->(e);\n"
        "\n"
        "LOAD CSV WITH HEADERS FROM 'file:///references.csv' AS row\n"
        "MERGE (r:Reference {id: row.`id:ID(Reference)`})\n"
        "SET r.source = row.source, r.title = row.title, r.page_title = row.page_title,\n"
        "    r.url = row.url, r.status = row.status, r.quote = row.quote,\n"
        "    r.note = row.note, r.fetched = row.fetched\n"
        "WITH r, row\n"
        "CALL { WITH r, row WITH r, row WHERE row.source = 'literature' SET r:Literature }\n"
        "RETURN count(r);\n"
        "\n"
        "LOAD CSV WITH HEADERS FROM 'file:///reference_edges.csv' AS row\n"
        "MATCH (c:Concept {id: row.`:START_ID(Concept)`}), "
        "(r:Reference {id: row.`:END_ID(Reference)`})\n"
        "MERGE (c)-[d:DEFINED_IN]->(r) SET d.receipt = row.receipt;\n"
        "\n"
        "LOAD CSV WITH HEADERS FROM 'file:///concept_relations.csv' AS row\n"
        "MATCH (a:Concept {id: row.`:START_ID(Concept)`}), "
        "(b:Concept {id: row.`:END_ID(Concept)`})\n"
        "CALL apoc.merge.relationship(a, row.`:TYPE`, {}, {receipt: row.receipt}, b, {}) "
        "YIELD rel\n"
        "RETURN count(rel);\n"
        "// Without APOC, replace the last statement by one MERGE per type, e.g.\n"
        "// MATCH ... WHERE row.`:TYPE` = 'USES' MERGE (a)-[:USES {receipt: row.receipt}]->(b);\n",
        encoding="utf-8",
    )
    (neo / "queries.cypher").write_text(
        "// Competency queries\n"
        "// 1. Where is a concept anchored?\n"
        "MATCH (c:Concept {id: 'opaque_payload'})-[:HAS_CODE_EVIDENCE]->(e)\n"
        "RETURN e.module, e.symbol, e.line, e.quote;\n"
        "// 2. What does a contract rest on?\n"
        "MATCH p = (c:Concept {id: 'tier_0'})-[:USES*1..3]->(d)\n"
        "RETURN DISTINCT d.id, length(p) AS depth ORDER BY depth;\n"
        "// 3. Paraphrase plus bibliographic pointers\n"
        "MATCH (c:Concept {id: 'scheme_dispatch'})\n"
        "OPTIONAL MATCH (c)-[:DEFINED_IN]->(r)\n"
        "RETURN c.label, c.definition, collect({src: r.source, url: r.url, status: r.status});\n"
        "// 4. Concepts with no external citation\n"
        "MATCH (c:Concept) WHERE NOT (c)-[:DEFINED_IN]->(:Reference)\n"
        "RETURN c.id, c.label;\n"
        "// 5. Free-text entry point\n"
        "CALL db.index.fulltext.queryNodes('concept_text', 'opaque payload')\n"
        "YIELD node, score RETURN node.id, node.label, score LIMIT 5;\n"
        "// 6. Contrasts\n"
        "MATCH (a)-[r:CONTRASTS_WITH]->(b) RETURN a.label, type(r), b.label;\n"
        "// 7. Everything a file touches\n"
        "MATCH (c:Concept)-[:HAS_CODE_EVIDENCE]->(e {module: 'src/urisolver/redaction.py'})\n"
        "RETURN DISTINCT c.id, c.label;\n",
        encoding="utf-8",
    )


def _write_readme(payload: dict, snapshot: dict) -> None:
    n_concepts = len(payload["concepts"])
    n_relations = sum(len(concept["relations"]) for concept in payload["concepts"])
    n_anchors = sum(len(concept["code_evidence"]) for concept in payload["concepts"])
    n_references = sum(len(concept["references"]) for concept in payload["concepts"])
    (OUT / "README.md").write_text(
        "# urisolver concept knowledge graph\n\n"
        "Generated by `python -m urisolver.kg.build`. Do not edit files in this directory by hand.\n\n"
        f"- concepts: {n_concepts}\n"
        f"- relations: {n_relations}\n"
        f"- anchors: {n_anchors}\n"
        f"- references: {n_references}\n"
        f"- snapshot: {snapshot['commit']} dirty={str(snapshot['dirty']).lower()}\n",
        encoding="utf-8",
    )
    print(
        "neo4j:", n_concepts, "concepts,", n_anchors, "evidence,",
        n_references, "references,", n_relations, "relations",
    )


if __name__ == "__main__":
    raise SystemExit(main())
