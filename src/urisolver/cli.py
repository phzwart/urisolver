"""CLI: urisolver serve (§21)."""
from __future__ import annotations
import argparse
import sys

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="urisolver")
    sub = parser.add_subparsers(dest="command", required=True)
    serve_p = sub.add_parser("serve", help="Run a self-hosted namespace service")
    serve_p.add_argument("--namespace", required=True)
    serve_p.add_argument("--resolver", required=True, help="dotted path module:attr")
    serve_p.add_argument("--auth", default=None)
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8765)
    serve_p.add_argument("--detail", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    return 2

def _serve(args: argparse.Namespace) -> int:
    from urisolver.namespaces.server import NullAuthenticator, ServerConfig, load_object, serve
    resolver = load_object(args.resolver)
    auth = load_object(args.auth) if args.auth else NullAuthenticator()
    if isinstance(resolver, type):
        resolver = resolver()
    if isinstance(auth, type):
        auth = auth()
    # ServerConfig field names may be include_detail or include_detail
    kwargs = dict(namespace=args.namespace, resolver=resolver, authenticator=auth, host=args.host, port=args.port)
    import inspect
    from urisolver.namespaces.server import ServerConfig as SC
    params = inspect.signature(SC).parameters
    if "include_detail" in params:
        kwargs["include_detail"] = args.detail
    elif "include_detail" in params:
        kwargs["include_detail"] = args.detail
    config = SC(**kwargs)
    print(f"serving namespace {args.namespace!r} on http://{args.host}:{args.port}/resolve", file=sys.stderr)
    serve(config, blocking=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
