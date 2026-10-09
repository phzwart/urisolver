"""Sentence checks for concept-graph evidence."""
from __future__ import annotations

import re

# A sentence boundary sits after a letter, digit, closing bracket, backtick, or
# emphasis marker, and before whitespace or a closing emphasis marker.
_BEFORE_PERIOD = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789)]}`*_")
_AFTER_MARK = set("*_")
_ANAPHORA = re.compile(
    r"^(in the second case|in this case|it|this|these)\b",
    re.IGNORECASE,
)


def _plain_start(sentence: str) -> str:
    return re.sub(r"^[*_`>\s]+", "", (sentence or "").strip())


def is_anaphoric(sentence: str) -> bool:
    return bool(_ANAPHORA.match(_plain_start(sentence)))


def has_sentence(text: str) -> bool:
    """True when *text* contains a period, question mark, or exclamation that ends a sentence."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    return _sentence_end(flat) is not None


def _sentence_end(flat: str) -> int | None:
    """Index just past the period that ends the sentence, or None.

    A period inside a double-backtick span is not a boundary. Outside one,
    the period must follow a letter, digit, closing bracket, or backtick,
    and must be followed by whitespace or the end of the text.
    """
    i = 0
    n = len(flat)
    in_code = False
    while i < n:
        if flat.startswith("``", i):
            in_code = not in_code
            i += 2
            continue
        if (
            not in_code
            and flat[i] in ".?!"
            and i > 0
            and flat[i - 1] in _BEFORE_PERIOD
            and (i + 1 == n or flat[i + 1].isspace() or flat[i + 1] in _AFTER_MARK)
        ):
            return i + 1
        i += 1
    return None


def first_sentence(doc: str, limit: int = 200) -> str:
    """First sentence, joining wrapped lines with one space.

    Stops at the first blank line or at the first period that ends a sentence,
    whichever comes first. Periods inside ``double backticks`` are not
    boundaries. Adds an ellipsis only when the sentence is cut to ``limit``.
    """
    if not doc or not doc.strip():
        return ""
    head = re.split(r"\n\s*\n", doc, maxsplit=1)[0]
    flat = re.sub(r"\s+", " ", head).strip()
    end = _sentence_end(flat)
    if end is not None:
        while end < len(flat) and flat[end] in "*_":
            end += 1
    sentence = flat[:end].strip() if end else flat
    if len(sentence) <= limit:
        return sentence
    cut = sentence[: limit - 3].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0].rstrip()
    return cut + "..."
