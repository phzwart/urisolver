#!/usr/bin/env python3
"""Resolve one object on the example Tiled server.

The resolution catalog names the server. The path is one object on that
server. The local secrets manager holds every secret; the catalog selects
the id for this resource, or none.
"""
from urisolver import Context, MemoryDestination, register_resolver, resolve
from urisolver.resolvers.example_tiled import SCHEME, ExampleCatalogResolver
from urisolver.secrets.jsonfile import LocalSecretsManager

register_resolver(SCHEME, ExampleCatalogResolver(), source="example")

uri = "com.urisolver.example.tiled://examples/images/astronaut"
secrets = LocalSecretsManager.default()

with Context(secrets=secrets) as ctx:
    resource = resolve(uri, context=ctx)
    array = resource.materialize(MemoryDestination()).value
    print(array.shape)
    print(array.nbytes)
