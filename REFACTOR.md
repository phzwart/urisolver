# REFACTOR.md — urisolver becomes a Tiled binder

Status: approved direction. Implemented on branch `tiled-binder`.
Starting tag: `v0.1.0-pre-tiled-binder` at `8ffd803`.

This file is the normative spec for the refactor. Sections 1–7 are the design.
The phase plan and implementer rules are historical once the work has landed.

## 0. Rules for the implementer

1. Build exactly what this file says. Do not re-add Tier 0 delivery, destinations, facets, selections, materialize, or worker-side secrets.
2. Workers never import urisolver. The read path is plain Tiled client calls.
3. Only `urisolver/tiled/_compat.py` imports Tiled internals. Other modules may import `tiled.client`, `tiled.structures.*`, and (server side only) `tiled.adapters.core`.
4. `import urisolver` must not import tiled, globus_sdk, numpy, pandas, or pyarrow.
5. No live network in the default test run. Live tests are gated by environment variables.
6. Commits are small and phase-scoped. Messages are imperative, one line, and end with a period.

## 1. What changes

urisolver runs at registration time. Given a URI, it creates a Tiled node on our server. After that, every worker reads through a plain Tiled client. urisolver is not on the read path.

Modes:

- REFERENCE: external asset in readable storage
- PROXY: custom adapter forwards to an upstream Tiled
- ACQUIRE: land bytes, then REFERENCE
- EXISTING: the data is already a node on the target server

## 2. Facts this design rests on

Checked against Tiled 0.2.18.

- F1. A node can be created with an external data source (`Management.external`, `Asset(data_uri=file://..., parameter="data_uri")`).
- F2. The server serves a `file://` asset only under a configured readable storage root. The check is textual (`os.path.commonpath` on absolute, unresolved paths).
- F3. Registration of a `file://` asset outside readable storage is accepted and fails only at read time. urisolver checks at bind time.
- F4. Adapters are chosen per mimetype. `adapters_by_mimetype` accepts import strings.
- F5. Server config accepts custom routers as import strings.
- F6. A proxy adapter serves full reads and slices of an upstream array. The worker sees neither the upstream server nor its key.
- F7. Tiled 0.2.18 has no link or alias node type.
- F8. Tiled's own file registration writes the local path as `data_uri`, which is wrong when the registering host and the server mount storage at different paths.
- F9. Unknown specs are accepted unless the server sets `reject_undeclared_specs`.
- F10. Two Tiled apps in one process share global auth settings. Live tests run the upstream server in a subprocess.
- F11. `globus_sdk.TransferClient.task_wait` requires integer `timeout` and `polling_interval` >= 1.
- F12. Tiled is BSD-licensed. urisolver is MIT.

## 3. Vocabulary

- Bind / register: turn a URI into a node on a Tiled server.
- Binder: a plugin for one protocol (`file`, `tiled`, `globus`, `zenodo`).
- Source: a site-config entry that binds a URI scheme to a protocol and its parameters.
- Site: readable storage, path mapping, landing area, and sources.
- Mode: how a bind makes data readable.
- Plan: a pure description of a bind.
- Binding: the result of executing a plan.

## 4. Disposition

Keep `_uriparse.py`, `redaction.py`, secrets (`base`, `jsonfile`), and namespaces (`base`, `client`, `server`).

`NamespaceCache.put` caches only `AVAILABLE`. `UNAVAILABLE` is cached only when `retry_after` is set, and only for `retry_after`.

Rewrite errors, the registry (keyed by protocol), plugins (groups `urisolver.binders` and `urisolver.sources`), and context as `BindContext`.

Move `kg/` to `tools/kg/`. Delete the delivery layer: destinations, selection, results, info, protocols, resources, exchange, the old API, and example resolvers after salvage.

Salvage `_uri_to_path`, `_path_segments`, Globus transfer helpers, and Zenodo fetch/stream helpers.

## 5. Target architecture

L0 core does not import tiled at module level: parse, redaction, errors, secrets, namespaces, site, context, binder registry, plan dataclasses.

L1 `urisolver.tiled` is client-side (`tiled.client`, `tiled.structures`) plus `_compat`.

L1 binders use L0 and L1.

L2 `urisolver.tiled_server` is loaded by Tiled config. It imports `tiled.adapters.core` and `redaction` only. It does not import binders, globus, zenodo, or site.

Modes, in preference order for `mode="auto"`: EXISTING, REFERENCE, PROXY, ACQUIRE.

| Binder | EXISTING | REFERENCE | PROXY | ACQUIRE |
|---|---|---|---|---|
| file | no | path under a readable entry | no | landing configured |
| tiled | source base equals target base | no | `proxy: true` and family is array or table | landing configured; family is array or table |
| globus | no | no | no | `landing.globus` configured |
| zenodo | no | no | no | landing configured |

A forced infeasible mode raises `ModeNotAvailableError` with `.feasible` and `.reasons`.

PROXY server config registers:

```yaml
adapters_by_mimetype:
  application/x-urisolver-tiled-proxy;structure=array: urisolver.tiled_server.proxy:RemoteArrayAdapter
  application/x-urisolver-tiled-proxy;structure=table: urisolver.tiled_server.proxy:RemoteTableAdapter
```

`URISOLVER_PROXY_CREDENTIALS` points at a mode-0600 JSON file of upstream API keys.

## 6. Public API

`plan(uri, into, *, key=None, mode="auto", metadata=None, context=None) -> Plan`

`register(...)` adds `on_conflict="return"` and `acquire_timeout=None`.

`register` algorithm:

1. Open context. Resolve namespaces to `(resolved, trail)`.
2. Source from the site. Binder from `source.protocol`, or from the scheme when there is no source (`file`).
3. Binder plans the chosen mode.
4. `plan()` stops here, after attaching `Origin` and merging metadata.
5. EXISTING (`existing_path` set): return the node. Create nothing. Write nothing.
6. ACQUIRE: `binder.acquire`, then re-plan the landed path with the file binder in REFERENCE mode. Origin mode stays `acquire` and `acquired_from` is the resolved URI. If the landed path is not referenceable, `SiteConfigError`.
7. `urisolver.tiled.apply.create`.
8. Return the `Binding`.

`OnConflict`: `return` (same origin returns the node; a different origin errors), `error`, `replace` (delete recursively, then create). Never mutate an existing node's metadata on `return`.

Origin metadata key `urisolver` plus spec `urisolver-origin` version `1`. Caller metadata is merged first. A caller `urisolver` key raises `ValueError`. Opaque namespace URIs are redacted in `origin` and `trail`. `resolved` is written as given.

`BindContext.__post_init__` bootstraps binders when `binders` is the global registry. Client caches live on the context, keyed by `(protocol, base, secret_id)`, and are dropped on close.

Site lookup: explicit path, `URISOLVER_SITE`, then `~/.config/urisolver/site.yaml`. Entry-point sources merge under the file. An explicit path or env var is not merged with the user file.

Validation raises `SiteConfigError` naming the key: readable paths absolute and not nested; landing inside a readable entry; layout contains `{name}` and `{sha12}` or `{sha64}`. Unknown protocols are an error at bind time, not load time.

`to_server_path` resolves the file and each local root, picks the longest containing root, and joins onto the server root verbatim.

Default keys: file and zenodo filenames with Tiled's `strip_suffixes`; tiled and globus use the last path segment. An invalid key raises `BindError` telling the caller to pass `key=`.

Errors: `URIResolverError` aliased as `UrisolverError`, then `InvalidURIError`, `UnknownSchemeError`, `SiteConfigError`, `PluginError` (`PluginConflictError`, `PluginVersionError`), `SecretLookupError`, namespace errors, access errors, and `BindError` (`ModeNotAvailableError`, `NotReadableError`, `KeyConflictError`, `DescribeError`, `AcquireError`, `AcquireTimeoutError`).

Binder API version is 2. Version 1 raises `PluginVersionError`. Protocol conflicts raise `PluginConflictError` at first use. Lazy proxies do not import their module at registration, and `opaque_payload` is not read until the binder loads.

CLI: `plan`, `register`, `site check`, `binders`. Exit codes: 0 ok, 2 usage, 3 bind error, 4 access error, 5 site or plugin error.

## 7. Binders

File URIs keep the RFC 8089 checks. `?recursive` is the only allowed query. REFERENCE uses `describe_local`, which rewrites every asset `data_uri` onto the server path and raises `NotReadableError` if a rewritten URI leaves readable storage. A directory that is not one describable item needs `?recursive`; undescribable files are skipped and recorded on `Plan.notes`. Image-sequence grouping is out of scope.

Tiled URIs use a source with `protocol: tiled`. EXISTING when the normalized source base equals the target base. PROXY stores the upstream base as an external asset and the remote path as a parameter, with mimetypes from `urisolver.tiled_server.proxy`. Upstream metadata is copied under `metadata["upstream"]`. ACQUIRE exports arrays with `numpy.save` of `node.read()` and tables with `to_parquet`, and notes that the array path reads the whole array. PROXY and ACQUIRE of containers are out of scope.

The proxy adapters resolve the remote node per request, cache one client per upstream base, and raise `IncompatibleShapeError` when shape, dtype, or columns differ. Credentials in a file looser than mode 0600 are refused. A missing entry uses an anonymous client. API keys never appear in exceptions.

`describe_local` follows Tiled's `register_single_item` (mimetype, `from_uris`, `generate_data_sources` or the single-asset form) and rewrites paths. Site overrides live under `tiled.mimetypes_by_file_ext` and `tiled.adapters_by_mimetype`.

Zenodo is ACQUIRE only. URIs are `<scheme>:/records/<id>/<filename>`. The `https://zenodo.org/records/...` form is accepted only when a source maps host `zenodo.org`. Size or md5 mismatch raises `AcquireError` and leaves no file.

Globus is ACQUIRE only and requires `landing.globus`. A directory needs `?recursive`. Transfer to a temp sibling with checksum verification, then rename. `task_wait` timeouts and polling intervals are integers >= 1. Timeout cancels the task and raises `AcquireTimeoutError`. A missing local temp path after success is `SiteConfigError`. Every secret value seen in the context is scrubbed.

## 8. Packaging

Version `0.2.0.dev0`. Core dependencies are empty. Extras: `tiled`, `server`, `globus`, `dev` (dev includes `tiled[all]>=0.2.18,<0.3`). Entry points `urisolver.binders` for file, tiled, globus, and zenodo. No `kg/` in the wheel. No force-included example catalog. `examples/site.example.yaml` ships in the sdist only.

CI installs `.[dev]`, with one leg pinned to Tiled 0.2.18 and one unpinned within `<0.3`.

## 9. Tests

`import urisolver` loads none of the heavy modules. `BindContext()` bootstraps the file binder with no prior module-level call. Namespace cache rules, site validation (symlinks, `..`, longest root, landing inside readable, entry points under the file), plugin conflicts, API version 1, and redaction are covered without Tiled.

File REFERENCE of `.npy`, `.csv`, `.tiff`, and `.h5` rewrites `data_uri` to the server path. The site fixture maps a real directory to a symlink the server calls readable storage, so an unrewritten URI fails Tiled's textual check. No test creates a `file://` asset outside readable storage. `plan()` does not write. Idempotent register returns `created=False`. A different URI at the same key raises `KeyConflictError`.

PROXY tests use an in-process target and a subprocess upstream with array `img` (6×8 float32 arange) and table `tab` (3×10). Full read, slice, block, columns, and partition match. Structure drift fails the read. Credential file mode 0644 is refused.

ACQUIRE tests cover copy, tiled export, zenodo size and md5 failure, and globus success, failure, timeout-cancel, and a missing landing file. `_wait` is checked against a real `TransferClient` with a monkeypatched `task_wait` for timeouts `None`, `0.01`, `5.5`, and `3600`. Sentinel secrets never appear in plans, reprs, or exceptions.

The conformance suite checks API version 2, every mode once, no plan side effects, infeasible forced modes, atomic acquire, and secret redaction.

## 10. Docs and examples

`DESIGN.md` is rewritten from sections 1–7. The v0.1 design moves to `docs/history/DESIGN-v0.1.md`. `SCHEMES.md` has one section per protocol. The README has three examples, each at most 10 lines. Examples are `site.example.yaml`, `tiled-server.example.yml`, `reference.py`, `proxy.py`, `acquire_globus.py`, `acquire_zenodo.py`, and `globus/login.py`. This file moves to `docs/history/` when the refactor is merged.

## 11. Adoption

Layer boundaries stay hard so the proxy can lift out, binders can stay separate, or the package can remain a plugin. Stock Tiled only: config import strings, no monkeypatch. `_compat.py` is the list of internals. Origin metadata is one reserved key plus spec `urisolver-origin/1`. Mimetype names are namespaced.

## 12. Phases

1. Strip and skeleton.
2. File REFERENCE, describe, and apply.
3. PROXY and EXISTING.
4. ACQUIRE for file, tiled, zenodo, and globus.
5. CLI, conformance, examples.
6. Docs and packaging.

## 13. Out of scope

Asynchronous acquire jobs, PROXY or ACQUIRE of Tiled containers, image-sequence grouping, chunked Tiled export, a `POST /register` router, and any worker-side API.

## 14. Defaults

Re-registering the same URI returns the existing node. The landing area is a directory inside readable storage and stays `Management.external`. PROXY uses one service identity per upstream. Upstream structure drift fails the read. `auto` prefers EXISTING, then REFERENCE, then PROXY, then ACQUIRE.
