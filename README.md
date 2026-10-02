# urisolver

Resolve URI references into usable resources.

Given a URI, `urisolver` dispatches to the appropriate resolver plugin, guarantees a
small set of universal delivery operations (Tier 0), and exposes the underlying
protocol's native capabilities to callers who opt in (Tier 2).

## Install

```bash
pip install -e ".[dev]"
# Optional Tiled support:
pip install -e ".[tiled,dev]"
# Optional Globus Transfer support:
pip install -e ".[globus,dev]"
```

## Resolve one URI

A catalog entry names a server. The URI names an object on that server. `examples/catalog.yaml` is the example, and [examples/README.md](examples/README.md) walks through tiled, then testdrive, then globus.

```python
from urisolver import Context, FileDestination, MemoryDestination

with Context() as ctx:
    resource = ctx.resolve("file:///tmp/data.h5")
    path = resource.materialize(FileDestination("/scratch/x")).value
    data = resource.materialize(MemoryDestination()).value
```

A third-party resolver implements the contract in [DESIGN.md](DESIGN.md). Scheme pages live in [SCHEMES.md](SCHEMES.md).

## License

MIT — see [LICENSE](LICENSE).

## Design

Architecture, contracts, and scope boundaries are specified in [DESIGN.md](DESIGN.md).
Deployable URI schemes are documented in [SCHEMES.md](SCHEMES.md).

## Conformance

Third-party resolvers can check against the baseline suite:

```python
from urisolver.testing import run_baseline_suite, BaselineResult, ConformanceFixtures
```

`run_baseline_suite` returns a `BaselineResult` with split skip reasons
`(check_name, reason)`. With the default `raise_on_failure=True`, failures raise
`ConformanceFailure` carrying the full result so coverage and skip summaries appear
together in pytest output.

Run CI tests as a **non-root** user when possible; see [DESIGN.md §36](DESIGN.md) for
root-proof §11.2 hazard checks.

## Behavior notes

- Missing local `file:` paths raise **`FileNotFoundError`** (Python stdlib), not a
  urisolver error type.
