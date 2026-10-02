# Examples

Each demo starts from a URI. urisolver turns it into a file or an in-memory object. The caller does not branch on the backend.

Start with the shared frontend, then the multi-machine workflow, then tiled, testdrive, and globus.

`examples/catalog.yaml` maps a scheme name to a server. An explicit path or `$URISOLVER_CATALOG` replaces that file. Otherwise `~/.config/urisolver/catalog.yaml` is merged over it. The example Tiled, Globus, and Zenodo resolvers are not package entry points. Each script registers its resolver before `resolve`.

## frontend

[examples/frontend.py](frontend.py) is one `stage` function for the Tiled demo, the Zenodo record, and the Globus tutorial file. It does not branch on the scheme. `--memory` delivers `MemoryDestination` instead of a file.

## workflow

[examples/workflow/](workflow/) is the holder and the worker. Local mode needs no second machine. The holder opens one loopback endpoint per job and closes it when the worker exits.

See [examples/workflow/README.md](workflow/README.md).

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
