#!/usr/bin/env python3
"""Print scale 2 of one public CryoET tomogram.

The resolution catalog names the portal origin. The path is one OME-Zarr
group on that origin. Scale 2's shape and uncompressed size come from the
group metadata. This script does not download voxels.
"""
from urisolver import Context, register_resolver, resolve
from urisolver.resolvers.example_cryoet import SCHEME, ExampleCryoetResolver

register_resolver(SCHEME, ExampleCryoetResolver(), source="example")

uri = (
    "com.urisolver.example.cryoet:///10000/TS_026/Reconstructions/"
    "VoxelSpacing13.480/Tomograms/100/TS_026.zarr"
)

with Context() as ctx:
    resource = resolve(uri, context=ctx)
    level = resource.facet("array").levels[2]
    print(level.shape)
    print(level.nbytes)
