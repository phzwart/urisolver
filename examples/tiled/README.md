# One URI, one object

The local resolution catalog binds a scheme to a server. This process only has a URI. It imports `urisolver`, resolves, and materializes. The server address is in [examples/catalog.yaml](../catalog.yaml).

```yaml
com.urisolver.example.tiled:
  protocol: tiled
  base_uri: https://tiled-demo.nsls2.bnl.gov
```

`com.urisolver.example.tiled://examples/images/astronaut` is the node `examples/images/astronaut` on that server: a `512×512×3` array. Another protocol is another scheme in the same file.

`import urisolver` does not load the tiled SDK. The SDK is imported inside urisolver on the first resolve of this scheme.

## Run

From the checkout root:

```bash
pip install -e ".[tiled,dev]"
python examples/tiled/resolve.py
```

A successful run prints:

```text
(512, 512, 3)
786432
```

## Test

```bash
pytest tests/test_tiled_example.py
```

The test skips when `tiled` is not installed. The astronaut fetch needs the public server.
