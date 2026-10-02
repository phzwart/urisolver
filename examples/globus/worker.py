#!/usr/bin/env python3
"""Stage the tutorial file in a child that never opens the secret file.

The parent reads the secret once and answers lookups on a pipe. The child
imports urisolver, resolves, and materializes. It does not handle tokens.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

from urisolver import Context, FileDestination, resolve
from urisolver.exchange import StreamExchange, serve_stream
from urisolver.secrets.exchange import ExchangeSecrets, secrets_handler
from urisolver.secrets.jsonfile import LocalSecretsManager

URI = "com.urisolver.example.globus:///share/godata/file1.txt"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--worker" in args:
        fd = int(args[args.index("--exchange-fd") + 1])
        dest = args[args.index("--worker") + 1]
        return _worker(dest, fd)
    dest = args[0] if args else str(Path.home() / "file1.txt")
    return _parent(dest)


def _parent(dest: str) -> int:
    store = LocalSecretsManager.default()
    parent, child = socket.socketpair()
    parent_stream = parent.makefile("rwb", buffering=0)
    thread = threading.Thread(
        target=serve_stream,
        args=(parent_stream, secrets_handler(store.get_secret)),
        daemon=True,
    )
    thread.start()
    fd = child.fileno()
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker", dest, "--exchange-fd", str(fd)],
        pass_fds=(fd,),
    )
    child.close()
    thread.join(timeout=5)
    parent_stream.close()
    parent.close()
    return proc.returncode


def _worker(dest: str, fd: int) -> int:
    stream = os.fdopen(fd, "r+b", buffering=0)
    secrets = ExchangeSecrets(StreamExchange(stream))
    try:
        with Context(secrets=secrets) as ctx:
            resource = resolve(URI, context=ctx)
            result = resource.materialize(FileDestination(dest))
        print(result.value)
        print(result.size_bytes)
    except Exception:
        print("delivery failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
