"""tiled: binder. Return an existing node, or proxy an upstream array or table."""
from __future__ import annotations

from dataclasses import asdict
from enum import Enum
from typing import Any
from urllib.parse import unquote, urlparse

from urisolver._uriparse import split_uri
from urisolver.bind import BinderPlan, Mode, NodeSpec
from urisolver.context import BindContext
from urisolver.errors import BindError, InvalidURIError, SiteConfigError
from urisolver.redaction import sanitize_exception
from urisolver.site import Source, select_secret_id

_MODES = (Mode.EXISTING, Mode.REFERENCE, Mode.PROXY, Mode.ACQUIRE)


class TiledBinder:
    """Bind a node that already lives on a Tiled server."""

    api_version = 2
    protocol = "tiled"
    opaque_payload = False

    def validate_source(self, source: Source) -> None:
        base = source.params.get("base_uri")
        if not isinstance(base, str) or not base:
            raise SiteConfigError(f"sources.{source.scheme}.base_uri is required")

    def feasible_modes(
        self, uri: str, source: Source | None, into: Any, ctx: BindContext
    ) -> list[tuple[Mode, str | None]]:
        if source is None:
            missing = "tiled URIs need a source"
            return [(mode, missing) for mode in _MODES]
        reasons = {
            Mode.EXISTING: "source base URI is not the target server",
            Mode.REFERENCE: "tiled nodes are not files in readable storage",
            Mode.PROXY: "source proxy is not enabled",
            Mode.ACQUIRE: "landing is not configured",
        }
        try:
            node = _open_node(uri, source, ctx)
        except Exception as exc:
            message = str(exc) or "upstream node is not readable"
            return [(mode, message) for mode in _MODES]
        family = _family(node)
        if _same_server(source, into):
            reasons[Mode.EXISTING] = None
        if source.params.get("proxy") and family in {"array", "table"}:
            reasons[Mode.PROXY] = None
        elif source.params.get("proxy"):
            reasons[Mode.PROXY] = f"structure family {family!r} cannot be proxied"
        if ctx.site is not None and ctx.site.landing is not None and family in {"array", "table"}:
            reasons[Mode.ACQUIRE] = None
        elif family not in {"array", "table"}:
            reasons[Mode.ACQUIRE] = f"structure family {family!r} cannot be acquired"
        return [(mode, reasons[mode]) for mode in _MODES]

    def plan(
        self,
        uri: str,
        source: Source | None,
        into: Any,
        ctx: BindContext,
        *,
        mode: Mode,
        key: str | None,
    ) -> BinderPlan:
        if source is None:
            raise BindError("tiled URIs need a source")
        segments = _path_segments(uri)
        node = _open_node(uri, source, ctx)
        family = _family(node)
        if mode is Mode.EXISTING:
            return BinderPlan(existing_path="/" + "/".join(segments))
        if mode is not Mode.PROXY:
            raise BindError(f"tiled binder cannot plan mode {mode.value} yet")
        from tiled.structures.data_source import Asset, DataSource, Management

        from urisolver.tiled_server.proxy import PROXY_MIMETYPES

        base = _normalize_base(str(source.params["base_uri"]))
        data_source = DataSource(
            structure_family=family,
            mimetype=PROXY_MIMETYPES[family],
            structure=_plain(asdict(node.structure())),
            parameters={"path": "/".join(segments)},
            management=Management.external,
            assets=[Asset(data_uri=base, is_directory=False, parameter="data_uri")],
        )
        specs = []
        for spec in node.specs or []:
            specs.append(spec if isinstance(spec, dict) else asdict(spec))
        derived = segments[-1] if segments else None
        return BinderPlan(
            node=NodeSpec(
                key=_safe_key(key, derived),
                structure_family=family,
                data_sources=(_plain(asdict(data_source)),),
                metadata={"upstream": dict(node.metadata)},
                specs=tuple(_plain(spec) for spec in specs),
            )
        )

    def acquire(self, acquisition, ctx: BindContext, *, timeout: float | None):
        raise NotImplementedError("tiled acquire is implemented with landing exports")


def _open_node(uri: str, source: Source, ctx: BindContext):
    segments = _path_segments(uri)
    client = _client(source, ctx, segments)
    node = client
    try:
        for part in segments:
            node = node[part]
        return node
    except Exception as exc:
        wrapped = sanitize_exception(exc, wrapper_type=BindError, message=str(exc) or "upstream node is not readable")
        raise wrapped from None


def _client(source: Source, ctx: BindContext, segments: list[str]):
    base = str(source.params["base_uri"]).rstrip("/")
    prefixes = source.params.get("secrets") or {}
    if not isinstance(prefixes, dict):
        prefixes = {}
    secret_id = select_secret_id(
        "/" + "/".join(segments),
        default=source.params.get("secret_id"),
        by_prefix=prefixes,
    )

    def factory():
        from tiled.client import from_uri

        api_key = _api_key(ctx, secret_id)
        return from_uri(base, api_key=api_key) if api_key else from_uri(base)

    return ctx.cache(("tiled", base, secret_id), factory)


def _api_key(ctx: BindContext, secret_id: str | None) -> str | None:
    if not secret_id or ctx.secrets is None:
        return None
    secret = ctx.secrets.get_secret(secret_id)
    value = secret.get("api_key") if isinstance(secret, dict) else None
    return value if isinstance(value, str) and value else None


def _same_server(source: Source, into: Any) -> bool:
    context = getattr(into, "context", None)
    api_uri = getattr(context, "api_uri", None)
    if api_uri is None:
        return False
    return _normalize_base(str(source.params.get("base_uri"))) == _normalize_base(str(api_uri))


def _family(node: Any) -> str:
    family = node.item["attributes"]["structure_family"]
    return family.value if isinstance(family, Enum) else str(family)


def _normalize_base(uri: str) -> str:
    parsed = urlparse(uri)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = host.split(":")[0]
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}{parsed.path.rstrip('/')}"


def _safe_key(explicit: str | None, derived: str | None) -> str:
    key = explicit or derived
    if not key or key in {".", ".."} or "/" in key:
        raise BindError(f"derived key {key!r} is not a valid Tiled key; pass key=")
    return key


def _path_segments(uri: str) -> list[str]:
    """Percent-decode each path segment once."""
    parts = split_uri(uri)
    body = parts.body
    if len(body) >= 2 and body[0:2] == "//":
        parsed = urlparse("http:" + body)
        path = f"{parsed.netloc}{parsed.path}"
    else:
        path = body
    path = path.split("?", 1)[0].split("#", 1)[0].strip("/")
    if not path:
        return []
    raw = path.split("/")
    if any(segment == "" for segment in raw):
        raise InvalidURIError(f"empty path segment in {uri!r}")
    return [unquote(segment) for segment in raw]


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value
