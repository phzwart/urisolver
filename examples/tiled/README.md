# One URI, one object

The local resolution catalog binds a scheme to a server. This process only has a URI. It imports `urisolver`, resolves, and materializes. The server address is in [examples/catalog.yaml](../catalog.yaml).

```yaml
com.urisolver.example.tiled:
  protocol: tiled
  base_uri: https://tiled-demo.nsls2.bnl.gov
  native: [memory]
```

`native` lists the deliveries this server can do without staging: `memory`, `file`, or both. Tiled reads an object into memory directly, so this entry is `memory`. A Globus entry would be `file`. Tier 0 still allows the other delivery; it is staged. `Context(strict_efficiency=True)` refuses that staged path.

## One manager, one id per resource

`LocalSecretsManager` holds every secret, one file per id under `~/.config/urisolver/secrets/`. Resolve picks the id for this resource from the catalog, then asks the manager for that id.

`secret_id` is the credential for every object on the server. `secrets` maps a path prefix to a different id. The longest prefix that is the path, or a parent of it, wins:

```yaml
com.urisolver.example.tiled:
  protocol: tiled
  base_uri: https://tiled-demo.nsls2.bnl.gov
  secret_id: tiled-default
  secrets:
    examples/private: tiled-lab
    examples/private/raw: tiled-raw
```

| Resource path | Secret id |
| --- | --- |
| `examples/images/astronaut` | `tiled-default` |
| `examples/private/scan` | `tiled-lab` |
| `examples/private/raw/frame` | `tiled-raw` |

The public demo sets neither field, so resolve asks for nothing. `resolve.py` still attaches the manager. Secret values stay out of the URI and the catalog.

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

The test skips when `tiled` is not installed. The astronaut fetch runs only when `URISOLVER_TILED_PUBLIC=1`, and only if the server's `/api/v1/` returns HTTP 200.
