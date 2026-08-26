# urisolver

Resolve URI references into usable resources.

Given a URI, `urisolver` dispatches to the appropriate resolver plugin, guarantees a
small set of universal delivery operations (Tier 0), and exposes the underlying
protocol's native capabilities to callers who opt in (Tier 2).

```python
from urisolver import Context, FileDestination, MemoryDestination

with Context() as ctx:
    resource = ctx.resolve("file:///tmp/data.h5")
    path = resource.materialize(FileDestination("/scratch/x")).value
    data = resource.materialize(MemoryDestination()).value
```

## Install

```bash
pip install -e ".[dev]"
# Optional Tiled support:
pip install -e ".[tiled,dev]"
```

## License

MIT — see [LICENSE](LICENSE).

## Design

v0 is frozen in [DESIGN.md](DESIGN.md). That document is the authority; this package
implements it without architectural additions.

## Conformance

Every resolver must pass the baseline suite:

```python
from urisolver.testing.baseline import run_baseline_suite
```
