#!/usr/bin/env python3
"""Hold the secrets store and start one worker for one URI.

Each job gets its own loopback endpoint, bearer token, and allowed set.
The endpoint closes when the worker exits. This process does not fetch data.
A tunnel is the deployer's transport; this script only prints and runs ssh.
"""
from __future__ import annotations

import argparse
import os
import secrets
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

_SRC = Path(os.path.abspath(__file__)).parents[2] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from urisolver.errors import SecretLookupError  # noqa: E402
from urisolver.exchange import serve_http  # noqa: E402
from urisolver.secrets.exchange import secrets_handler  # noqa: E402
from urisolver.secrets.jsonfile import LocalSecretsManager  # noqa: E402

WORKER = Path(os.path.abspath(__file__)).parent / "worker.py"


def job_lookup(store: LocalSecretsManager, allowed: set[str]):
    """Return a lookup that refuses ids outside *allowed*."""

    def lookup(secret_id: str):
        if secret_id not in allowed:
            raise SecretLookupError("secret lookup refused")
        return store.get_secret(secret_id)

    return lookup


def _dest_for(uri: str, dest: str | None) -> str:
    if dest:
        return dest
    name = uri.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    if not name or ":" in name:
        return "staged"
    return name


def run_job(
    uri: str,
    dest: str,
    *,
    allowed: set[str],
    local: bool,
    ssh_host: str | None,
) -> int:
    store = LocalSecretsManager.default()
    token = secrets.token_urlsafe(32)
    running = serve_http(secrets_handler(job_lookup(store, allowed)), token=token)
    try:
        print(f"endpoint {running.url}", file=sys.stderr)
        port = urlparse(running.url).port
        worker_url = f"http://127.0.0.1:{port}/"
        if local:
            proc = subprocess.run(
                [sys.executable, str(WORKER), uri, dest, worker_url],
                input=token + "\n",
                text=True,
            )
            return proc.returncode
        if not ssh_host:
            print("pass --local or --ssh HOST", file=sys.stderr)
            return 2
        ssh_argv = [
            "ssh",
            "-R",
            f"{port}:127.0.0.1:{port}",
            ssh_host,
            sys.executable,
            str(WORKER),
            uri,
            dest,
            worker_url,
        ]
        print(shlex.join(ssh_argv), file=sys.stderr)
        proc = subprocess.run(ssh_argv, input=token + "\n", text=True)
        return proc.returncode
    finally:
        running.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="run the worker on this machine")
    parser.add_argument("--ssh", metavar="HOST", help="run the worker on HOST through ssh -R")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="SECRET_ID",
        help="secret id this job may obtain (repeatable)",
    )
    parser.add_argument("uri")
    parser.add_argument("dest", nargs="?")
    args = parser.parse_args(argv)
    if args.local and args.ssh:
        parser.error("pass only one of --local and --ssh")
    if not args.local and not args.ssh:
        parser.error("pass --local or --ssh HOST")
    return run_job(
        args.uri,
        _dest_for(args.uri, args.dest),
        allowed=set(args.allow),
        local=args.local,
        ssh_host=args.ssh,
    )


if __name__ == "__main__":
    raise SystemExit(main())
