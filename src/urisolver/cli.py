"""Command line: plan, register, site check, and binders."""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from urisolver.errors import AccessError, BindError, PluginError, SiteConfigError, URIResolverError
from urisolver.redaction import redact_message


def main(argv: list[str] | None = None) -> int:
    """Run one command. Returns a process exit code."""
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else 2
    try:
        return int(args.func(args))
    except (SiteConfigError, PluginError) as exc:
        _error(exc)
        return 5
    except AccessError as exc:
        _error(exc)
        return 4
    except (BindError, URIResolverError) as exc:
        _error(exc)
        return 3
    except Exception as exc:
        _error(exc)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="urisolver")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="describe a bind without writing")
    _bind_args(plan)
    plan.set_defaults(func=_plan)

    register = sub.add_parser("register", help="create the node described by a plan")
    _bind_args(register)
    register.add_argument("--on-conflict", default="return", choices=("return", "error", "replace"))
    register.add_argument("--acquire-timeout", type=float, default=None)
    register.set_defaults(func=_register)

    site = sub.add_parser("site", help="site configuration")
    site_sub = site.add_subparsers(dest="site_command", required=True)
    check = site_sub.add_parser("check", help="load a site file and report errors")
    check.add_argument("path", nargs="?")
    check.set_defaults(func=_site_check)

    binders = sub.add_parser("binders", help="list built-in binders")
    binders.set_defaults(func=_binders)
    return parser


def _bind_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("uri")
    parser.add_argument("--into", required=True, help="Tiled URL, or a path under target.base_uri")
    parser.add_argument("--key", default=None)
    parser.add_argument("--mode", default="auto")
    parser.add_argument("--site", default=None, help="site file; default is URISOLVER_SITE or the user file")


def _plan(args: argparse.Namespace) -> int:
    from urisolver import plan

    ctx = _context(args.site)
    into = _open_into(args.into, ctx)
    planned = plan(args.uri, into, key=args.key, mode=args.mode, context=ctx)
    print(planned.to_json())
    return 0


def _register(args: argparse.Namespace) -> int:
    import json

    from urisolver import register

    ctx = _context(args.site)
    into = _open_into(args.into, ctx)
    binding = register(
        args.uri,
        into,
        key=args.key,
        mode=args.mode,
        on_conflict=args.on_conflict,
        acquire_timeout=args.acquire_timeout,
        context=ctx,
    )
    mode = binding.origin.mode.value if hasattr(binding.origin.mode, "value") else binding.origin.mode
    print(json.dumps({"path": binding.path, "created": binding.created, "mode": mode}, sort_keys=True))
    return 0


def _site_check(args: argparse.Namespace) -> int:
    from urisolver.site import Site

    site = Site.load(args.path)
    print(f"ok sources={len(site.sources)} readable={len(site.readable)}")
    return 0


def _binders(args: argparse.Namespace) -> int:
    del args
    from urisolver.context import BindContext
    from urisolver.site import Site

    ctx = BindContext(site=Site.from_mapping({"version": 1}))
    registry = ctx.binders
    for protocol in sorted(registry.protocols()):
        binder = registry.get(protocol)
        print(f"{protocol} {binder.api_version}")
    return 0


def _context(site_path: str | None):
    from urisolver.context import BindContext
    from urisolver.site import Site

    return BindContext(site=Site.load(site_path))


def _open_into(spec: str, ctx: Any) -> Any:
    from tiled.client import from_uri

    if "://" in spec:
        uri = spec
    else:
        base = ctx.site.target_base_uri if ctx.site is not None else None
        if not isinstance(base, str) or not base:
            raise SiteConfigError("--into path requires target.base_uri")
        uri = base.rstrip("/") + "/" + spec.strip("/")
    api_key = os.environ.get("TILED_API_KEY")
    secret_id = ctx.site.target_secret_id if ctx.site is not None else None
    if not api_key and secret_id and ctx.secrets is not None:
        secret = ctx.secrets.get_secret(secret_id)
        if isinstance(secret, dict) and isinstance(secret.get("api_key"), str):
            api_key = secret["api_key"]
    if api_key and "api_key=" not in uri:
        return from_uri(uri, api_key=api_key)
    return from_uri(uri)


def _error(exc: BaseException) -> None:
    print(redact_message(str(exc)), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
