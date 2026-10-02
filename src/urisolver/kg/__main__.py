"""Query the committed concept graph.

    python -m urisolver.kg search "opaque payload"
    python -m urisolver.kg card tier_0
    python -m urisolver.kg module src/urisolver/redaction.py
    python -m urisolver.kg receipt ent:concept:tier_0
"""
from __future__ import annotations

import argparse
import json
import sys

from urisolver.kg.graph import ConceptGraph, GraphError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="urisolver.kg")
    sub = parser.add_subparsers(dest="command", required=True)
    search_p = sub.add_parser("search", help="Rank concepts by label, alias, or definition")
    search_p.add_argument("query")
    card_p = sub.add_parser("card", help="One concept with relations and evidence")
    card_p.add_argument("ident")
    module_p = sub.add_parser("module", help="Concepts anchored in a file")
    module_p.add_argument("path")
    receipt_p = sub.add_parser("receipt", help="One ledger node")
    receipt_p.add_argument("ident")
    args = parser.parse_args(argv)
    try:
        graph = ConceptGraph.load()
        if args.command == "search":
            payload = graph.search(args.query)
        elif args.command == "card":
            payload = graph.card(args.ident)
        elif args.command == "module":
            payload = graph.module(args.path)
        else:
            payload = graph.receipt(args.ident)
    except GraphError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
