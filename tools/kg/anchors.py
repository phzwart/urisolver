"""Extract verbatim spec and code evidence for each concept anchor."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from concepts import CONCEPTS  # noqa: E402
from quotes import first_sentence, has_sentence, is_anaphoric  # noqa: E402

REPO_URL = "https://github.com/phzwart/urisolver/blob/main/"
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
# "8. Title" and "4.1 Title" both carry a section number. The dot after a
# single integer is punctuation; the dot inside "4.1" is part of the number.
_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)(?:\.\s+|\s+)(.*)$")
_LABEL_ONLY = re.compile(
    r"^(examples?|requirements?|request|response)\s*:?\s*$",
    re.IGNORECASE,
)
# Example fences are not sentences. A ```text block is the spec itself.
_SKIP_FENCE = {"python", "py", "yaml", "yml", "json", "bash", "sh", "toml"}


def repo_root() -> Path:
    return Path(subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], cwd=_HERE, text=True,
    ).strip())


def first_doc_line(node) -> str | None:
    doc = ast.get_docstring(node, clean=False)
    if not doc:
        return None
    sentence = first_sentence(doc)
    return sentence or None


def find_symbol(tree, symbol):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and node.name == symbol:
            return node
    return None


def _norm_title(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("`", "")).strip().casefold()


def _split_heading(text: str) -> tuple[str | None, str]:
    match = _NUMBER.match(text.strip())
    if match:
        return match.group(1), match.group(2).strip()
    return None, text.strip()


def _headings(lines: list[str]) -> list[tuple[int, int, str | None, str]]:
    found = []
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if not match:
            continue
        number, title = _split_heading(match.group(2))
        found.append((index, len(match.group(1)), number, title))
    return found


def _section_span(lines: list[str], key: str) -> tuple[int, int, int] | None:
    """Return (heading_index, body_start, body_end) for a unique heading key."""
    numbered = bool(re.fullmatch(r"\d+(?:\.\d+)*", key))
    want = _norm_title(key)
    hits = []
    headings = _headings(lines)
    for pos, (index, level, number, title) in enumerate(headings):
        if numbered:
            if number == key:
                hits.append(pos)
        elif _norm_title(title) == want:
            hits.append(pos)
    if len(hits) != 1:
        return None
    pos = hits[0]
    index, level, _number, _title = headings[pos]
    end = len(lines)
    for later_index, later_level, _number, _title in headings[pos + 1:]:
        if later_level <= level:
            end = later_index
            break
    return index, index + 1, end


def _paragraphs(lines: list[str], start: int, end: int) -> list[tuple[int, str]]:
    """Prose paragraphs in a section, as (first_line_1based, collapsed text)."""
    paragraphs: list[tuple[int, list[str]]] = []
    current: list[str] = []
    current_line = start + 1
    in_fence = False
    skip_fence = False

    def flush() -> None:
        nonlocal current
        if current:
            paragraphs.append((current_line, current))
        current = []

    for offset, line in enumerate(lines[start:end]):
        absolute = start + offset
        if line.startswith("```"):
            if not in_fence:
                lang = line[3:].strip().split()[0].lower() if line[3:].strip() else ""
                skip_fence = lang in _SKIP_FENCE
            in_fence = not in_fence
            flush()
            continue
        if in_fence and skip_fence:
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            continue
        if stripped.startswith("|"):
            flush()
            continue
        if stripped.startswith(">"):
            stripped = stripped[1:].lstrip()
        if not stripped:
            flush()
            continue
        if not current:
            current_line = absolute + 1
        current.append(stripped)
    flush()
    out = []
    for line_no, parts in paragraphs:
        text = re.sub(r"\s+", " ", " ".join(parts)).strip()
        if not text or _LABEL_ONLY.match(text):
            continue
        out.append((line_no, text))
    return out


def _next_sentence(paragraph: str) -> tuple[str, str] | None:
    sentence = first_sentence(paragraph)
    if not sentence:
        return None
    body = sentence[:-3].rstrip() if sentence.endswith("...") else sentence
    if not paragraph.startswith(body):
        return None
    rest = re.sub(r"^[*_`\s]+", "", paragraph[len(body):])
    return sentence, rest


def _choose(paragraphs: list[tuple[int, str]]) -> tuple[str, int] | None:
    """Prefer the first real sentence. Otherwise the first non-anaphoric line."""
    fallback: tuple[str, int] | None = None
    for line_no, paragraph in paragraphs:
        rest = paragraph
        while rest:
            source = rest
            nxt = _next_sentence(source)
            if nxt is None:
                break
            sentence, rest = nxt
            if is_anaphoric(sentence):
                if sentence.endswith("..."):
                    break
                continue
            real = has_sentence(sentence) or (sentence.endswith("...") and has_sentence(source))
            if real:
                return sentence, line_no
            if fallback is None:
                fallback = (sentence, line_no)
            break
    return fallback


def section_quote(text: str, key: str) -> tuple[str, int] | None:
    """First substantive sentence under a heading, and its 1-based line.

    The heading's own body wins over a sentence that only appears under a
    child heading.
    """
    lines = text.splitlines()
    span = _section_span(lines, key)
    if span is None:
        return None
    _heading_index, start, end = span
    child = end
    for index in range(start, end):
        if _HEADING.match(lines[index]):
            child = index
            break
    chosen = _choose(_paragraphs(lines, start, child))
    if chosen:
        return chosen
    return _choose(_paragraphs(lines, child, end))


def extract(src: Path) -> tuple[list[dict], dict[str, str], list[str]]:
    files: dict[str, dict] = {}
    out: list[dict] = []
    problems: list[str] = []
    ids = {concept["id"] for concept in CONCEPTS}
    for concept in CONCEPTS:
        for _rel, target in concept["rels"]:
            if target not in ids:
                problems.append(f"{concept['id']}: relation target {target} unknown")
        if not concept["anchors"]:
            problems.append(f"{concept['id']}: no anchors")
        for module, symbol in concept["anchors"]:
            path = src / module
            if not path.is_file():
                problems.append(f"{concept['id']}: {module} missing")
                continue
            if module not in files:
                raw = path.read_bytes()
                files[module] = {
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "text": raw.decode("utf-8"),
                }
                if module.endswith(".py"):
                    files[module]["tree"] = ast.parse(files[module]["text"])
            record = files[module]
            if module.endswith(".md"):
                found = section_quote(record["text"], symbol)
                if found is None:
                    problems.append(f"{concept['id']}: heading {symbol!r} not quoted in {module}")
                    continue
                quote, lineno = found
                kind = "section"
            elif module.endswith(".py"):
                tree = record["tree"]
                node = tree if symbol == "" else find_symbol(tree, symbol)
                if node is None:
                    problems.append(f"{concept['id']}: symbol {symbol} not in {module}")
                    continue
                quote = first_doc_line(node)
                if quote is None:
                    label = symbol or "<module>"
                    problems.append(f"{concept['id']}: {module}:{label} has no docstring")
                    continue
                if is_anaphoric(quote):
                    problems.append(f"{concept['id']}: {module}:{symbol or '<module>'} quote is anaphoric")
                    continue
                doc = ast.get_docstring(node, clean=False) or ""
                collapsed = " ".join(doc.split())
                body = quote[:-3].rstrip() if quote.endswith("...") else quote
                if not collapsed.startswith(body):
                    problems.append(f"{concept['id']}: quote is not the docstring prefix in {module}")
                    continue
                if node is tree:
                    lineno = 1
                    kind = "module"
                elif node.body and isinstance(node.body[0], ast.Expr):
                    lineno = getattr(node.body[0], "lineno", 1)
                    kind = type(node).__name__
                else:
                    lineno = getattr(node, "lineno", 1)
                    kind = type(node).__name__
            else:
                problems.append(f"{concept['id']}: anchor module {module} is not .py or .md")
                continue
            out.append({
                "concept": concept["id"],
                "module": module,
                "symbol": symbol,
                "kind": kind,
                "line": lineno,
                "exact": quote,
                "sha256": record["sha256"],
                "uri": REPO_URL + module,
            })
    digests = {module: record["sha256"] for module, record in files.items()}
    return out, digests, problems


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else repo_root()
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else _HERE / "anchors.json"
    anchors, digests, problems = extract(src)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"anchors": anchors, "files": digests}, indent=1) + "\n", encoding="utf-8")
    print(
        len(CONCEPTS), "concepts;", len(anchors), "anchors;",
        len(digests), "files;", len(problems), "problems",
    )
    for problem in problems:
        print("  -", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
