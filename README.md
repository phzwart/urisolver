# urisolver

Register a URI as a node on a Tiled server. Workers then read that node with a Tiled client and do not import urisolver.

```bash
pip install urisolver
```

Tiled, the proxy server, and Globus are extras: `pip install "urisolver[tiled,server,globus]"`.

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

`examples/reference.py` registers a file on a local Tiled server and reads those bytes back. `examples/proxy.py`, `examples/acquire_globus.py`, and `examples/acquire_zenodo.py` skip unless their environment variable is set. The design is in [DESIGN.md](DESIGN.md). Schemes are in [SCHEMES.md](SCHEMES.md).

MIT — see [LICENSE](LICENSE).
