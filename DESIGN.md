# urisolver

urisolver runs at registration time. Given a URI, it creates a node on a Tiled server. After that, every worker reads through a plain Tiled client. urisolver is not on the read path.

## Modes

- REFERENCE: an external asset under readable storage.
- PROXY: a custom adapter forwards reads to an upstream Tiled server.
- ACQUIRE: land the bytes, then REFERENCE the copy.
- EXISTING: the data is already a node on the target server.

`mode="auto"` picks the first feasible mode in that order: EXISTING, REFERENCE, PROXY, ACQUIRE. A forced mode that is not feasible raises `ModeNotAvailableError` with `.feasible` and `.reasons`.

| Binder | EXISTING | REFERENCE | PROXY | ACQUIRE |
|---|---|---|---|---|
| file | no | path under a readable entry | no | landing configured |
| tiled | source base equals the target base | no | `proxy: true` and the family is array or table | landing configured; family is array or table |
| globus | no | no | no | `landing.globus` configured |
| zenodo | no | no | no | landing configured |

## Vocabulary

- Bind / register: turn a URI into a node on a Tiled server.
- Binder: a plugin for one protocol (`file`, `tiled`, `globus`, `zenodo`).
- Source: a site entry that binds a URI scheme to a protocol and its parameters.
- Site: readable storage, path mapping, a landing area, and sources.
- Plan: a description of a bind. `plan()` does not write.
- Binding: the result of executing a plan.

## Layout

The core does not import Tiled at module level: parse, redaction, errors, secrets, namespaces, site, context, the binder registry, and plan dataclasses.

`urisolver.tiled` is client-side (`tiled.client`, `tiled.structures`) plus `tiled/_compat.py`. Only `_compat.py` imports Tiled internals.

Binders use the core and `urisolver.tiled`.

`urisolver.tiled_server` is loaded by a Tiled server config. It imports `tiled.adapters.core` and redaction. It does not import binders, site, Globus, or Zenodo.

`import urisolver` does not import tiled, globus_sdk, numpy, pandas, or pyarrow.

## Register

```python
plan(uri, into, *, key=None, mode="auto", metadata=None, context=None) -> Plan
register(uri, into, *, on_conflict="return", acquire_timeout=None, ...) -> Binding
```

1. Resolve namespace hops to `(resolved, trail)`.
2. Take the source from the site. The binder comes from `source.protocol`, or from the scheme when there is no source.
3. The binder plans the chosen mode.
4. `plan()` stops here, after attaching origin metadata.
5. EXISTING returns the node. It creates nothing and writes nothing.
6. ACQUIRE calls `binder.acquire`, then re-plans the landed path with the file binder in REFERENCE mode. Origin mode stays `acquire` and `acquired_from` is the resolved URI. A landed path that is not referenceable raises `SiteConfigError`.
7. `urisolver.tiled.apply.create` writes the node.
8. Return the `Binding`.

`OnConflict.return` returns the existing node when the origin matches and raises `KeyConflictError` otherwise. It does not change the existing node's metadata. `error` always conflicts. `replace` deletes the node recursively with `external_only=True`, then creates it again.

Origin metadata is `metadata["urisolver"]` plus spec `urisolver-origin` version `1`. Caller metadata is merged first. A caller `urisolver` key raises `ValueError`. Opaque namespace URIs are redacted in `origin` and `trail`. `resolved` is stored as given.

`BindContext` bootstraps the built-in binders when it uses the global registry. Client caches live on the context, keyed by `(protocol, base, secret_id)`, and are dropped on `close`.

## Site

Lookup order: an explicit path, `URISOLVER_SITE`, then `~/.config/urisolver/site.yaml`. Entry-point sources merge under the file. An explicit path or env var is not merged with the user file.

Validation raises `SiteConfigError` naming the key. Readable paths are absolute and not nested. The landing directory is inside a readable entry. The layout contains `{name}` and `{sha12}` or `{sha64}`. An unknown protocol is an error at bind time, not at load time.

`to_server_path` resolves the file and each local root, picks the longest containing root, and joins onto the server root verbatim. Tiled compares readable-storage paths as text, so the server root is not resolved again.

Landing paths use `{protocol}/{sha12}/{name}` by default. An acquire writes a sibling `*.partial` file and renames it into place.

## Errors

`URIResolverError` is aliased as `UrisolverError`. Under it: `InvalidURIError`, `UnknownSchemeError`, `SiteConfigError`, `PluginError` (`PluginConflictError`, `PluginVersionError`), `SecretLookupError`, namespace errors, access errors (`AuthenticationError`, `AuthorizationError`, `ResourceUnavailableError`), and `BindError` (`ModeNotAvailableError`, `NotReadableError`, `KeyConflictError`, `DescribeError`, `AcquireError`, `AcquireTimeoutError`).

Binder API version is 2. Version 1 raises `PluginVersionError`. Two entry points for one protocol raise `PluginConflictError` the first time that protocol is used. Lazy proxies do not import their module at registration.

The CLI commands are `plan`, `register`, `site check`, `binders`, and `proxy credentials`. Exit codes: 0 ok, 2 usage, 3 bind error, 4 access error, 5 site or plugin error. `site check` fails when a readable root or the landing directory is missing. `proxy credentials` writes the mode-0600 upstream key file the server reads.

## Binders

File URIs follow RFC 8089. `?recursive` is the only allowed query. REFERENCE uses `describe_local`, which rewrites every asset `data_uri` onto the server path and raises `NotReadableError` if a rewritten URI leaves readable storage. A directory that is not one describable item needs `?recursive`. Undescribable files are skipped and recorded on `Plan.notes`.

Tiled URIs use a source with `protocol: tiled`. EXISTING applies when the normalized source base equals the target base. PROXY stores the upstream base as an external asset and the remote path as a parameter. The mimetypes are `application/x-urisolver-tiled-proxy;structure=array` and `application/x-urisolver-tiled-proxy;structure=table`. Upstream metadata is copied under `metadata["upstream"]`. ACQUIRE saves arrays with `numpy.save` of `node.read()` and tables with `to_parquet`, and notes that the array path reads the whole array. PROXY and ACQUIRE of containers are out of scope.

The proxy adapters resolve the remote node on each read, cache one client per upstream base, and raise `IncompatibleShapeError` when the shape, dtype, or columns differ. The server process, not the worker, holds `URISOLVER_PROXY_CREDENTIALS`, a mode-0600 JSON file of upstream API keys. `urisolver proxy credentials` writes that file. Registration still uses the site `secret_id`. A looser mode is refused. A missing entry uses an anonymous client. API keys never appear in exceptions. A client that reads the proxied node does not receive the upstream key.

`describe_local` follows Tiled's single-item registration (mimetype, `from_uris`, `generate_data_sources` or one asset) and rewrites paths. Site overrides live under `tiled.mimetypes_by_file_ext` and `tiled.adapters_by_mimetype`. A `.parquet` file is described as one external table asset because Tiled's parquet adapter has no `from_uris`.

Zenodo is ACQUIRE only. URIs are `<scheme>:/records/<id>/<filename>`. `https://zenodo.org/records/...` is accepted only when a source sets `host: zenodo.org`. The `https` scheme is not claimed globally. A size or md5 mismatch raises `AcquireError` and leaves no file.

Globus is ACQUIRE only and requires `landing.globus`. A directory needs `?recursive`. The transfer goes to a temp sibling with checksum verification, then a local rename. `task_wait` timeouts and polling intervals are integers of at least 1. `timeout=None` repeats a 3600-second wait. A timeout cancels the task and raises `AcquireTimeoutError`. A missing local temp path after success is `SiteConfigError`. Every secret value named by the source is scrubbed from errors.

## Defaults

Re-registering the same URI returns the existing node. The landing area is a directory inside readable storage and stays `Management.external`. PROXY uses one service identity per upstream. Upstream structure drift fails the read.
