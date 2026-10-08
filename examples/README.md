# Examples

`site.example.yaml` is a site file. `tiled-server.example.yml` registers the proxy adapters on a Tiled server.

`reference.py` references a file the server can already read. `proxy.py` proxies an upstream array or table. `acquire_globus.py` and `acquire_zenodo.py` copy bytes into the landing area; they skip unless `URISOLVER_GLOBUS_LIVE=1` or `URISOLVER_ZENODO=1`.

`globus/login.py` stores the refresh token named by the globus source. It skips unless `URISOLVER_GLOBUS_CLIENT_ID` is set.
