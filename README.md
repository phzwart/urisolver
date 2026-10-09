# urisolver

Register a URI as a node on a Tiled server. Workers then read that node with a Tiled client and do not import urisolver.

```bash
pip install urisolver
```

Optional extras install these packages. `tiled` installs `tiled[client]` and PyYAML. `server` installs `tiled[server]` and PyYAML. `globus` installs `globus-sdk` and PyYAML. `dev` installs the test tools, `tiled[all]`, numpy, pandas, pyarrow, and globus-sdk. `examples/reference.py` imports numpy and `tiled.server`. Numpy is part of the `dev` extra.

The examples are in the repository. A source distribution includes `examples/site.example.yaml`.

## List the built-in binders

```python
from urisolver.context import BindContext
from urisolver.site import Site

ctx = BindContext(site=Site.from_mapping({"version": 1}))
print(" ".join(sorted(ctx.binders.protocols())))
```

## Describe a landing area

```python
from urisolver.site import Site

site = Site.from_mapping({
    "version": 1,
    "readable": [{"local": "/data/real", "server": "/data/srv"}],
    "landing": {"local": "/data/real/incoming", "layout": "{protocol}/{sha12}/{name}"},
})
print(site.landing.layout)
```

## Ask which modes exist

```python
from urisolver import Mode

print(" ".join(mode.value for mode in Mode))
```

`examples/reference.py` registers a file on a local Tiled server and reads those bytes back. `examples/proxy.py` skips unless `URISOLVER_SITE`, `URISOLVER_TILED_URI`, and `URISOLVER_INTO` are set. `examples/acquire_globus.py` skips unless `URISOLVER_GLOBUS_LIVE` is `1` and the site, URI, and into values are set. `examples/acquire_zenodo.py` skips unless `URISOLVER_ZENODO` is `1` and the site, URI, and into values are set. The design is in [DESIGN.md](DESIGN.md). Schemes are in [SCHEMES.md](SCHEMES.md).

MIT — see [LICENSE](LICENSE).
