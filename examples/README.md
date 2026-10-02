# Examples

Each demo starts from a URI. urisolver turns it into a file or an in-memory object. The caller does not branch on the backend.

Start with tiled, then testdrive, then globus.

`examples/catalog.yaml` maps a scheme name to a server. An explicit path or `$URISOLVER_CATALOG` replaces that file. Otherwise `~/.config/urisolver/catalog.yaml` is merged over it. The example Tiled and Globus schemes are not package entry points. Each script registers its resolver before `resolve`. The Zenodo resolver stays inside the testdrive script.

## tiled

Needs the network and the `[tiled]` extra. The public demo needs no credential.

[examples/tiled/resolve.py](tiled/resolve.py) resolves `com.urisolver.example.tiled://examples/images/astronaut` and prints the array shape and its byte count. The live test is gated on `URISOLVER_TILED_PUBLIC=1`.

See [examples/tiled/README.md](tiled/README.md).

## testdrive

The local `file:` story needs a checkout and nothing else. The Zenodo story needs the network and `URISOLVER_ZENODO=1`.

A parent process ships only a URI. The worker calls `resolve`, `info()`, and `materialize(FileDestination)`, then prints a JSON report. The same worker carries secrets over an inherited file descriptor when a story needs a credential.

See [examples/TESTDRIVE.md](TESTDRIVE.md).

## globus

Needs the `[globus]` extra, a Globus account, and [Globus Connect Personal](https://www.globus.org/globus-connect-personal) on this machine. `setup.py` records this machine's staging collection and does not store a token. `login.py` stores the credential. A file or memory delivery needs both. The live probe is gated on `URISOLVER_GLOBUS_LIVE=1`.

See [examples/globus/README.md](globus/README.md).
