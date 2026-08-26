# `urisolver` — v0 Design Specification (revision 3 — frozen for v0)

This file is the in-tree authority for v0. It freezes revision 3 of the design
contract. Public names in the implementation match the names in this document.

## 1. Purpose

`urisolver` resolves URI references into usable resources.

> Given a URI, resolve it through the appropriate resolver; guarantee a small set of
> universal delivery operations; expose the underlying protocol's native capabilities to
> callers who want them.

It is **not** a workflow engine, provenance system, scientific metadata framework,
universal data API, generalized filesystem, transfer planner, or replacement for
Tiled / Globus / S3 / HDF5 / Zarr.

## 2. Three tiers

```text
Tier 0   Baseline contract     MUST be implemented by every resolver.
                               Protocol-agnostic. Never requires the caller
                               to know the backend.

Tier 1   Facets                Small, optional, declared protocols
                               (stream / array / table / container).

Tier 2   Native pass-through   Everything the protocol genuinely provides.
                               Caller opts in and accepts protocol coupling.
```

Guiding rule: ordinary things work identically everywhere; extraordinary things
are not flattened into a lowest common denominator.

## 3. Public API (headline)

```python
from urisolver import Context, FileDestination, MemoryDestination

with Context() as ctx:
    resource = ctx.resolve("file:///tmp/data.h5")
    path = resource.materialize(FileDestination("/scratch/x")).value
    data = resource.materialize(MemoryDestination()).value
```

Module-level `resolve()` uses a lazy default context. Library code must accept an
explicit context. `close_default_context()` is idempotent.

## 4. Tier 0 baseline

Universally **present** on every `ResolvedResource` (never hidden by policy):

- `info() -> ResourceInfo`
- `materialize(MemoryDestination(form=NATIVE))`

Additionally for `Kind` in `{FILE, OPAQUE, ARRAY, TABLE}` when
`canonical_media_type` is declared:

- `materialize(FileDestination(...))`
- `materialize(MemoryDestination(form=BYTES))`

`Kind.CONTAINER`: `MemoryDestination(NATIVE)` returns a mapping of child name →
`ResolvedResource`. File/BYTES for containers require a declared serialization.

Byte-level delivery uses the resolver-declared `canonical_media_type` (established
formats only). Unsupported requested media types raise; they are never substituted.

Selection at Tier 0: numpy basic indexing for arrays; column sequences for tables;
anything else via `Native(...)`.

Presence is not entitlement: Tier 0 may raise `AuthorizationError` or
`ResourceUnavailableError` at call time. Resolvers must not probe read authorization
eagerly on `resolve()`.

## 5. MaterializedResult honesty

Results carry `source_uri`, `resolved_uri`, `form`, `media_type`, `is_reference`,
`strategy`, and `warnings`. Strategies include `native`, `native-selection`,
`read-then-select`, `reference`, `converted`. `Context(strict_efficiency=True)`
turns `read-then-select` into `InefficientOperationError`.

File destinations write via temp + `os.replace`. Reference policies
(`COPY` / `HARDLINK` / `SYMLINK` / `IN_PLACE`) never delete caller-owned paths on
failure when `is_reference=True`.

## 6. Facets and native

Facets: `stream`, `array`, `table`, `container` — adopted interfaces only.
`supports` / `capabilities` / `hasattr` agree. Policy filtering is intent signalling,
not a security boundary; filtered resolvers deny `native` with `NativeAccessDenied`.

## 7. Plugins, namespaces, secrets

Entry points: `urisolver.resolvers` (eager enumerate, lazy import), plus groups for
namespaces, secrets, codecs. Namespace `POST /resolve` with TTL cache keyed by
`(namespace, identifier, principal)`. Opaque URI payloads are secrets in logs/repr.

## 8. Implementation directive (§35)

Do **not** add without a written amendment:

- capability enum/ontology
- SliceSpec / Query / Filter / Predicate types
- a fifth facet, sixth Kind, or additional Form
- metadata / schema / provenance models
- core-level retry / cache / connection-pool above the resolver
- a required resolver base class
- convenience APIs that hide which tier a call lands in
- async beyond reserved `aresolve` / `amaterialize` names

Prefer thirty duplicated lines across two resolvers over a premature core
abstraction. If a requirement looks wrong or two sections conflict: stop and report.

## 9. Done criteria

v0 is done when `urisolver.testing.baseline` passes for `file:` and Tiled, and a
third-party resolver can be written against this document alone.
