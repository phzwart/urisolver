"""Concept catalogue for the urisolver knowledge graph.

Each concept: id, label, kind, definition (paraphrase, how=derived), anchors
(path, symbol) -> verbatim sentences extracted by anchors.py, relations, and
optional RFC citation strings resolved by literature.py.

kind: architecture | contract | protocol | scheme
relations: IS_A, PART_OF, USES, DUAL_OF, SPECIALIZES, EQUIVALENT_TO,
           RELATED_TO, DEFINED_BY, INSTANCE_OF, CONTRASTS_WITH

A markdown anchor's symbol is a heading title. A Python anchor's symbol is a
function or class name, or "" for the module docstring.
"""
from __future__ import annotations

C: list[dict] = []


def c(id, label, kind, definition, anchors, rels=(), refs=(), aliases=()):
    C.append(dict(
        id=id, label=label, kind=kind, definition=definition,
        anchors=list(anchors), rels=list(rels), refs=list(refs),
        aliases=list(aliases),
    ))


c(
    "registration", "Registration", "architecture",
    "urisolver creates a Tiled node from a URI at registration time. Workers "
    "then read that node with a Tiled client.",
    [("DESIGN.md", "urisolver"), ("src/urisolver/bind.py", "")],
    [("USES", "auto_mode"), ("USES", "site"), ("USES", "origin")],
    aliases=["register", "bind"],
)
c(
    "auto_mode", "Auto mode", "contract",
    "mode=\"auto\" selects the first feasible mode in the order EXISTING, "
    "REFERENCE, PROXY, ACQUIRE.",
    [("DESIGN.md", "Modes"), ("src/urisolver/bind.py", "Mode")],
    [("PART_OF", "registration")],
    aliases=["mode auto"],
)
c(
    "site", "Site", "architecture",
    "A site names readable storage, a landing area, sources, and the target "
    "server. Lookup is an explicit path, then URISOLVER_SITE, then the user file.",
    [("DESIGN.md", "Site"), ("src/urisolver/site.py", "")],
    [("PART_OF", "registration"), ("USES", "server_path")],
    aliases=["site file"],
)
c(
    "site_load", "Site load", "contract",
    "Loading a site file resolves relative readable and landing paths against "
    "that file and does not follow symlinks. from_mapping requires absolute paths.",
    [("src/urisolver/site.py", "load")],
    [("PART_OF", "site")],
    aliases=["relative path"],
)
c(
    "server_path", "Server path", "contract",
    "to_server_path maps a local file onto the longest containing readable root "
    "and joins the relative path onto the server root verbatim.",
    [("src/urisolver/site.py", "to_server_path")],
    [("PART_OF", "site"), ("USES", "file_binder")],
    aliases=["readable storage"],
)
c(
    "origin", "Origin", "contract",
    "Every created node stores origin metadata at metadata[\"urisolver\"] and "
    "carries the urisolver-origin spec.",
    [("src/urisolver/tiled/origin.py", ""), ("DESIGN.md", "Register")],
    [("PART_OF", "registration")],
    aliases=["urisolver-origin"],
)
c(
    "on_conflict", "On conflict", "contract",
    "The default on_conflict value return keeps an existing key when the stored "
    "origin or resolved URI matches. A different origin raises KeyConflictError.",
    [("DESIGN.md", "Defaults"), ("src/urisolver/tiled/apply.py", "create")],
    [("USES", "origin"), ("PART_OF", "registration")],
    aliases=["return", "replace"],
)
c(
    "command_line", "Command line", "architecture",
    "The commands are plan, register, site check, binders, and proxy credentials. "
    "Exit codes are 0, 1, 2, 3, 4, and 5.",
    [("DESIGN.md", "Errors"), ("src/urisolver/cli.py", "main")],
    [("USES", "registration"), ("USES", "proxy_credentials")],
    aliases=["urisolver cli"],
)
c(
    "file_binder", "File binder", "protocol",
    "The file binder references a path under readable storage, or copies bytes "
    "into landing storage when acquire is selected.",
    [("SCHEMES.md", "file"), ("src/urisolver/binders/file.py", "")],
    [("USES", "server_path"), ("USES", "describe_local")],
    refs=["RFC 8089"], aliases=["file"],
)
c(
    "tiled_binder", "Tiled binder", "protocol",
    "The tiled binder returns an existing node, proxies an upstream array or "
    "table, or copies one into landing storage.",
    [("SCHEMES.md", "tiled"), ("src/urisolver/binders/tiled.py", "")],
    [("USES", "proxy_credentials"), ("USES", "registration")],
    aliases=["tiled"],
)
c(
    "globus_binder", "Globus binder", "protocol",
    "Globus is ACQUIRE only. The transfer lands on landing.globus and the local "
    "file is renamed into the landing layout.",
    [("SCHEMES.md", "globus"), ("src/urisolver/binders/globus.py", "")],
    [("USES", "site")],
    aliases=["globus"],
)
c(
    "zenodo_binder", "Zenodo binder", "protocol",
    "Zenodo is ACQUIRE only. A size or md5 mismatch leaves no file, and a "
    "redirect onto another host is refused.",
    [("SCHEMES.md", "zenodo"), ("src/urisolver/binders/zenodo.py", "")],
    [("USES", "site")],
    aliases=["zenodo"],
)
c(
    "proxy_credentials", "Proxy credentials", "contract",
    "The Tiled server process holds upstream API keys in the mode-0600 file "
    "named by URISOLVER_PROXY_CREDENTIALS. A reading client does not receive that key.",
    [("src/urisolver/tiled_server/credentials.py", ""), ("DESIGN.md", "Binders")],
    [("USES", "tiled_binder")],
    aliases=["URISOLVER_PROXY_CREDENTIALS"],
)
c(
    "describe_local", "Describe local", "contract",
    "describe_local follows Tiled single-item registration and rewrites each "
    "asset data_uri onto the server path.",
    [("src/urisolver/tiled/describe.py", "")],
    [("USES", "server_path"), ("USES", "file_binder")],
    aliases=["describe_local"],
)
c(
    "opaque_payload", "Opaque payload", "contract",
    "Redaction replaces an opaque URI payload with the scheme and a digest.",
    [("src/urisolver/redaction.py", "")],
    [("USES", "redaction")],
    aliases=["opaque payload"],
)
c(
    "redaction", "Redaction", "contract",
    "Messages drop secret-shaped text and listed opaque URI payloads.",
    [("src/urisolver/redaction.py", "redact_message")],
    [("USES", "opaque_payload")],
    aliases=["redact"],
)
c(
    "light_import", "Light import", "contract",
    "import urisolver does not import tiled, globus_sdk, numpy, pandas, or pyarrow.",
    [("DESIGN.md", "Layout"), ("src/urisolver/__init__.py", "")],
    [("RELATED_TO", "tiled_internals")],
    aliases=["import urisolver"],
)
c(
    "tiled_internals", "Tiled internals", "architecture",
    "_compat.py imports Tiled internals. The proxy adapters import tiled.adapters.core "
    "and tiled.structures when a server loads them.",
    [("src/urisolver/tiled/_compat.py", ""), ("DESIGN.md", "Layout")],
    [("RELATED_TO", "light_import"), ("USES", "tiled_binder")],
    aliases=["_compat"],
)
c(
    "absolute_uri", "Absolute URI", "contract",
    "split_uri accepts an absolute URI and separates the scheme, the "
    "scheme-specific part, and the fragment.",
    [("src/urisolver/_uriparse.py", "split_uri")],
    [("USES", "registration")],
    refs=["RFC 3986"], aliases=["absolute URI"],
)
c(
    "bind_context", "Bind context", "architecture",
    "A BindContext holds the site, secrets, namespaces, and binder lookup for one session.",
    [("src/urisolver/context.py", "")],
    [("USES", "site"), ("USES", "registration")],
    aliases=["BindContext"],
)
c(
    "node_create", "Node create", "contract",
    "create writes a NodeSpec under a Tiled container and applies the on_conflict rule.",
    [("src/urisolver/tiled/apply.py", "create")],
    [("USES", "on_conflict"), ("PART_OF", "registration")],
    aliases=["apply.create"],
)
c(
    "error_hierarchy", "Error hierarchy", "contract",
    "URIResolverError is the base error. Bind failures, site failures, plugin "
    "failures, and access failures are subtypes.",
    [("src/urisolver/errors.py", "")],
    [("USES", "command_line")],
    aliases=["UrisolverError"],
)

CONCEPTS = C
