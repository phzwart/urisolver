# `urisolver` — v0 Design Specification (revision 3 — frozen for v0)

## 0. What changed in this revision

The previous draft made **native pass-through the only access path** and `materialize()` the
only universal operation, with its semantics left almost entirely to the resolver. The
consequence was that a caller who wanted nothing more than *"give me this as a file"* or
*"give me this in memory"* still had to know whether the URI was Tiled, Globus, S3 or a
local path — because nothing about the delivered result was contractual.

This revision inverts that. `urisolver` now defines **three tiers**:

```text
Tier 0   Baseline contract     MUST be implemented by every resolver.
                               Protocol-agnostic. Never requires the caller
                               to know the backend.

Tier 1   Facets                Small, optional, declared protocols borrowed
                               from existing de-facto standards (bytes,
                               array, table, container). Generic code may
                               use them after checking.

Tier 2   Native pass-through   Everything the protocol genuinely provides.
                               Caller opts in and accepts protocol coupling.
```

The guiding rule is now:

> **Ordinary things must work identically everywhere. Extraordinary things must not be
> flattened into a lowest common denominator.**

Other substantive changes: `MaterializedResult` is fully specified; copy-vs-reference is
explicit; overwrite policy has an API; policy filtering is described as intent signalling
rather than as a security boundary; there is one authoritative capability mechanism;
`ResolveContext` owns session lifetime and is a context manager; namespace resolutions
carry TTL and a richer status set; opaque URI payloads are treated as secrets.

**Revision 3** makes three corrections and freezes the document:

1. Universal `BYTES` materialization is relaxed for structured resources. Byte-level
   delivery now depends on a resolver-declared `canonical_media_type` rather than
   obliging every resolver to invent a serialization (§8.1, §9).
2. The reason numpy basic indexing sits at Tier 0 — and why nothing else may join it —
   is now stated rather than assumed (§13.1).
3. Tier 0 operations are universally **present** but may fail at call time with
   `AuthorizationError` or `ResourceUnavailableError`. Resolution establishes
   addressability, not entitlement; resolvers must not probe read authorization eagerly
   to force early failure (§16.1, §25).

§35 adds an implementation directive constraining what may be added during the build.

---

## 1. Purpose

`urisolver` resolves URI references into usable resources.

> **Given a URI, resolve it through the appropriate resolver; guarantee a small set of
> universal delivery operations; expose the underlying protocol's native capabilities to
> callers who want them.**

It is not:

```text
a workflow engine
a provenance system
a scientific metadata framework
a universal data API
a generalized filesystem
a transfer planner
a replacement for Tiled, Globus, S3, HDF5, Zarr, etc.
```

Architecture:

```text
URI
 ↓
scheme dispatch
 ↓
resolver plugin  (+ optional namespace indirection)
 ↓
native backend object
 ↓
ResolvedResource
 ├── Tier 0  baseline: info(), materialize(File|Memory), selection
 ├── Tier 1  facets:   stream / array / table / container
 └── Tier 2  native:   whatever the protocol provides
```

---

## 2. Core responsibilities

`urisolver-core` owns:

```text
URI scheme dispatch
resolver plugin discovery and lifecycle
namespace delegation
runtime context and session ownership
secrets-provider interfaces
the Tier 0 baseline contract and its result types
facet protocol definitions (definitions only, not implementations)
destination abstractions
capability declaration and policy plumbing
error model and redaction rules
```

Everything backend-specific belongs to resolver plugins.

---

## 3. Core non-responsibilities

The core must not define its own universal versions of:

```text
query / search syntax
backend indexing
backend selection grammar beyond §13
streaming semantics beyond the stream facet
metadata schemas
a capability ontology
```

where those concepts are already defined by the underlying protocol. Tier 1 facets are the
deliberate, bounded exception: each facet adopts an interface that already exists in the
ecosystem rather than inventing one (see §14).

---

## 4. URI model

Examples:

```text
file:///data/run001/image_001.tif
tiled-nslsii://catalog/run/12345
tiled-ssrl://experiments/abc/data
lbl-mbib:8dd49e18-2938-4ee2-a117
private:v1:OPAQUE_PAYLOAD
```

The core extracts **only** the scheme. The resolver receives the complete original URI
unchanged. All of these are valid from the core's perspective:

```text
foo:abc
foo://abc/def
foo:ENCRYPTED_PAYLOAD
foo://SIGNED_OR_OPAQUE_PAYLOAD
```

Do not impose filesystem-like parsing on arbitrary schemes.

### 4.1 Opaque payloads are secrets

A resolver or namespace declares whether its payload is opaque:

```python
class Resolver(Protocol):
    opaque_payload: bool = False
```

When `opaque_payload` is true, the core and all plugins must use a redacted rendering of
the URI in every log record, exception message, `__repr__`, and temporary path:

```text
private:v1:AF31DD91...  →  private:<sha256:9f2c1ab04e7d>
```

The scheme may always appear in the clear (it is needed to diagnose
`UnknownSchemeError`). The payload may not. See §24.

### 4.2 Scheme naming

Scheme names are private to a deployment unless registered with IANA. Use a
vendor-prefixed form (`tiled-nslsii`, `lbl-mbib`) rather than a generic word. The core
must not bless a generic scheme such as `local:`; the local namespace prefix is
configuration (§21.3).

---

## 5. Public API

The context is primary; the module-level function is sugar.

```python
from urisolver import Context, FileDestination, MemoryDestination

with Context(secrets=OpenBaoSecretsProvider(...)) as ctx:
    resource = ctx.resolve("tiled-nslsii://catalog/run/12345")
    array = resource.materialize(MemoryDestination()).value
```

```python
from urisolver import resolve          # uses a lazily created default Context
resource = resolve("file:///tmp/data.h5")
```

`resolve()` establishes access. It does **not** transfer, download, or convert.

The default context is a documented convenience with real hazards: it holds a secrets
provider and live backend sessions for the lifetime of the process. Library code must
accept an explicit context; only application entry points should rely on the default.
`urisolver.close_default_context()` must exist and must be idempotent.

---

## 6. `ResolvedResource`

```python
class ResolvedResource(Protocol):

    @property
    def uri(self) -> str: ...                 # as requested by the caller
    @property
    def resolved_uri(self) -> str: ...        # after namespace indirection; == uri if none
    @property
    def protocol(self) -> str: ...

    # ---- Tier 0: baseline, always present -------------------------------
    def info(self) -> "ResourceInfo": ...
    def materialize(
        self,
        destination: "Destination",
        *,
        selection: "Selection | None" = None,
        **kwargs,
    ) -> "MaterializedResult": ...

    # ---- Tier 1: facets, declared ---------------------------------------
    def facets(self) -> frozenset[str]: ...
    def facet(self, name: str) -> object: ...

    # ---- Tier 2: native, declared ---------------------------------------
    def supports(self, name: str) -> bool: ...
    def capabilities(self) -> frozenset[str]: ...
    @property
    def native(self) -> object: ...           # may raise NativeAccessDenied
```

A `ResolvedResource` may hold an open session. It is bound to the `Context` that produced
it and becomes invalid when that context closes.

### 6.1 Serialization

`ResolvedResource` is **not** picklable and must raise a clear `TypeError` explaining why.
The serializable artefact is the URI. Distributed code (Dask, MPI ranks, batch workers)
must ship the URI and re-resolve inside the worker against a worker-local context;
resolvers are expected to make repeat resolution cheap through session reuse (§23).

---

## 7. `ResourceInfo`

Cheap, best-effort description obtained during or shortly after resolution.

```python
class Kind(str, Enum):
    FILE      = "file"        # an opaque byte payload with a location
    ARRAY     = "array"
    TABLE     = "table"
    CONTAINER = "container"   # has named children
    OPAQUE    = "opaque"      # resolvable, but nothing further is claimed

@dataclass(frozen=True)
class ResourceInfo:
    uri: str
    resolved_uri: str
    protocol: str
    kind: Kind
    exists: bool
    media_type: str | None = None
    size_bytes: int | None = None       # None == unknown, not zero
    shape: tuple[int, ...] | None = None
    dtype: str | None = None                    # numpy-style string where meaningful
    canonical_media_type: str | None = None     # byte-level serialization, §8.1
    label: str | None = None
```

`Kind` is a closed five-value enum and is the only classification the core defines. Its
sole purpose is to let generic code decide which facet to ask for. It is not a metadata
model and must not grow domain semantics.

`info()` must not transfer bulk data. If a backend cannot answer a field cheaply, the
field is `None`.

---

## 8. Tier 0 — the baseline contract

Tier 0 operations are **universally present**. Every `ResolvedResource` has them, no
policy may hide them, and `supports()` and `hasattr()` are always true for them. Presence
is structural. It is not a promise that a given call will succeed — see §16.1.

Required for every resource a resolver returns, regardless of `Kind`:

```text
info()
materialize(MemoryDestination(form=NATIVE))
```

Additionally required for `Kind` in `{FILE, OPAQUE, ARRAY, TABLE}`:

```text
materialize(FileDestination(...))
materialize(MemoryDestination(form=BYTES))
```

both using the resource's declared `canonical_media_type` (§8.1). `Kind.CONTAINER` is
exempt from the byte-level requirements (§12.4).

This is the whole point of the package: for any non-container URI, from any resolver, the
following works without the caller knowing the protocol.

```python
path  = resolve(any_uri).materialize(FileDestination("/scratch/x")).value
data  = resolve(any_uri).materialize(MemoryDestination()).value
raw   = resolve(any_uri).materialize(MemoryDestination(form=Form.BYTES)).value
```

### 8.1 Canonical encoding

A byte-level representation of a structured resource requires choosing a serialization,
and the core must not choose one on the resolver's behalf — that would be exactly the
invented semantics §3 forbids. The resolver declares it instead, per resource, in
`ResourceInfo.canonical_media_type`:

```text
file:            the file's own bytes, media type by content or extension
opaque payload:  application/octet-stream
Tiled array:     application/x-hdf5  or  application/x-npy
Tiled table:     application/vnd.apache.parquet  or  application/vnd.apache.arrow.file
```

Rules:

```text
the declared format MUST be an established, independently readable format; a
    resolver may NOT invent a private encoding to satisfy Tier 0
the same declared format MUST serve both FileDestination and
    MemoryDestination(BYTES), and MUST appear in MaterializedResult.media_type
a caller may request a specific encoding — FileDestination(media_type=...) or
    MemoryDestination(form=BYTES, media_type=...) — and an unsupported request
    raises UnsupportedFormError; it is never silently substituted
canonical_media_type is None for Kind.CONTAINER, and MAY be None for a resource
    whose resolver has no defensible serialization; the byte-level requirements
    then lift and MemoryDestination(NATIVE) remains the guaranteed path
```

A resolver declaring `canonical_media_type = None` for a non-container resource must
document why, because it is opting out of the portable-file guarantee that motivates the
package.

Plugin-defined destinations (`GlobusDestination`, `S3Destination`) remain optional and may
raise `UnsupportedDestinationError`.

---

## 9. Forms

A form is *what the caller wants back*, independent of protocol.

```python
class Form(str, Enum):
    NATIVE = "native"   # backend-appropriate object      (mandatory)
    BYTES  = "bytes"    # bytes / memoryview              (mandatory)
    ARRAY  = "array"    # numpy-compatible ndarray        (optional)
    TABLE  = "table"    # Arrow table / dataframe         (optional)
    PATH   = "path"     # implied by FileDestination
```

- `NATIVE` is the default for `MemoryDestination` and is the one form allowed to vary by
  backend: ndarray, Arrow table, xarray object, `bytes`. Never coerce a backend-native
  array into `bytes` merely for uniformity.
- `BYTES` is the portable floor wherever a byte-level representation is well defined:
  mandatory for `Kind` in `{FILE, OPAQUE, ARRAY, TABLE}` with a declared
  `canonical_media_type`, and raising `UnsupportedFormError` otherwise (§8.1). The
  encoding actually used is always reported in `MaterializedResult.media_type`.
- `ARRAY` and `TABLE` are optional and raise `UnsupportedFormError` when unavailable.
  Generic code should check `Kind` or facets first rather than catching.

---

## 10. `MaterializedResult`

```python
@dataclass(frozen=True)
class MaterializedResult:
    value: object                    # Path for file dests; object for memory dests
    source_uri: str                  # URI as requested (redacted rendering in repr)
    resolved_uri: str                # concrete URI actually used
    protocol: str
    destination: "Destination"
    form: Form
    media_type: str | None
    size_bytes: int | None
    selection: "Selection | None"
    is_reference: bool               # see §11.2 — value is NOT owned by the caller
    strategy: str                    # see §10.1
    warnings: tuple[str, ...] = ()
```

`__repr__` must use redacted URIs (§4.1) and must never include `value` for memory results.

Carrying `source_uri` / `resolved_uri` on the result is deliberate: it is the seam that
lets an external provenance or metadata layer record where a staged file came from without
any such awareness in the core (§28).

### 10.1 `strategy` — honesty about efficiency

`strategy` is a short machine-readable token describing how the result was produced:

```text
"native"            backend delivered exactly what was asked
"native-selection"  backend performed the selection server-side
"read-then-select"  full object was retrieved and sliced locally
"reference"         no copy was made (see §11.2)
"converted"         retrieved natively then converted to the requested form
```

`"read-then-select"` must also append a human-readable entry to `warnings`.

`Context(strict_efficiency=True)` turns any `"read-then-select"` into an
`InefficientOperationError` before the transfer starts. Default is `False`: the ordinary
caller gets the right answer automatically, and the caller who cares about not pulling a
terabyte can opt into strictness. This replaces the previous draft's prohibition, which
forbade the fallback without providing a portable alternative.

---

## 11. `FileDestination`

```python
@dataclass(frozen=True)
class FileDestination:
    path: os.PathLike | str
    overwrite: bool = False
    make_parents: bool = True
    mode: int | None = None
    reference: "ReferencePolicy" = ReferencePolicy.COPY
    media_type: str | None = None    # None → resource's canonical_media_type (§8.1)
```

```python
class ReferencePolicy(str, Enum):
    COPY     = "copy"        # always produce an independent copy (default)
    HARDLINK = "hardlink"    # hardlink when same filesystem, else copy
    SYMLINK  = "symlink"     # symlink when local, else copy
    IN_PLACE = "in_place"    # may return the source path itself
```

### 11.1 Correctness requirements

```text
the returned path must exist when success is returned
writes go to a unique temporary name in the destination directory,
    then are finalized atomically (os.replace)
temporary names must not collide across concurrent materializations
overwrite=False must fail with FileExistsError before any transfer begins
partial output must never be presented as success
```

### 11.2 Cleanup and `is_reference`

Failure cleanup removes the temporary artefact only. **Cleanup must never remove a path
the caller did not cause to be created.** When `reference` is `IN_PLACE` or `SYMLINK` and
the resolver returns or links the original source, the result carries
`is_reference=True`, and:

```text
no cleanup is performed on that path under any circumstance
the caller must not mutate or delete result.value
overwrite semantics do not apply
```

This resolves the contradiction in the previous draft between "avoid unnecessary copying"
and "failures should clean up incomplete data", which together could delete a user's
source data.

The default is `COPY`. A resolver may only return a reference when the caller asked for
one.

---

## 12. `MemoryDestination`

```python
@dataclass(frozen=True)
class MemoryDestination:
    form: Form = Form.NATIVE
    max_bytes: int | None = None     # None → context default
```

Requirements:

```text
partial failure must not appear successful
if size is known and exceeds max_bytes, fail before transfer with MemoryLimitError
if size is unknown, the resolver should enforce the limit during transfer where it can
the NATIVE representation remains backend-appropriate
```

The context supplies a default `max_bytes`; `Context(memory_limit=None)` disables it.

### 12.4 Containers

For `Kind.CONTAINER`:

```text
materialize(MemoryDestination())      → a Mapping of child name → ResolvedResource
                                        (lazy; children are not materialized)
materialize(FileDestination(path))    → v0: raises UnsupportedDestinationError
                                        unless the resolver declares a single-file
                                        serialization of the container (e.g. Tiled
                                        node → HDF5) via canonical_media_type,
                                        in which case §8.1 applies unchanged
materialize(MemoryDestination(BYTES)) → same condition
```

Directory destinations and recursive export are out of scope for v0 and are the obvious
first post-v0 extension.

---

## 13. Selection

Selection is portable at Tier 0 for one narrow, already-standard case.

```python
Selection = Union[
    int, slice, EllipsisType, tuple,      # numpy basic indexing
    Sequence[str],                        # column subset, for Kind.TABLE
    "Native",                             # opaque pass-through wrapper
]
```

- **numpy basic indexing** is adopted, not invented. Tiled, h5py, zarr, xarray and numpy
  already accept it. A resolver whose resource is `Kind.ARRAY` must accept it and should
  push it to the backend (`strategy="native-selection"`); if it cannot, it falls back to
  `"read-then-select"` (§10.1).
- **Column sequences** apply to `Kind.TABLE`.
- **Anything else** must be wrapped so intent is unambiguous:

```python
from urisolver import Native
resource.materialize(MemoryDestination(), selection=Native(some_tiled_query))
```

`Native(...)` is handed to the resolver untouched and is a declaration by the caller that
they have accepted protocol coupling.

The core defines no query language, no filter grammar, and no `SliceSpec` type.

### 13.1 Why basic indexing is Tier 0, and why nothing else may join it

This is the only place in the document where the core adopts an access semantics instead
of deferring to the protocol. The reason belongs on the record, both to justify it and to
bound it.

**It is not an invention.** Basic indexing is already the shared vocabulary of numpy,
h5py, zarr, xarray, Dask and Tiled. The core defines it by reference to numpy's rules and
adds nothing of its own. Nobody has to learn, implement, or disagree about a new concept.

**Without it, Tier 0 is a bulk-only promise.** The only portable way to obtain part of a
resource would be to obtain all of it. At facility scale that turns "protocol-agnostic
access" into "protocol-agnostic full download" — which is precisely why the previous
revision tried to forbid the fallback, and precisely why protocol knowledge kept leaking
back into the caller. `shape` and `dtype` from `ResourceInfo` plus basic indexing is the
smallest interface that lets generic code decide *what to fetch* before fetching it.

**It is closed.** Basic indexing is a fixed, finite, decades-stable specification. It
cannot grow into a query language, which is exactly what makes it safe here. Fancy
indexing, boolean masks, label-based selection, predicates, joins, and anything resembling
a where-clause fall outside it by construction and travel through `Native(...)`. This
property — not usefulness — is the admission test for Tier 0. Nothing else in sight passes
it.

**Not supporting it server-side is not disqualifying.** A resolver that cannot push the
selection down falls back to `read-then-select` and says so (§10.1). No resolver is
blocked from conformance by lacking backend selection, so the requirement costs
implementers nothing.

**The counterfactual is worse.** If the core omits it, every generic tool built over
`urisolver` reimplements the same slicing on top of full materialization — separately,
unreviewably, and usually with the whole-object fetch left in. The parallel abstraction
appears either way. The only question is whether it exists once, inside, where it can be
pushed down to the backend.

---

## 14. Tier 1 — facets

A facet is a small, optional, *declared* protocol. Each facet adopts an interface that
already exists rather than inventing one. Facets exist so that generic code can do
slightly more than "fetch the whole thing" without knowing the backend.

```python
if "stream" in resource.facets():
    with resource.facet("stream").open() as fh:
        header = fh.read(4096)
```

v0 defines exactly four:

### 14.1 `stream`

```python
class StreamFacet(Protocol):
    def open(self, mode: Literal["rb"] = "rb") -> IO[bytes]: ...
    def readable_ranges(self) -> bool: ...      # HTTP Range / seekable file
```

### 14.2 `array`

```python
class ArrayFacet(Protocol):
    shape: tuple[int, ...]
    dtype: str
    chunks: tuple[tuple[int, ...], ...] | None
    def __getitem__(self, selection) -> "ndarray-like": ...
```

Numpy basic indexing only. Advanced/fancy indexing is explicitly *not* part of the facet;
resolvers may support it natively, callers reach it through Tier 2.

### 14.3 `table`

```python
class TableFacet(Protocol):
    columns: tuple[str, ...]
    num_rows: int | None
    def read(self, columns: Sequence[str] | None = None) -> "arrow-like": ...
```

### 14.4 `container`

```python
class ContainerFacet(Protocol):
    def keys(self) -> Iterable[str]: ...
    def __getitem__(self, key: str) -> ResolvedResource: ...
    def __len__(self) -> int: ...
```

Adding a facet to the core requires a concrete interoperability need and at least two
independent implementing resolvers. Facets are not a growth area.

---

## 15. Tier 2 — native pass-through

For everything else, the resolver exposes the protocol's own operations:

```python
resource.read_block(...)
resource.structure()
resource.search(...)
```

Rules:

```text
the wrapper must not rename, reorder, or reinterpret native arguments
return values are passed through unchanged
backend exceptions propagate unwrapped unless wrapping is required for
    redaction or context (§24, §25)
__doc__ and inspect.signature must resolve to the native callable where practical
```

### 15.1 One authoritative capability mechanism

`supports(name)` is authoritative. `capabilities()` returns exactly the set for which
`supports()` is true. `__getattr__` consults the same set and raises `AttributeError` for
any name not in it, so `hasattr()` agrees by construction. There is no third answer.

```python
resource.supports("read_block")     # authoritative
"read_block" in resource.capabilities()
hasattr(resource, "read_block")     # all three agree, always
```

Capability names come from the resolved object, not from a fixed enum. A resolver must not
advertise a capability it synthesizes.

### 15.2 Typing

Tier 2 access is dynamically typed; callers get `Any` and lose completion and static
checking. Resolvers are encouraged to return typed subclasses
(`TiledResolvedResource`, `FileResolvedResource`) so that callers who have opted into
protocol coupling can `cast()` and recover tooling. Tier 0 and Tier 1 are fully typed.

---

## 16. Policy filtering — what it is and is not

A resolver may expose fewer capabilities than the backend supports:

```text
native backend capabilities → resolver policy → exposed capabilities
```

**This is intent signalling and ergonomics. It is not a security boundary.** In-process
Python filtering cannot be enforcement: the caller shares the address space with the
session object, the transport, and the credentials. Any real restriction must be enforced
server-side by the facility (Tiled access control, API authorization, network policy).

Requirements that follow:

```text
a resolver that filters capabilities MUST also deny `native`, raising
    NativeAccessDenied — otherwise the filter is trivially bypassed and
    misleading
policy filtering MUST be applied in __getattr__, not only in capabilities()
documentation for any facility plugin MUST state where real enforcement lives
the core MUST NOT describe policy filtering as a security feature
```

### 16.1 Tier 0 is present, not guaranteed to succeed

Policy may hide Tier 2 capabilities. It may never hide Tier 0. `info()` and
`materialize()` are always present, always reported by `supports()`, and never removed
from a resource. A Tier-0 operation the caller is not entitled to must **raise**, not
disappear — a vanishing method forces generic code to branch on the backend, which is the
failure this whole design exists to prevent.

Presence is not entitlement. Resolution establishes that a URI is *addressable*; it does
not establish that this caller may read the bytes, or that the bytes are retrievable right
now. Authorization is enforced server-side and often only at read time, and embargoes,
per-dataset ACLs, expiring tokens and tape recall all mean a perfectly resolvable resource
may be undeliverable at this moment. Therefore:

```text
a resolver MUST NOT eagerly probe read authorization merely to make resolve()
    fail early — it is an extra round trip on every resolution and is frequently
    unanswerable without attempting the read
a refused Tier-0 call raises AuthorizationError (caller established, not
    permitted), distinct from AuthenticationError (caller not established)
a permitted but currently unsatisfiable Tier-0 call raises
    ResourceUnavailableError, carrying retry_after where the backend knows it
these are raised at call time, from info() as well as materialize()
```

`info()` may itself raise `AuthorizationError` where even metadata is restricted. Whether
a facility prefers to report `exists=False` rather than `AuthorizationError` — the
existence-leak trade-off — is a facility policy decision. The conformance suite must
accept either and must not assert one.

This is the access-time counterpart of namespace `RESTRICTED` and `UNAVAILABLE` (§20): the
same underlying conditions, observed one stage later, when the caller holds an address
rather than an identifier.

---

## 17. Resolver protocol

```python
class Resolver(Protocol):

    api_version: int                 # see §19.3
    opaque_payload: bool             # see §4.1

    def resolve(self, uri: str, context: "ResolveContext") -> ResolvedResource: ...
    def close(self) -> None: ...     # release sessions; called by Context.close()
```

The resolver owns:

```text
URI interpretation          capability discovery and policy
authentication              the Tier 0 baseline implementation
backend connection          facet implementations it chooses to offer
session reuse               materialization mechanics
```

---

## 18. Registry

```python
register_resolver("file", FileResolver())
register_resolver("tiled-nslsii", NSLSIITiledResolver(...))
register_resolver("tiled-ssrl", SSRLTiledResolver(...))
```

Two schemes may use the same protocol with entirely independent servers, credentials,
routing, policy, URI syntax and configuration.

---

## 19. Plugins

### 19.1 Entry points

```toml
[project.entry-points."urisolver.resolvers"]
tiled-nslsii = "urisolver_nslsii:NSLSIITiledResolver"
tiled-ssrl   = "urisolver_ssrl:SSRLTiledResolver"
```

Installing a package must be sufficient to make a scheme resolvable.

### 19.2 Lazy loading

Entry points are **enumerated** eagerly and **imported** lazily on first use of their
scheme. `import urisolver` must not import Tiled, boto3, or any backend SDK. An import
failure surfaces as `PluginError` at resolve time, chained to the underlying
`ImportError`, and must not prevent other schemes from working.

### 19.3 Collisions and versioning

```text
two installed distributions registering the same scheme is a hard error
    (PluginConflictError) naming both distributions
resolution order is never implicit; the override is explicit configuration
    in the Context or a config file
each resolver declares api_version; the core refuses to load a resolver
    whose api_version it does not support (PluginVersionError)
```

---

## 20. Namespace resolution

A namespace URI answers a different question from a backend URI:

> *What concrete URI does this identifier resolve to, for this caller, right now?*

```python
class NamespaceResolver(Protocol):
    def resolve_namespace(
        self,
        identifier: str,
        context: "NamespaceRequestContext",
    ) -> "NamespaceResolution": ...
```

```python
class ResolutionStatus(str, Enum):
    AVAILABLE   = "available"      # uri is present
    RESTRICTED  = "restricted"     # exists; this caller may not have it
    UNAVAILABLE = "unavailable"    # exists; not currently retrievable
    NOT_FOUND   = "not_found"      # no such identifier, ever

@dataclass(frozen=True)
class NamespaceResolution:
    status: ResolutionStatus
    uri: str | None = None
    expires_at: datetime | None = None    # None → context default TTL
    etag: str | None = None
    retry_after: timedelta | None = None  # for UNAVAILABLE
    detail: str | None = None             # off by default; see §21.2
```

`NOT_FOUND` and `UNAVAILABLE` are separated deliberately: for archive-facing systems the
difference between "this reference was never valid" and "this reference is valid but the
data is on tape / the collection is migrating" determines whether the caller retries,
fails, or reports a broken link.

`RESTRICTED` should be distinguishable from `AVAILABLE`-after-authentication by the
`detail` field where the authority chooses to populate it.

### 20.1 Caching

The context caches namespace resolutions keyed by `(namespace, identifier, principal)` and
honours `expires_at`. Resolving 1,000 identifiers against one authority must not produce
1,000 round trips for repeated identifiers. `Context(namespace_cache=False)` disables it.
`etag` supports cheap revalidation where the authority implements it.

### 20.2 Identity

Routing may depend on the caller (§22). `NamespaceRequestContext` therefore carries the
authenticated principal, and the core must define how identity reaches the user's router:

```python
@dataclass(frozen=True)
class NamespaceRequestContext:
    principal: "Principal | None"     # authenticated caller, server-side
    secrets: "SecretsProvider"
    request_id: str
```

In-process resolvers receive the local principal (possibly `None`). Server-hosted
resolvers receive the principal established by the service's authentication hook (§21.1).
The router never sees raw credentials.

### 20.3 Recursion

```text
myfacility:abc123 → private router → tiled-private://catalog/run/123 → Tiled resolver
```

Maximum depth is small (default 4) and configurable. Loops raise `ResolutionLoopError`.
The chain is recorded on the resource as `resolved_uri` plus an internal trail available
for debugging but excluded from default logs.

---

## 21. Self-hosted namespace service

```bash
urisolver serve \
    --namespace lbl-mbib \
    --resolver mypackage.router:resolver \
    --auth mypackage.auth:authenticator
```

The server infrastructure is `urisolver`'s. The routing logic is the user's.

### 21.1 Wire API

```text
POST /resolve
```

POST rather than GET so that opaque identifiers do not appear in URLs, proxy logs,
browser history, or `Referer` headers.

Request:

```json
{ "identifier": "abc123" }
```

Response:

```json
{ "status": "available",
  "uri": "tiled-private://catalog/run/123",
  "expires_at": "2026-09-01T00:00:00Z" }
```

or `{"status": "not_found"}`, `{"status": "restricted"}`,
`{"status": "unavailable", "retry_after": 3600}`.

Authentication is a pluggable hook returning a `Principal`. The core ships bearer-token
and mTLS hooks and a `NullAuthenticator` for single-user local use; anything else is the
deployer's.

### 21.2 Diagnostics

`detail` is omitted by default. Enabling it is a deliberate deployment choice, because a
namespace authority's failure reasons leak information about internal routing, collection
names, and existence of identifiers the caller may not be entitled to know about.

### 21.3 Ownership

`urisolver` does not own namespaces. For v0 the deployer configures which namespace their
service serves. Do not build a global registry, DNS discovery, facility federation, or
automatic namespace ownership.

---

## 22. Bespoke routing

The user-supplied router may contain private and security-sensitive logic: consult private
databases, contact internal APIs, decrypt opaque tokens via OpenBao Transit / AWS KMS /
Google Cloud KMS / Azure HSM, perform authorization, check availability, route by
identity, choose current backend locations, hide internal server names, audit requests.

None of that logic exists in `urisolver-core`.

Persistent references therefore stay small and non-disclosing:

```text
lbl-mbib:abc123
myfacility:v1:AF31DD91...
```

without publishing server URLs, paths, endpoints, collections, storage technologies,
secret identifiers, or routing rules. The same reference may resolve to
`tiled-private://...` in 2026 and `globus-archive://...` in 2028, or to `UNAVAILABLE`,
without the persisted URI changing.

---

## 23. Context and sessions

```python
@dataclass
class ResolveContext:
    secrets: SecretsProvider | None = None
    registry: Registry | None = None
    namespaces: NamespaceConfig | None = None
    memory_limit: int | None = 2 * 2**30
    strict_efficiency: bool = False
    namespace_cache: bool = True
    max_resolution_depth: int = 4
    tmpdir: Path | None = None
```

`ResolveContext` is a context manager. `close()` closes every resolver it instantiated,
which closes backend sessions, and invalidates outstanding resources
(`ContextClosedError` on use). It is idempotent.

Session reuse is required: resolving 1,000 Tiled resources against one server must not
cause 1,000 authentications. Session semantics belong to the resolver; credential storage
belongs to the secrets provider; lifetime belongs to the context.

---

## 24. Secrets

```python
class SecretsProvider(Protocol):
    def get_secret(self, secret_id: str) -> Mapping[str, str]: ...
```

The provider knows the infrastructure. The resolver knows the expected structure. The core
knows neither and never persists secrets.

OpenBao is the reference backend (`urisolver-secrets-openbao`); AWS Secrets Manager,
Google Secret Manager, Azure Key Vault and bespoke providers use the same interface with
their standard authentication chains. None of their SDKs are core dependencies.
`urisolver` must not silently start OpenBao on import.

KMS/Transit/HSM decoding of opaque locators is a separate optional plugin group
(`urisolver.codecs`) from ordinary secret retrieval. Keys do not belong in `urisolver`.

### 24.1 Redaction

Never log or include in exceptions, `repr`, diagnostics, or temporary paths:

```text
passwords, API keys, access tokens, refresh tokens
Authorization headers, private keys
credential dictionaries
decrypted private locator information
opaque URI payloads (§4.1)
full URIs from schemes declaring opaque_payload
```

Backend exceptions frequently carry URLs with embedded credentials. Resolvers must
therefore **sanitize before chaining**: wrap in a `urisolver` error carrying a redacted
message, with the original attached as `__cause__` only when the context is configured to
retain it (`Context(retain_raw_exceptions=True)`, default `False` in server deployments).

Provider failure fails explicitly. Never fall back silently to plaintext secret files.

---

## 25. Error model

```text
URIResolverError
├── InvalidURIError
├── UnknownSchemeError
├── AccessError                     # raisable by resolve(), info(), materialize()
│   ├── AuthenticationError         # caller not established
│   ├── AuthorizationError          # caller established, not permitted
│   └── ResourceUnavailableError    # permitted, not retrievable now (retry_after)
├── ResolutionError
│   └── ContextClosedError
├── NamespaceResolutionError
│   ├── NamespaceNotFoundError
│   ├── NamespaceUnavailableError
│   ├── NamespaceRestrictedError
│   └── ResolutionLoopError
├── MaterializationError
│   ├── UnsupportedDestinationError
│   ├── UnsupportedFormError
│   ├── MemoryLimitError
│   └── InefficientOperationError
├── SelectionError
│   └── SelectionNotSupportedError
├── NativeAccessDenied
├── SecretLookupError
└── PluginError
    ├── PluginConflictError
    └── PluginVersionError
```

`AccessError` is deliberately not under `ResolutionError`: entitlement is decided at call
time, not at resolution time (§16.1), so a resource may resolve cleanly and then raise
`AuthorizationError` from `info()` or `materialize()`.

Native operation errors (Tier 2) remain protocol-native except where §24.1 requires
sanitization. Preserve chaining where it is safe to do so.

---

## 26. Async

v0 does not build an async abstraction, but reserves the names so that the ecosystem does
not fork later:

```python
async def aresolve(uri, *, context=None) -> ResolvedResource: ...
async def amaterialize(destination, *, selection=None, **kw) -> MaterializedResult: ...
```

Resolvers **may** implement them; `supports("aresolve")` reports whether they do. Sync
callers are never required to have an event loop.

Destinations define their own completion semantics. §11.1's "the path must exist on
success" binds `FileDestination`. A future `GlobusDestination` describes a submitted
transfer; either its `materialize()` blocks until completion, or it returns a result whose
`value` is a transfer handle and whose `strategy` is `"submitted"` — the plugin must
document which, and must not present an incomplete transfer as a completed one.

---

## 27. Reference resolvers

### 27.1 `file:` (required in v0)

```text
Kind          FILE (or CONTAINER for a directory)
info()        stat-derived: exists, size_bytes, media_type by extension
facets        stream (always), array/table only via optional codecs
Tier 2        open(), stat()
FileDest      copy by default; hardlink/symlink/in-place on request (§11.2)
MemoryDest    NATIVE == BYTES == file contents; mmap where beneficial
```

### 27.2 Tiled (required in v0)

Independently configured schemes: `tiled-local:`, `tiled-nslsii:`, `tiled-ssrl:`.

```text
1.  receive the complete URI unchanged
2.  parse its own payload
3.  determine server and resource
4.  acquire credentials via SecretsProvider
5.  create or reuse a client session (§23)
6.  resolve the native node
7.  populate ResourceInfo from the node's structure
8.  offer array / table / container facets as the node type warrants
9.  expose native operations dynamically (read, read_block, structure, search)
10. implement Tier 0 for every node type
```

Selection: numpy basic indexing is pushed to Tiled server-side wherever the node supports
it (`strategy="native-selection"`). Tiled-specific selections travel through
`Native(...)`. Do not define a second slicing grammar. Do not materialize an entire
dataset to emulate a backend-native selective operation without recording
`strategy="read-then-select"` and honouring `strict_efficiency`.

Capabilities derive from the actual resolved object. If a node has no `read_block`, do not
advertise or synthesize one. If a future Tiled version adds an operation the adapter can
safely expose, `urisolver-core` must not need modification.

### 27.3 Globus (future, must remain possible)

The plugin owns source interpretation, destination semantics, authentication, transfer
submission and status handling. Tier 0 still applies: a Globus-backed resource must
support `FileDestination` and `MemoryDestination` even if it does so by staging. The core
builds no transfer graph.

Cross-protocol optimizations (`urisolver-tiled-globus`) must be pluggable without core
changes. Do not build general cross-protocol routing in v0.

---

## 28. Composition with metadata layers

`urisolver` implements no metadata model, ontology, or provenance system. It is designed to
be *consumed* by them: URIs minted by a namespace authority are the intended durable
reference inside metadata records, and `MaterializedResult` carries `source_uri`,
`resolved_uri` and `strategy` precisely so that an external provenance layer can record
what was staged, from where, and how, without `urisolver` knowing anything about that
layer's schema. That is the whole extent of the relationship.

---

## 29. Package layout

```text
urisolver/
    __init__.py
    api.py            resolve(), default context
    context.py        ResolveContext, session lifetime
    registry.py       scheme → resolver, collisions, config override
    protocols.py      ResolvedResource, Resolver, facet protocols
    info.py           Kind, ResourceInfo
    destinations.py   Destination, FileDestination, MemoryDestination, Form
    selection.py      Selection, Native
    results.py        MaterializedResult
    errors.py
    redaction.py      URI and message redaction (§4.1, §24.1)
    plugins.py        entry points, lazy import, api_version

    resolvers/
        file.py
        tiled.py
    namespaces/
        base.py  server.py  client.py  cache.py
    secrets/
        base.py
```

Optional distributions:

```text
urisolver-secrets-{openbao,aws,google,azure}
urisolver-codec-{openbao,awskms,googlekms,azure}
urisolver-globus
urisolver-namespace-myfacility
```

Core dependencies must not include Tiled, NumPy, Globus SDK, boto3, or any cloud or
secrets SDK. (NumPy may be an optional extra used only by the array facet's type hints.)

---

## 30. Plugin groups

```toml
[project.entry-points."urisolver.resolvers"]
[project.entry-points."urisolver.namespaces"]
[project.entry-points."urisolver.secrets"]
[project.entry-points."urisolver.codecs"]
```

Later, with concrete need: `urisolver.destinations`, `urisolver.facets`. Do not add groups
speculatively.

---

## 31. Required tests

### Baseline conformance suite (the important one)

A reusable, resolver-agnostic suite that **every** resolver plugin must pass:

```text
info() returns a valid ResourceInfo without bulk transfer
Tier 0 methods are present on every resource and reported by supports()
policy filtering never removes a Tier 0 method
refusal surfaces as AuthorizationError, never as AttributeError or None
resolve() does not probe read authorization (no extra backend round trip)
either exists=False or AuthorizationError is accepted for restricted metadata
materialize(MemoryDestination) returns a non-None value for every Kind
materialize(FileDestination) returns an existing path for the kinds in §8
materialize(MemoryDestination(form=BYTES)) returns bytes-like + media_type
    for the kinds in §8, and raises UnsupportedFormError otherwise
canonical_media_type is reported and the output opens in a standard reader
a requested media_type that is unsupported raises rather than substituting
overwrite=False raises before any transfer
overwrite=True replaces atomically
failure leaves no partial file
failure never deletes a pre-existing path
is_reference=True results are never cleaned up
strategy is populated and truthful
selection with numpy basic indexing works for Kind.ARRAY
strict_efficiency turns read-then-select into an error
memory limit is enforced before transfer when size is known
resource is unusable after context close
resource is not picklable and says why
```

The suite is shipped as `urisolver.testing.baseline` so third-party resolvers can import
and run it. A plugin that does not pass it is not a v0 resolver.

### Core

```text
scheme extraction; original URI preservation; opaque payloads
resolver registration; collision detection; api_version rejection
lazy import (importing urisolver does not import backend SDKs)
plugin import failure isolated to its scheme
capabilities()/supports()/hasattr() agree under policy filtering
native pass-through preserves arguments and return values
```

### Namespace

```text
self-hosted service; user-provided router
available / restricted / unavailable / not_found
TTL honoured; expiry triggers re-resolution; etag revalidation
cache keyed by principal (no cross-principal leakage)
recursion; depth limit; loop detection
identity reaches the router; raw credentials do not
```

### Security

```text
provider injection and failure
canary secret never appears in: logs, exception messages, chained
    tracebacks, repr of resource / result / destination, temp paths
opaque URI payload never appears in any of the above
retain_raw_exceptions=False strips backend messages containing credentials
policy-filtered resolver denies native access
router internals absent from client responses when detail is disabled
```

Mock all external infrastructure in ordinary CI.

---

## 32. Phase 0 demonstration

### The protocol-agnostic path — the headline case

```python
# Nothing here knows or cares what the URI resolves to.
def stage(uri: str, workdir: Path) -> Path:
    return resolve(uri).materialize(
        FileDestination(workdir / "input.dat", overwrite=True)
    ).value

def load(uri: str):
    return resolve(uri).materialize(MemoryDestination()).value

for uri in ["file:///tmp/data.h5",
            "tiled-nslsii://catalog/run/12345",
            "lbl-mbib:abc123"]:
    stage(uri, Path("/scratch/job42"))
```

### Portable partial read

```python
r = resolve(uri)
if r.info().kind is Kind.ARRAY:
    block = r.materialize(MemoryDestination(), selection=(slice(0, 10), ...))
    assert block.strategy in {"native-selection", "read-then-select"}
```

### Facet use

```python
if "stream" in r.facets():
    with r.facet("stream").open() as fh:
        magic = fh.read(8)
```

### Native use (opted-in coupling)

```python
r = resolve("tiled-local://catalog/run/12345")
if r.supports("read_block"):
    chunk = r.read_block((0, 0))
```

### Namespace indirection

```text
lbl-mbib:abc123 → self-hosted service → private router → tiled-local://catalog/run/12345
```

---

## 33. Explicit non-goals

```text
RO-Crate support, ontologies, scientific metadata, provenance
workflow execution, job databases, queues, DAGs, scheduling
agent APIs
global namespace registry, DNS federation
a universal capability ontology
a universal query or filter language
automatic transfer graphs, replication, synchronization, mirror selection
persistent credential storage
facility-specific routing logic or security policy
directory/recursive materialization (post-v0)
```

Note the change from revision 1: a *universal delivery contract* (Tier 0) and four small
adopted facets (Tier 1) are no longer non-goals. Universal *semantics* — query languages,
capability ontologies, metadata models — remain non-goals.

---

## 34. Final architectural contract

```text
                         URI
                          |
                    scheme dispatch
               +----------+----------+
            concrete              namespace
            resolver               resolver
               |               private routing / authz
               |               KMS / HSM / availability
               |               TTL / identity
               |                     |
               +----------+----------+
                          |
                   native backend object
                          |
                   ResolvedResource
        +-----------------+-----------------+
        |                 |                 |
     Tier 0            Tier 1            Tier 2
   guaranteed          facets            native
        |                 |                 |
  info()            stream / array    read_block / structure
  materialize()     table / container  search / whatever
  selection              |             the protocol provides
  (numpy basic)     declared, optional      declared, opt-in
        |
  FileDestination / MemoryDestination
  → MaterializedResult(value, source_uri, form,
                       media_type, is_reference, strategy)
```

Authentication remains orthogonal:

```text
resolver / namespace plugin → SecretsProvider → {OpenBao, AWS, Google, Azure, bespoke}
```

The defining design rules:

> **1. Ordinary delivery — a file, or the thing in memory — must work identically for
> every resolver, with no protocol knowledge in the caller.**
>
> **2. Beyond that, `urisolver` exposes the native protocol surface and does not reinvent
> the data-access semantics of the protocols it resolves.**
>
> **3. Where the two meet, the result tells the truth about how it was obtained.**

---

## 35. Implementation directive

This document is frozen for v0. It is a build order, not a starting point for
architectural improvement. The abstractions absent from it were removed deliberately and
under review; their absence *is* the design.

Do not add, without a written amendment to this document:

```text
a capability enum or capability ontology
a SliceSpec, Query, Filter or Predicate type
a universal streaming interface beyond the stream facet
a fifth facet, a sixth Kind, or an additional Form
a metadata, schema, or provenance model
a retry, cache, or connection-pool layer above the resolver
a base class that resolvers are required to inherit from
a convenience API that hides which tier a call lands in
an async abstraction beyond the reserved names in §26
```

Rules for the implementer:

```text
if a requirement here looks wrong, stop and say so; do not route around it
if two sections conflict, that is a spec bug — report it, do not adjudicate
prefer thirty duplicated lines across two resolvers over a shared abstraction
    in the core; the core earns an abstraction on the third implementation
    that wants it, not the first
every public name in this document must appear in the code with that name
anything not in this document is out of scope for v0, including things that
    are obviously good ideas
```

v0 is done when the baseline conformance suite (§31) passes for the `file:` and Tiled
resolvers, and a third-party resolver can be written against this document alone.