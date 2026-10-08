"""Stdlib concept graph: payload, ledger receipts, search, neighbours.

Loads ``out/urisolver_concepts.json`` and ``out/urisolver_kg.grits.jsonld``
next to this file. ``URISOLVER_KG`` may point at another directory that holds
those two files.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"[a-z0-9]+")


class GraphError(ValueError):
    """A concept query that should become a non-zero CLI status."""

    def __init__(self, status: int, message: str, extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.extra = extra or {}


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _norm_id(text: str) -> str:
    return "_".join(_tokens(text))


def _soft_in(token: str, bag: set[str]) -> bool:
    if token in bag:
        return True
    if len(token) < 4:
        return False
    for word in bag:
        if len(word) < 4:
            continue
        if word.startswith(token) or token.startswith(word):
            return True
    return False


def default_dir() -> Path:
    env = os.environ.get("URISOLVER_KG", "").strip()
    if env:
        path = Path(env)
        if path.is_file():
            path = path.parent
        if (path / "urisolver_concepts.json").is_file():
            return path
        raise FileNotFoundError(f"URISOLVER_KG has no urisolver_concepts.json: {path}")
    here = Path(__file__).resolve().parent / "out"
    if (here / "urisolver_concepts.json").is_file():
        return here
    raise FileNotFoundError("urisolver_concepts.json not found in the kg out directory")


class ConceptGraph:
    """Payload plus an id index of the receipt ledger."""

    def __init__(self, payload: dict[str, Any], ledger: dict[str, Any] | None):
        concepts = payload.get("concepts") or []
        self.payload = payload
        self.concepts: list[dict[str, Any]] = concepts
        self.by_id: dict[str, dict[str, Any]] = {c["id"]: c for c in concepts}
        raw_snapshot = payload.get("snapshot")
        if isinstance(raw_snapshot, dict):
            self.snapshot = raw_snapshot
        else:
            self.snapshot = {
                "repository": raw_snapshot or payload.get("source_repository") or "",
                "commit": None,
                "dirty": None,
            }
        self.generated = payload.get("generated") or ""
        self.nodes: dict[str, dict[str, Any]] = {}
        if ledger:
            for node in ledger.get("@graph") or []:
                ident = node.get("@id")
                if ident:
                    self.nodes[ident] = node
        self._alias: dict[str, str] = {}
        for concept in concepts:
            cid = concept["id"]
            self._alias.setdefault(_norm_id(cid), cid)
            self._alias.setdefault(_norm_id(concept.get("label") or ""), cid)
            for alias in concept.get("aliases") or []:
                self._alias.setdefault(_norm_id(alias), cid)
        used_by: dict[str, list[str]] = {}
        for concept in concepts:
            for rel in concept.get("relations") or []:
                if rel.get("type") != "USES":
                    continue
                target = rel.get("target") or ""
                if target:
                    used_by.setdefault(target, []).append(concept["id"])
        self._used_by = used_by

    @classmethod
    def load(cls, directory: Path | None = None) -> ConceptGraph:
        root = directory or default_dir()
        payload = json.loads((root / "urisolver_concepts.json").read_text(encoding="utf-8"))
        ledger_path = root / "urisolver_kg.grits.jsonld"
        ledger = None
        if ledger_path.is_file():
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        return cls(payload, ledger)

    @property
    def n(self) -> int:
        return len(self.concepts)

    def _meta(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot,
            "generated": self.generated,
            "n_concepts": self.n,
        }

    def resolve(self, term: str) -> str | None:
        """Map an id, label, or alias to a concept id."""
        text = term.strip()
        if not text:
            return None
        if text in self.by_id:
            return text
        return self._alias.get(_norm_id(text))

    def _bags(self, concept: dict[str, Any]) -> tuple[set[str], set[str]]:
        label_bag = set(_tokens(concept["id"].replace("_", " ")))
        label_bag |= set(_tokens(concept.get("label") or ""))
        for alias in concept.get("aliases") or []:
            label_bag |= set(_tokens(alias))
        definition = set(_tokens(concept.get("definition") or ""))
        return label_bag, definition

    def search(self, query: str, limit: int = 8) -> dict[str, Any]:
        qtokens = _tokens(query)
        if not qtokens:
            raise GraphError(400, "q is empty")
        qnorm = " ".join(qtokens)
        qid = "_".join(qtokens)
        hits: list[dict[str, Any]] = []
        for concept in self.concepts:
            cid = concept["id"]
            label_norm = " ".join(_tokens(concept.get("label") or ""))
            aliases = [" ".join(_tokens(a)) for a in concept.get("aliases") or []]
            if qid == cid or qnorm == cid.replace("_", " "):
                score = 100
            elif qnorm == label_norm:
                score = 90
            elif qnorm in aliases:
                score = 85
            else:
                label_bag, definition = self._bags(concept)
                label_hits = sum(1 for token in qtokens if _soft_in(token, label_bag))
                def_hits = sum(1 for token in qtokens if _soft_in(token, definition))
                if label_hits == 0 and def_hits == 0:
                    continue
                score = 10 * label_hits + 2 * def_hits
                if label_hits == len(qtokens):
                    score += 20
            hits.append({
                "id": cid,
                "label": concept.get("label") or cid,
                "kind": concept.get("kind"),
                "score": score,
                "definition": concept.get("definition") or "",
            })
        hits.sort(key=lambda row: (-row["score"], row["id"]))
        return {**self._meta(), "query": query, "hits": hits[:limit]}

    def _require(self, ident: str) -> tuple[str, dict[str, Any]]:
        concept = self.by_id.get(ident.strip()) or self.by_id.get(_norm_id(ident))
        if concept is None:
            resolved = self.resolve(ident)
            concept = self.by_id.get(resolved) if resolved else None
        if concept is None:
            raise GraphError(
                404,
                f"unknown concept id {ident!r}",
                {"hint": "search labels and aliases"},
            )
        return concept["id"], concept

    def _evidence(self, cid: str, concept: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for index, anchor in enumerate(concept.get("code_evidence") or []):
            rows.append({
                "module": anchor.get("module") or "",
                "symbol": anchor.get("symbol") or "",
                "kind": anchor.get("kind") or "",
                "line": anchor.get("line"),
                "quote": anchor.get("quote") or "",
                "uri": anchor.get("uri") or "",
                "sha256": anchor.get("sha256") or "",
                "receipt": f"evi:code:{cid}:{index}",
            })
        return rows

    def _references(self, cid: str, concept: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        lit_n = 0
        for ref in concept.get("references") or []:
            source = ref.get("source") or ""
            if source == "literature":
                lit_n += 1
                receipt = f"evi:lit:{cid}:{lit_n}"
            else:
                receipt = f"evi:ref:{cid}:{source}"
            rows.append({
                "source": source,
                "title": ref.get("title") or "",
                "url": ref.get("url") or "",
                "status": ref.get("status") or "",
                "quote": ref.get("quote") or "",
                "doi": ref.get("doi") or "",
                "receipt": receipt,
            })
        return rows

    def _relations(self, cid: str, concept: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for rel in concept.get("relations") or []:
            target = rel.get("target") or ""
            kind = rel.get("type") or ""
            other = self.by_id.get(target)
            rows.append({
                "type": kind,
                "target": target,
                "target_label": (other or {}).get("label") or "",
                "receipt": f"ent:rel:{cid}:{kind}:{target}",
            })
        return rows

    def card(self, ident: str) -> dict[str, Any]:
        cid, concept = self._require(ident)
        return {
            **self._meta(),
            "id": cid,
            "label": concept.get("label") or cid,
            "kind": concept.get("kind"),
            "aliases": list(concept.get("aliases") or []),
            "definition": concept.get("definition") or "",
            "definition_receipt": f"ent:concept:{cid}",
            "literature": list(concept.get("literature") or []),
            "relations": self._relations(cid, concept),
            "code_evidence": self._evidence(cid, concept),
            "references": self._references(cid, concept),
            "note": (
                "definition is a builder paraphrase (definition_receipt). "
                "references[].status citation is a bibliographic pointer without "
                "a fetched sentence. code_evidence sha256 values are the snapshot, "
                "not a later edit."
            ),
        }

    def neighbors(self, ident: str, relation: str | None = None, depth: int = 1) -> dict[str, Any]:
        """Concepts reachable by outgoing relations, optionally one relation type."""
        cid, concept = self._require(ident)
        want = (relation or "").strip().upper() or None
        seen: dict[str, tuple[int, str]] = {}
        frontier = [cid]
        for step in range(1, depth + 1):
            nxt: list[str] = []
            for node in frontier:
                for rel in self.by_id[node].get("relations") or []:
                    kind = rel.get("type") or ""
                    target = rel.get("target") or ""
                    if want and kind != want:
                        continue
                    if not target or target == cid or target in seen or target not in self.by_id:
                        continue
                    seen[target] = (step, kind)
                    nxt.append(target)
            frontier = nxt
        rows = [
            {
                "id": target,
                "label": self.by_id[target].get("label") or target,
                "relation": seen[target][1],
                "depth": seen[target][0],
                "definition": self.by_id[target].get("definition") or "",
            }
            for target in seen
        ]
        rows.sort(key=lambda row: (row["depth"], row["relation"], row["id"]))
        return {
            **self._meta(),
            "id": cid,
            "label": concept.get("label") or cid,
            "relation": want or "",
            "depth": depth,
            "neighbors": rows,
        }

    def _walk(self, ident: str, depth: int, *, reverse: bool) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        concept_id, concept = self._require(ident)
        cid = concept_id
        seen: dict[str, int] = {}
        frontier = [cid]
        for step in range(1, depth + 1):
            nxt: list[str] = []
            for node in frontier:
                if reverse:
                    neighbours = self._used_by.get(node) or []
                else:
                    neighbours = [
                        rel.get("target") or ""
                        for rel in self.by_id[node].get("relations") or []
                        if rel.get("type") == "USES"
                    ]
                for target in neighbours:
                    if target == cid or target in seen or target not in self.by_id:
                        continue
                    seen[target] = step
                    nxt.append(target)
            frontier = nxt
        rows = [
            {
                "id": target,
                "label": self.by_id[target].get("label") or target,
                "depth": seen[target],
                "definition": self.by_id[target].get("definition") or "",
            }
            for target in seen
        ]
        rows.sort(key=lambda row: (row["depth"], row["id"]))
        return concept, cid, rows

    def uses(self, ident: str, depth: int) -> dict[str, Any]:
        concept, cid, rows = self._walk(ident, depth, reverse=False)
        return {**self._meta(), "id": cid, "label": concept.get("label") or cid, "depth": depth, "uses": rows}

    def used_by(self, ident: str, depth: int) -> dict[str, Any]:
        concept, cid, rows = self._walk(ident, depth, reverse=True)
        return {**self._meta(), "id": cid, "label": concept.get("label") or cid, "depth": depth, "used_by": rows}

    def module(self, name: str) -> dict[str, Any]:
        query = name.strip().replace("\\", "/").lstrip("./")
        if not query:
            raise GraphError(400, "module is required")
        found: list[dict[str, Any]] = []
        for concept in self.concepts:
            anchors = [
                anchor for anchor in self._evidence(concept["id"], concept)
                if _module_match(anchor["module"], query)
            ]
            if not anchors:
                continue
            found.append({
                "id": concept["id"],
                "label": concept.get("label") or concept["id"],
                "anchors": anchors,
            })
        if not found:
            raise GraphError(
                404,
                f"no concept is anchored in {query!r}",
                {"hint": "use a path like src/urisolver/redaction.py or DESIGN.md"},
            )
        found.sort(key=lambda row: row["id"])
        return {**self._meta(), "module": query, "concepts": found}

    def receipt(self, ident: str) -> dict[str, Any]:
        key = ident.strip()
        if not key:
            raise GraphError(400, "id is required")
        node = self.nodes.get(key)
        if node is None:
            raise GraphError(
                404,
                f"unknown receipt {key!r}",
                {"hint": "pass definition_receipt, relations[].receipt, or code_evidence[].receipt"},
            )
        return {
            **self._meta(),
            "receipt": key,
            "node": node,
            "note": (
                "Ledger node. how=quote is a verbatim sentence with source.sha256. "
                "how=derived is a builder paraphrase or a bibliographic pointer. "
                "how=inferred is a builder relation."
            ),
        }


def _module_match(stored: str, query: str) -> bool:
    path = stored.replace("\\", "/").lstrip("./")
    if path == query or path.endswith("/" + query):
        return True
    if "/" not in query and path.rsplit("/", 1)[-1] == query:
        return True
    return False
