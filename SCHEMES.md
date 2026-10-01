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
