# One URI, one file

The local resolution catalog binds a scheme to a Globus collection. This process only has a URI. It imports `urisolver`, resolves, and materializes. The collection id is in [examples/catalog.yaml](../catalog.yaml).

```yaml
com.urisolver.example.globus:
  protocol: globus
  collection: 6c54cade-bde5-45c1-bdea-f4bd71dba2cc
  native: [file]
  secret_id: globus-example
  staging: &example-staging
    collection: 00000000-0000-0000-0000-000000000000
    root: /
    accessible:
      - /CHANGE_ME
```

`collection` is Globus Tutorial Collection 1. The URI path is the absolute path on that collection. `com.urisolver.example.globus:///share/godata/file1.txt` is `/share/godata/file1.txt`.

`native` is `file`. A transfer into a local path is the delivery Globus can do without an extra copy. `MemoryDestination` still works: the resolver transfers into a temporary file under `staging.accessible` and reads it back. That result is `strategy="staged"`. `Context(strict_efficiency=True)` allows the file delivery and refuses the memory one.

`staging` is this machine, not a second source. `root` is the local path that corresponds to `/` on your collection. `accessible` lists prefixes the resolver is willing to write. The committed UUID and `/CHANGE_ME` are placeholders. Replace both. Another Globus scheme in the same file can point at the same block with `staging: *example-staging`.

`import urisolver` does not load the Globus SDK. The SDK is imported inside urisolver on the first transfer.

## Globus Connect Personal

Install [Globus Connect Personal](https://www.globus.org/globus-connect-personal) and start it. In the collection settings, note the collection UUID and the local directories it is allowed to serve (`config-paths` in the GCP configuration). Put that UUID in `staging.collection`. Put one of those directories in `staging.accessible`. `staging.root` stays `/` when the collection root is the filesystem root GCP is using.

The tutorial collection is the source. Your GCP collection is only the place files land. You do not need a second tutorial endpoint.

## Log in

Register a native app at [https://app.globus.org](https://app.globus.org). The redirect URL is `https://auth.globus.org/v2/web/auth-code`.

```bash
pip install -e ".[globus,dev]"
export URISOLVER_GLOBUS_CLIENT_ID="<app client id>"
python examples/globus/login.py
```

The script opens a consent URL on stderr. Paste the code it asks for. It writes `~/.config/urisolver/secrets/globus-example.json` mode `0600` with `client_id` and `refresh_token`, then prints that path. An access token is not stored.

Tutorial collections and Globus Connect Personal do not need a `data_access` scope. A GCSv5 mapped collection does. `login.py` requests it only after the transfer scope is in hand and the collection's `entity_type` says so. If Globus answers `consent_required` later, the error lists `required_scopes` and says to run `login.py` again.

## Resolve

`staging.accessible` has to contain the destination directory. Pass that directory, or rely on `$HOME` after you have listed it.

```bash
python examples/globus/resolve.py "$HOME"
```

A successful run prints four lines: the remote size in bytes, the length of the bytes held in memory, the local path, and that file's size.

## Worker

`examples/globus/worker.py` reads the secret file in the parent and passes lookups to a child over a pipe. The child only imports `urisolver`. It does not open the secret file and it does not handle tokens.

```bash
python examples/globus/worker.py "$HOME/file1.txt"
```

The child prints the staged path and the size.

## File, memory, and a task id

`FileDestination` submits one transfer to a hidden name in the destination directory and waits. On success it renames that name onto the destination. The call blocks until Globus reports the task. `strategy` is `"native"`.

`GlobusDestination(collection, path)` submits and returns. `value` is the task id, `strategy` is `"submitted"`, and the warning says the transfer is not finished. `strict_efficiency` does not apply. Waiting is the Tier 2 `wait(task_id, timeout)` on the resource.

`MemoryDestination` is `"staged"` because the bytes crossed a temporary file on the staging collection. A container materialized to memory is a map of child names (`strategy="reference"`) and does not transfer until a child is materialized.

With no `staging` block, `FileDestination` and `MemoryDestination` raise `UnsupportedDestinationError` naming the missing staging collection. `GlobusDestination` still submits, because the destination is a collection id rather than a local path.

## Confidential client

Skip `login.py` when the app is confidential. Share the source collection and the staging collection with `<client_id>@clients.auth.globus.org`. Write the same secret path by hand, mode `0600`:

```json
{"client_id": "<client id>", "client_secret": "<client secret>"}
```

The resolver uses that pair as a client-credentials token. It still does not write an access token to disk.
