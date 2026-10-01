#!/usr/bin/env python3
from urisolver import MemoryDestination, resolve

# examples/catalog.yaml binds this scheme to a server.
# The path is one object on that server.
uri = "com.urisolver.example.tiled://examples/images/astronaut"

resource = resolve(uri)
array = resource.materialize(MemoryDestination()).value

print(array.shape)
print(array.nbytes)
