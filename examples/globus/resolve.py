#!/usr/bin/env python3
"""Resolve one file on the Globus tutorial collection.

examples/catalog.yaml names the collection. The path is the file on that
collection. Credentials come from ~/.config/urisolver/secrets/.
"""
from pathlib import Path
import sys

from urisolver import Context, FileDestination, MemoryDestination, resolve
from urisolver.secrets.jsonfile import JsonFileSecrets

uri = "com.urisolver.example.globus:///share/godata/file1.txt"
secrets = JsonFileSecrets(Path.home() / ".config" / "urisolver" / "secrets")
dest_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home()

with Context(secrets=secrets) as ctx:
    resource = resolve(uri, context=ctx)
    print(resource.info().size_bytes)
    data = resource.materialize(MemoryDestination()).value
    print(len(data))
    staged = resource.materialize(FileDestination(dest_root / "file1.txt"))
    print(staged.value)
    print(staged.size_bytes)
