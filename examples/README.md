# Examples

`site.example.yaml` is a site file. Its readable and landing paths are relative to that file, and `site check` requires those directories. `reference.py` uses those directories and does not open `target.base_uri`.

`tiled-server.example.yml` names the proxy adapters and a readable-storage path. `reference.py` resolves that path against the file and passes it to a local Tiled server. It does not apply the example API key, sqlite URI, or writable directory.

`reference.py` registers `local/real/sample.npy` through the `local/srvview` symlink and reads the bytes back. `proxy.py` proxies an upstream array or table. It skips unless `URISOLVER_SITE`, `URISOLVER_TILED_URI`, and `URISOLVER_INTO` are set. Registration receives the upstream API key from `TILED_UPSTREAM_API_KEY` for every secret id. The server, not the worker, holds the upstream key: `urisolver proxy credentials` writes the mode-0600 file named by `URISOLVER_PROXY_CREDENTIALS`.

`acquire_globus.py` and `acquire_zenodo.py` copy bytes into the landing area. Each skips unless its live flag is `1` (`URISOLVER_GLOBUS_LIVE` or `URISOLVER_ZENODO`) and `URISOLVER_SITE`, the source URI, and `URISOLVER_INTO` are set.

`globus/login.py` stores the refresh token named by the globus source. It skips unless `URISOLVER_GLOBUS_CLIENT_ID` or `--client-id` is set. The site is `URISOLVER_SITE`, or `site.example.yaml` when that variable is unset. The server example's API key is `localexamplekey`. Tiled rejects a key that is not alphanumeric. `local/catalog` is the writable directory named by that file.
