"""Concept catalogue for the urisolver knowledge graph.

Each concept: id, label, kind, definition (paraphrase, how=derived), anchors
(path, symbol) -> verbatim sentences extracted by anchors.py, relations, and
optional RFC citation strings resolved by literature.py.

kind: architecture | contract | protocol | scheme
relations: IS_A, PART_OF, USES, DUAL_OF, SPECIALIZES, EQUIVALENT_TO,
           RELATED_TO, DEFINED_BY, INSTANCE_OF, CONTRASTS_WITH

A markdown anchor's symbol is a section number ("8", "4.1") or a heading
title. A Python anchor's symbol is a function or class name, or "" for the
module docstring.
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
    "absolute_uri", "Absolute URI", "architecture",
    "A URI that already has a scheme. A reference without one is rejected, and "
    "RFC 3986 relative-reference resolution is not this package's job.",
    [("DESIGN.md", "1")],
    [("RELATED_TO", "scheme_dispatch"), ("RELATED_TO", "fragment")],
    refs=["RFC 3986"], aliases=["absolute URI"],
)
c(
    "scheme_dispatch", "Scheme dispatch", "architecture",
    "The core checks scheme grammar, compares schemes case-insensitively, and "
    "hands the original URI to the resolver registered for that scheme.",
    [("DESIGN.md", "4"), ("src/urisolver/_uriparse.py", "split_uri")],
    [("USES", "absolute_uri"), ("USES", "uri_equivalence"), ("USES", "registry")],
    refs=["RFC 3986"], aliases=["scheme dispatch"],
)
c(
    "fragment", "URI fragment", "contract",
    "The fragment is split off before dispatch and is never an identifier. "
    "Resolvers must not turn it into a path, a key, or a selection.",
    [("DESIGN.md", "4.3"), ("src/urisolver/context.py", "_inherit_fragment")],
    [("PART_OF", "absolute_uri"), ("CONTRASTS_WITH", "selection")],
    refs=["RFC 3986"], aliases=["fragment"],
)
c(
    "opaque_payload", "Opaque payload", "contract",
    "When a resolver marks its payload opaque, logs, errors, reprs, and "
    "temporary paths show the scheme plus a digest, not the payload.",
    [("DESIGN.md", "4.1"), ("src/urisolver/redaction.py", "")],
    [("USES", "redaction")],
    aliases=["opaque payload"],
)
c(
    "redaction", "Redaction", "contract",
    "Secrets, credential-bearing backend errors, and opaque URI payloads are "
    "stripped before they are logged or chained onto an exception.",
    [("DESIGN.md", "24.1"), ("src/urisolver/redaction.py", "")],
    [("RELATED_TO", "opaque_payload"), ("RELATED_TO", "secrets_provider")],
    aliases=["redaction"],
)
c(
    "scheme_naming", "Scheme naming", "contract",
    "A private scheme uses a reversed domain the deployer controls. A short "
    "unregistered name is not a conforming choice.",
    [("DESIGN.md", "4.2")],
    [("PART_OF", "scheme_definition")],
    refs=["RFC 7595"], aliases=["reverse-DNS scheme"],
)
c(
    "uri_equivalence", "URI equivalence", "contract",
    "The core case-folds the scheme and does not otherwise normalize. "
    "Percent-encoding, dot segments, and default ports stay the resolver's problem.",
    [("DESIGN.md", "4.4"), ("src/urisolver/_uriparse.py", "scheme_normalized")],
    [("PART_OF", "scheme_dispatch")],
    refs=["RFC 3986"], aliases=["normalization"],
)
c(
    "scheme_definition", "Scheme definition", "contract",
    "Every scheme a deployment registers needs a page in SCHEMES.md stating "
    "syntax, operations, and security before the scheme is usable.",
    [("DESIGN.md", "4.5"), ("SCHEMES.md", "Registered schemes")],
    [("USES", "scheme_naming")],
    refs=["RFC 7595"], aliases=["SCHEMES.md"],
)
c(
    "public_api", "Public resolve API", "architecture",
    "Context.resolve is the real entry point. The module-level resolve function "
    "is a process-default convenience that library code should not rely on.",
    [("DESIGN.md", "5"), ("src/urisolver/api.py", "resolve")],
    [("USES", "resolve_context")],
    aliases=["resolve"],
)
c(
    "resolve_context", "Resolve context", "architecture",
    "The context owns resolver lifetime, the secrets provider, the memory limit, "
    "and session reuse. Closing it invalidates resources it produced.",
    [("DESIGN.md", "23"), ("src/urisolver/context.py", "")],
    [("USES", "registry"), ("USES", "secrets_provider"), ("USES", "strict_efficiency")],
    aliases=["Context", "ResolveContext"],
)
c(
    "resolved_resource", "Resolved resource", "protocol",
    "The object a resolver returns. It keeps the caller's URI and the concrete "
    "URI, and it is bound to the context that created it.",
    [("DESIGN.md", "6"), ("src/urisolver/protocols.py", "")],
    [("USES", "tier_0"), ("USES", "resource_info")],
    aliases=["ResolvedResource"],
)
c(
    "resource_info", "Resource info", "contract",
    "A cheap description filled in at resolve time: kind, existence, and "
    "optional size or shape. It must not pull the bulk bytes.",
    [("DESIGN.md", "7"), ("src/urisolver/info.py", "")],
    [("PART_OF", "resolved_resource")],
    aliases=["ResourceInfo", "Kind"],
)
c(
    "tier_0", "Tier 0 baseline", "contract",
    "info and materialize are present on every resource. Policy may make them "
    "fail, but it may not hide them.",
    [("DESIGN.md", "8")],
    [("PART_OF", "resolved_resource"), ("USES", "materialize"), ("USES", "resource_info")],
    aliases=["Tier 0", "baseline contract"],
)
c(
    "materialize", "Materialize", "contract",
    "Delivery of a resource into a file or memory destination. Resolve itself "
    "does not download or convert; this call does.",
    [("DESIGN.md", "8"), ("src/urisolver/results.py", "")],
    [
        ("USES", "file_destination"), ("USES", "memory_destination"),
        ("USES", "selection"), ("USES", "materialized_result"),
    ],
    aliases=["materialize"],
)
c(
    "canonical_media_type", "Canonical media type", "contract",
    "The resolver names the byte encoding for a structured resource. The core "
    "does not invent one.",
    [("DESIGN.md", "8.1")],
    [("PART_OF", "tier_0"), ("USES", "resource_info")],
    aliases=["canonical_media_type"],
)
c(
    "form", "Form", "contract",
    "What the caller wants back from memory delivery: a backend-native object, "
    "bytes, or an optional array or table.",
    [("DESIGN.md", "9"), ("src/urisolver/destinations.py", "")],
    [("PART_OF", "memory_destination")],
    aliases=["Form"],
)
c(
    "materialized_result", "Materialized result", "contract",
    "The value plus enough URI and strategy metadata for an outside provenance "
    "layer to record what was staged.",
    [("DESIGN.md", "10"), ("src/urisolver/results.py", "")],
    [("USES", "form"), ("USES", "materialization_strategy")],
    aliases=["MaterializedResult"],
)
c(
    "materialization_strategy", "Materialization strategy", "contract",
    "A short token on the result that says whether the backend did the work, "
    "the bytes were sliced locally, or a reference was returned.",
    [("DESIGN.md", "10.1")],
    [("PART_OF", "materialized_result")],
    aliases=["strategy", "read-then-select"],
)
c(
    "strict_efficiency", "Strict efficiency", "contract",
    "When the context flag is set, a delivery that would read the whole object "
    "and slice it locally is refused before the transfer starts.",
    [("DESIGN.md", "10.1")],
    [("USES", "materialization_strategy"), ("PART_OF", "resolve_context")],
    aliases=["strict_efficiency"],
)
c(
    "file_destination", "File destination", "contract",
    "A caller-chosen path. Successful delivery leaves that path in place, "
    "written via a temporary name and an atomic replace.",
    [("DESIGN.md", "11"), ("src/urisolver/destinations.py", "")],
    [("USES", "reference_policy")],
    aliases=["FileDestination"],
)
c(
    "reference_policy", "Reference policy", "contract",
    "Copy is the default. A link or in-place path is returned only when the "
    "caller asked, and failure cleanup must not delete that source.",
    [("DESIGN.md", "11.2")],
    [("PART_OF", "file_destination")],
    aliases=["ReferencePolicy", "is_reference"],
)
c(
    "memory_destination", "Memory destination", "contract",
    "An in-memory delivery in a chosen form, bounded by the destination or "
    "context byte limit.",
    [("DESIGN.md", "12"), ("src/urisolver/destinations.py", "")],
    [("CONTRASTS_WITH", "file_destination"), ("USES", "form")],
    aliases=["MemoryDestination"],
)
c(
    "selection", "Selection", "contract",
    "The only portable subsetting in the baseline is numpy basic indexing, plus "
    "a column list for tables. Anything else is not a core query language.",
    [("DESIGN.md", "13"), ("src/urisolver/selection.py", "")],
    [("USES", "native_selection"), ("PART_OF", "materialize")],
    aliases=["basic indexing"],
)
c(
    "native_selection", "Native selection", "contract",
    "A wrapper that passes a backend-specific query through untouched. Using it "
    "means the caller has accepted protocol coupling.",
    [("DESIGN.md", "13"), ("src/urisolver/selection.py", "Native")],
    [("IS_A", "selection"), ("CONTRASTS_WITH", "tier_0")],
    aliases=["Native"],
)
c(
    "tier_1_facet", "Tier 1 facet", "protocol",
    "An optional declared interface borrowed from an existing library, so "
    "generic code can do more than fetch the whole object.",
    [("DESIGN.md", "14"), ("src/urisolver/protocols.py", "")],
    [("PART_OF", "resolved_resource"), ("CONTRASTS_WITH", "tier_0")],
    aliases=["facet", "Tier 1"],
)
c(
    "stream_facet", "Stream facet", "protocol",
    "A binary reader for resources that can be opened as a byte stream, "
    "including range reads where the backend supports them.",
    [("DESIGN.md", "14"), ("src/urisolver/protocols.py", "")],
    [("PART_OF", "tier_1_facet")],
    aliases=["stream"],
)
c(
    "array_facet", "Array facet", "protocol",
    "Shape, dtype, and numpy basic indexing on an array resource. Fancy "
    "indexing is not part of the facet.",
    [("DESIGN.md", "14.2"), ("src/urisolver/protocols.py", "")],
    [("PART_OF", "tier_1_facet"), ("USES", "selection")],
    aliases=["array"],
)
c(
    "table_facet", "Table facet", "protocol",
    "Column names and an optional row count, with a read that can ask for a "
    "subset of columns.",
    [("DESIGN.md", "14"), ("src/urisolver/protocols.py", "")],
    [("PART_OF", "tier_1_facet")],
    aliases=["table"],
)
c(
    "container_facet", "Container facet", "protocol",
    "Named children of a container, each itself a resolved resource. Keys are "
    "single path segments, not a path traversal API.",
    [("DESIGN.md", "14.4"), ("src/urisolver/protocols.py", "")],
    [("PART_OF", "tier_1_facet")],
    aliases=["container"],
)
c(
    "tier_2_native", "Tier 2 native pass-through", "protocol",
    "Backend operations the wrapper does not rename or reinterpret. Callers "
    "who use them accept that the call is protocol-specific.",
    [("DESIGN.md", "15")],
    [("PART_OF", "resolved_resource"), ("CONTRASTS_WITH", "tier_0")],
    aliases=["Tier 2", "native"],
)
c(
    "capability", "Capability", "contract",
    "supports is the one answer for what a resource can do. capabilities and "
    "attribute lookup report that same set.",
    [("DESIGN.md", "15.1")],
    [("PART_OF", "tier_2_native")],
    aliases=["supports", "capabilities"],
)
c(
    "policy_filtering", "Policy filtering", "architecture",
    "A resolver may hide backend operations. That filter is a convenience in "
    "this process, not a security boundary.",
    [("DESIGN.md", "16")],
    [("CONTRASTS_WITH", "capability"), ("USES", "tier_2_native")],
    aliases=["policy"],
)
c(
    "resolver", "Resolver", "protocol",
    "The plugin that interprets one scheme: sessions, credentials, info, and "
    "materialize. The core does not parse the scheme-specific part for it.",
    [("DESIGN.md", "17"), ("src/urisolver/protocols.py", "")],
    [("USES", "tier_0"), ("USES", "registry")],
    aliases=["Resolver"],
)
c(
    "registry", "Registry", "architecture",
    "The map from scheme to resolver. Two schemes may share a protocol and "
    "still point at different servers and credentials.",
    [("DESIGN.md", "18"), ("src/urisolver/registry.py", "")],
    [("USES", "resolver"), ("RELATED_TO", "plugin")],
    aliases=["register_resolver"],
)
c(
    "plugin", "Resolver plugin", "architecture",
    "An installed distribution registers schemes through entry points. Those "
    "points are listed at import and imported on first use.",
    [("DESIGN.md", "19.1"), ("src/urisolver/plugins.py", "")],
    [("USES", "registry")],
    aliases=["entry point"],
)
c(
    "namespace_indirection", "Namespace indirection", "architecture",
    "A namespace URI asks which concrete URI an identifier maps to for this "
    "caller right now. That is not RFC 3986 reference resolution.",
    [("DESIGN.md", "20"), ("src/urisolver/namespaces/base.py", "")],
    [("USES", "resolver"), ("RELATED_TO", "scheme_dispatch")],
    refs=["RFC 7595"], aliases=["namespace resolution"],
)
c(
    "namespace_service", "Namespace service", "architecture",
    "A self-hosted POST /resolve endpoint. The process is urisolver's; the "
    "routing function is the deployer's.",
    [("DESIGN.md", "21"), ("src/urisolver/namespaces/server.py", ""), ("src/urisolver/cli.py", "")],
    [("USES", "namespace_indirection")],
    aliases=["urisolver serve"],
)
c(
    "bespoke_routing", "Bespoke routing", "architecture",
    "Persistent names stay small because the private routing rules live in the "
    "deployer's resolver, not in the core.",
    [("DESIGN.md", "22")],
    [("PART_OF", "namespace_indirection")],
    aliases=["router"],
)
c(
    "secrets_provider", "Secrets provider", "protocol",
    "A get_secret lookup by id. The core never stores the values, and the "
    "resolver asks only for the id the catalog selected.",
    [("DESIGN.md", "24"), ("src/urisolver/secrets/base.py", "")],
    [("PART_OF", "resolve_context")],
    aliases=["SecretsProvider"],
)
c(
    "error_model", "Error model", "contract",
    "Failures are typed by stage: bad URI, unknown scheme, access, namespace, "
    "materialize, selection, secrets, and plugins.",
    [("DESIGN.md", "25"), ("src/urisolver/errors.py", "URIResolverError")],
    [("RELATED_TO", "policy_filtering")],
    aliases=["URIResolverError"],
)
c(
    "async_reservation", "Async names", "contract",
    "aresolve and amaterialize are reserved so later async support does not "
    "fork the API. Sync callers do not need an event loop.",
    [("DESIGN.md", "26"), ("src/urisolver/api.py", "aresolve")],
    [("RELATED_TO", "public_api")],
    aliases=["aresolve"],
)
c(
    "file_scheme", "file scheme", "scheme",
    "The built-in resolver for local paths: stat for info, a stream facet, and "
    "byte contents for memory delivery.",
    [("DESIGN.md", "27.1"), ("src/urisolver/resolvers/file.py", "")],
    [("INSTANCE_OF", "resolver"), ("USES", "file_destination")],
    aliases=["file:"],
)
c(
    "tiled_resolver", "Tiled resolver", "scheme",
    "An optional resolver that reads a Tiled node. The server address and the "
    "secret id come from the local resolution catalog.",
    [
        ("DESIGN.md", "27.2"),
        ("src/urisolver/resolvers/tiled.py", ""),
        ("src/urisolver/resolvers/example_tiled.py", "ExampleCatalogResolver"),
    ],
    [("INSTANCE_OF", "resolver"), ("USES", "resolution_catalog"), ("USES", "secrets_provider")],
    refs=["RFC 7595"], aliases=["tiled"],
)
c(
    "globus_resolver", "Globus resolver", "scheme",
    "An optional Transfer resolver for one collection path. File delivery is a "
    "copy; memory delivery stages through the catalog's staging collection.",
    [
        ("DESIGN.md", "27.3"),
        ("SCHEMES.md", "com.urisolver.example.globus"),
        ("src/urisolver/resolvers/globus.py", ""),
        ("src/urisolver/resolvers/example_globus.py", "ExampleGlobusResolver"),
    ],
    [("INSTANCE_OF", "resolver"), ("USES", "resolution_catalog"), ("USES", "file_destination")],
    refs=["RFC 7595"], aliases=["Globus"],
)
c(
    "cryoet_example", "CryoET example", "scheme",
    "An example resolver for one public object on a CryoET Data Portal origin. "
    "The origin comes from the local resolution catalog. A .zarr path is an "
    "OME-Zarr multiscale array; an .mrc path is a file whose size comes from HEAD.",
    [
        ("SCHEMES.md", "com.urisolver.example.cryoet"),
        ("src/urisolver/resolvers/example_cryoet.py", ""),
        ("src/urisolver/resolvers/example_cryoet.py", "ExampleCryoetResolver"),
    ],
    [
        ("INSTANCE_OF", "resolver"),
        ("USES", "resolution_catalog"),
        ("USES", "file_destination"),
        ("USES", "selection"),
    ],
    refs=["RFC 7595"], aliases=["cryoet", "OME-Zarr"],
)
c(
    "resolution_catalog", "Resolution catalog", "architecture",
    "A local YAML file that binds a scheme to a server, a secret id, and "
    "optional path-prefix overrides. Secret values are not in the file.",
    [
        ("SCHEMES.md", "Registered schemes"),
        ("src/urisolver/resolvers/_catalog.py", ""),
        ("src/urisolver/resolvers/_catalog.py", "select_secret_id"),
    ],
    [("USES", "secrets_provider"), ("USES", "scheme_definition")],
    aliases=["catalog"],
)
c(
    "conformance_baseline", "Conformance baseline", "contract",
    "A resolver-agnostic test suite shipped with the package. A plugin that "
    "does not pass it is not a conforming resolver.",
    [
        ("DESIGN.md", "Baseline conformance suite (the important one)"),
        ("src/urisolver/testing/baseline.py", ""),
    ],
    [("DEFINED_BY", "tier_0")],
    aliases=["run_baseline_suite"],
)

CONCEPTS = C
