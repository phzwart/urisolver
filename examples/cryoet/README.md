# One URI, one tomogram

The local resolution catalog binds a scheme to a public HTTPS origin. This process only has a URI. It imports `urisolver`, resolves, and reads scale metadata. The origin is in [examples/catalog.yaml](../catalog.yaml).

```yaml
com.urisolver.example.cryoet:
  protocol: cryoet
  base_uri: https://files.cryoetdataportal.cziscience.com
  native: [memory, file]
```

`native` lists deliveries that do not stage through another service. An array read is `memory`. An object GET, including a zarr store copy and an MRC file copy, is `file`. The portal objects are anonymous, so the entry has no `secret_id`.

`com.urisolver.example.cryoet:///10000/TS_026/Reconstructions/VoxelSpacing13.480/Tomograms/100/TS_026.zarr` is the OME-Zarr reconstruction of dataset 10000, run TS_026. Axes are stored z, y, x. Scale 0 is `(1000, 928, 960)` float32. Scale 2 is `(250, 232, 240)`, 55,680,000 bytes uncompressed. The MRC sibling is the same key with `.mrc` instead of `.zarr` (Content-Length 1,781,761,024). SCHEMES.md has the scheme page.

`import urisolver` does not load this resolver or `zarr`. The script registers the resolver. `zarr` is imported on the first array read, not when metadata is fetched.

## Run

From the checkout root:

```bash
pip install -e ".[cryoet]"
python examples/cryoet/resolve.py
```

A successful run prints scale 2 and does not download chunks:

```text
(250, 232, 240)
55680000
```

Reading that scale is one compressed chunk (about 26 MB):

```python
from urisolver import MemoryDestination
from urisolver.selection import Native

array = resource.materialize(MemoryDestination(), selection=Native(2)).value
```

Basic indexing is pushed to the chosen scale (`strategy="native-selection"`):

```python
array = resource.materialize(
    MemoryDestination(),
    selection=Native((2, (slice(0, 8), slice(0, 8), slice(0, 8)))),
).value
```

Scale 2 is a single chunk, so a small slice still transfers that chunk. `FileDestination` on the `.zarr` copies the store. `FileDestination` on the `.mrc` copies that one object. `MemoryDestination()` with no selection reads scale 0 and raises `MemoryLimitError` under the default 2 GiB limit.

## Test

```bash
pytest tests/test_cryoet_example.py
```

Metadata against the portal runs only when `URISOLVER_CRYOET=1`.
