# AGENTS.md

urisolver registers a URI as a Tiled node. Workers read that node with a Tiled client and do not import urisolver. Modes, in auto order, are EXISTING, REFERENCE, PROXY, and ACQUIRE. The design is [DESIGN.md](DESIGN.md). Schemes are [SCHEMES.md](SCHEMES.md).

`import urisolver` does not import Tiled or other heavy libraries. `src/urisolver/tiled/_compat.py` imports Tiled internals (`tiled.adapters.utils`, `tiled.client.register`, `tiled.utils`, `tiled.mimetypes`, and `tiled.ndslice`). `src/urisolver/tiled_server/proxy.py` imports `tiled.adapters.core` and `tiled.structures` when a Tiled server loads the proxy adapters.

The concept graph in `tools/kg/` describes this tree. Query it with `PYTHONPATH=tools python -m kg`.
