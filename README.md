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
from urisolver.testing import run_baseline_suite, BaselineResult, ConformanceFixtures
```

`run_baseline_suite` returns a `BaselineResult` with split skip reasons
`(check_name, reason)`. With the default `raise_on_failure=True`, failures raise
`ConformanceFailure` carrying the full result so coverage and skip summaries appear
together in pytest output.

Run CI tests as a **non-root** user when possible; see [DESIGN.md §36](DESIGN.md) for
root-proof §11.2 hazard checks.

## Footnotes

- Missing local `file:` paths raise **`FileNotFoundError`** (Python stdlib), not a
  urisolver error type. This is intentional for v0.
