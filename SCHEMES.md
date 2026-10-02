# Scheme definitions

Every URI scheme registered with a `urisolver` deployment is defined here, per RFC 7595
§3.3, §3.4, and §3.7. A scheme with no entry is not deployable.

## Registered schemes

| Scheme | Status | Notes |
| --- | --- | --- |
| `file` | Built-in | See DESIGN.md §27.1 |
| `gov.bnl.nsls2.tiled` | Optional (`[tiled]` extra) | Tiled deployment; document before deploy |
| `gov.bnl.nsls2.tiled-ssrl` | Optional (`[tiled]` extra) | Tiled deployment; document before deploy |
| `gov.lbl.mbib` | Documented below | Facility namespace (opaque name → concrete URI) |

Deployment-specific schemes follow the template below and get a page in this file before
they are registered.

A local resolution catalog binds a scheme to a server. `examples/catalog.yaml` is the
example. Each entry names one scheme:

```yaml
com.urisolver.example.tiled:
  protocol: tiled
  base_uri: https://tiled.example
  native: [memory]
  secret_id: tiled

com.urisolver.example.globus:
  protocol: globus
  collection: 6c54cade-bde5-45c1-bdea-f4bd71dba2cc
  native: [file]
  secret_id: globus-example
  staging: &lab-staging
    collection: 00000000-0000-0000-0000-000000000000
    root: /
    accessible:
      - /CHANGE_ME
```

`protocol` selects the server kind. A tiled entry requires `base_uri`. `secret_id` is
optional. When set, the resolver calls `SecretsProvider.get_secret(secret_id)`. Tiled
reads `api_key` or `token`. Globus reads `client_id` plus `refresh_token` or
`client_secret`.

A globus entry requires `collection`, the source collection UUID. `staging` is the
collection on this machine that receives a file or memory delivery: `collection`, `root`,
and `accessible` (absolute local prefixes). Another scheme in this file reuses one block
with `staging: *lab-staging`. There is no top-level machine key. `staging.collection` and
`accessible` in the committed example are placeholders; replace them before a transfer.

`native` is the efficient path: `memory`, `file`, or both. It does not remove Tier 0. A
caller that sets `strict_efficiency` is refused a delivery outside that list. Tiled is
`memory`. Globus is `file`.

The Globus URI path is the absolute path on `collection`.
`com.urisolver.example.globus:///share/godata/file1.txt` is `/share/godata/file1.txt` on
Tutorial Collection 1. An authority (`scheme://<uuid>/path`) is rejected. A sibling scheme
that puts the collection UUID in the authority is future work.

## Template

### Scheme name

Lowercase, RFC 3986 §3.1 grammar. State whether it is reverse-DNS private use (RFC 7595
§3.8) or registered with IANA, and if registered, the status (provisional / permanent)
and date.

### Syntax

The scheme-specific-part grammar. State explicitly:

- is there an authority component? if not, `//` is invalid and is rejected;
- which reserved characters (RFC 3986 §2.2) are delimiters in this scheme, and which must
  be percent-encoded;
- is a query component defined? if so, is it part of the identifier?
- is the scheme-specific-part case-sensitive?

### Semantics

What does a URI of this scheme identify? Is it a locator or a name?

### Operations

What does dereferencing do (RFC 7595 §3.4)? What is the default operation? Is it safe in
the sense of the W3C Web Architecture — does dereferencing incur any obligation?

### Fragments

Fragments are not interpreted by `urisolver` (see DESIGN.md §4.3). Record any
media-type-specific fragment meaning the scheme may define later.

### Encoding

How is human-readable text encoded into the URI (RFC 7595 §3.6)? Which percent-encodings
are legal?

### Security and privacy

Is the scheme-specific-part sensitive (RFC 7595 §3.7)? Does this scheme set
`opaque_payload = True`? What does an observer learn from seeing a URI of this scheme in
a log, a metadata record, or a publication?

### Change control

Who assigns identifiers in this scheme? What is the commitment to not reassigning them?

---

## gov.lbl.mbib

### Scheme name

`gov.lbl.mbib` — reverse-DNS private use (RFC 7595 §3.8). Owner: Lawrence Berkeley
National Laboratory (`lbl.gov`). Not registered with IANA.

### Syntax

Opaque identifier namespace. **No authority component** — `gov.lbl.mbib://identifier`
is invalid and rejected by the core (RFC 7595 §3.2).

```text
gov.lbl.mbib:<identifier>
```

- `<identifier>` is opaque to the core; characters are passed verbatim to the namespace
  router after scheme dispatch.
- No query component is defined.
- Case-sensitive identifier (deployment policy; the scheme itself is case-insensitive per
  RFC 3986 §6.2.2.1).

### Semantics

A persistent, location-independent name assigned by the facility namespace authority. The
URI names an identifier, not a storage location. Dereference requires namespace
indirection (DESIGN.md §20–§22).

### Operations

Default operation: POST to the namespace service (`/resolve`) with the identifier; receive
a concrete backend URI; follow namespace indirection in the context. No direct
dereference without the router.

### Fragments

Fragments are not interpreted (DESIGN.md §4.3). A fragment on a namespace URI is split off
before the identifier reaches the router and may be inherited onto the resolved backend
URI per RFC 9110 §10.2.2.

### Encoding

Identifiers SHOULD use unreserved characters (RFC 3986 §2.3). Percent-encoding is the
caller's responsibility if reserved characters appear in an identifier.

### Security and privacy

The scheme-specific-part is **sensitive**: it may encode internal catalog keys, run IDs,
or other facility-internal references. Namespace resolvers SHOULD set `opaque_payload =
True`. The core redacts opaque payloads in logs and exceptions (DESIGN.md §4.1).

### Change control

Identifiers are assigned by the facility namespace authority. Identifiers MUST NOT be
reassigned to a different resource once published.

---

## com.urisolver.example.globus

### Scheme name

`com.urisolver.example.globus` — reverse-DNS private use (RFC 7595 §3.8). Example
scheme for one Globus Transfer collection. Not registered with IANA. The optional
`[globus]` extra supplies the SDK.

### Syntax

No authority component. `com.urisolver.example.globus://<uuid>/path` is invalid.
The path is absolute on the collection named by the resolution catalog:

```text
com.urisolver.example.globus:/<absolute-path>
com.urisolver.example.globus:///<absolute-path>
```

- `/` separates path segments. An empty interior segment (`a//b`) is `InvalidURIError`.
- Each segment is percent-decoded once.
- No query component is defined.
- The path is case-sensitive. The scheme is case-insensitive (RFC 3986 §6.2.2.1).

### Semantics

A locator for one path on the catalog's source collection. The example entry points at
Tutorial Collection 1 (`6c54cade-bde5-45c1-bdea-f4bd71dba2cc`). The path
`/share/godata/file1.txt` is that tutorial's sample file.

### Operations

`resolve` checks the path and does not contact Globus. `info` lists the parent.
`materialize(FileDestination)` submits a checksum transfer into the staging collection
and blocks until the task succeeds, then renames the file into place.
`materialize(MemoryDestination)` stages through a temporary file on that collection and
returns the bytes (`strategy="staged"`). `GlobusDestination` submits and returns the
task id (`strategy="submitted"`) without waiting. A missing `staging` block makes file
and memory delivery `UnsupportedDestinationError` and does not affect `GlobusDestination`.

### Fragments

Fragments are not interpreted (DESIGN.md §4.3).

### Encoding

UTF-8 percent-encoding (RFC 3986 §2.1). Reserved characters in a segment must be
percent-encoded by the caller. The resolver decodes each segment once.

### Security and privacy

The path may name a private file, a user directory, or an instrument path. That is
sensitive in a log or a paper. This scheme sets `opaque_payload = False`: the core does
not redact the path. Callers that log URIs of this scheme should redact them. Credential
values never appear in resolver errors. A refresh token or client secret is read from
the secrets provider and is not part of the URI.

### Change control

The example scheme name is stable for this repository. The collection it points at is
deployment data in `examples/catalog.yaml` and can change without renaming the scheme.
Paths on the tutorial collection are assigned by Globus.
