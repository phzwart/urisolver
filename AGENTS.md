# AGENTS.md

urisolver registers a URI as a Tiled node. Workers read that node with a Tiled client and do not import urisolver. Modes, in auto order, are EXISTING, REFERENCE, PROXY, and ACQUIRE. The design is [DESIGN.md](DESIGN.md). Schemes are [SCHEMES.md](SCHEMES.md).

`import urisolver` does not import Tiled or other heavy libraries. Only `src/urisolver/tiled/_compat.py` imports Tiled internals.

The concept graph in `tools/kg/` describes the old delivery API and is stale until it is rebuilt from that tree. Do not describe binder, mode, or site behavior from the graph.
