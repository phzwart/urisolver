# AGENTS.md

The concept graph now lives in `tools/kg/` and is stale until it is rebuilt from
that tree. Do not describe binder, mode, or site behavior from the graph.

`import urisolver` does not import Tiled or other heavy libraries. Binders run
at registration time; workers read through a Tiled client and do not import
urisolver.
