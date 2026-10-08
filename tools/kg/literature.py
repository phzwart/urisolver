"""Bibliographic pointers for the two RFCs the design actually depends on.

No abstract sentence is fetched. A hit is a title and a URL only.
"""
from __future__ import annotations

RECORDS = [
    {
        "match": "RFC 3986",
        "title": "Uniform Resource Identifier (URI): Generic Syntax",
        "url": "https://www.rfc-editor.org/rfc/rfc3986",
    },
    {
        "match": "RFC 7595",
        "title": "Guidelines and Registration Procedures for URI Schemes",
        "url": "https://www.rfc-editor.org/rfc/rfc7595",
    },
]


def lookup(citation: str) -> dict:
    """Return url/title for a citation string, or an empty dict."""
    for rec in RECORDS:
        if rec["match"] in citation:
            return {"title": rec["title"], "url": rec["url"]}
    return {}
