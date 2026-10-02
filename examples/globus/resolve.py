#!/usr/bin/env python3
"""Resolve one file on the Globus tutorial collection.

The resolution catalog names the collection. The path is the file on that
collection. The local secrets manager holds every secret; the catalog selects
the id for this resource.
"""
import sys
from pathlib import Path

from urisolver import Context, FileDestination, MemoryDestination, register_resolver, resolve
from urisolver.resolvers.example_globus import SCHEME, ExampleGlobusResolver
from urisolver.secrets.jsonfile import LocalSecretsManager

register_resolver(SCHEME, ExampleGlobusResolver(), source="example")

uri = "com.urisolver.example.globus:///share/godata/file1.txt"
secrets = LocalSecretsManager.default()
dest_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home()

with Context(secrets=secrets) as ctx:
    resource = resolve(uri, context=ctx)
    print(resource.info().size_bytes)
    data = resource.materialize(MemoryDestination()).value
    print(len(data))
    staged = resource.materialize(FileDestination(dest_root / "file1.txt"))
    print(staged.value)
    print(staged.size_bytes)
