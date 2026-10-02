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

## One manager, one id per resource

`LocalSecretsManager` holds every secret, one file per id under `~/.config/urisolver/secrets/`. Resolve picks the id for this path from the catalog, then asks the manager for that id.

`secret_id` is the credential for every path on this collection. `secrets` maps a path prefix to a different id. The longest prefix that is the path, or a parent of it, wins:

```yaml
  secret_id: globus-example
  secrets:
    share/godata/secret: globus-secret
```

`/share/godata/file1.txt` asks for `globus-example`. `/share/godata/secret/a` asks for `globus-secret`. The committed catalog sets only `secret_id`. Secret values stay out of the URI and the catalog.

`native` is `file`. A transfer into a local path is the delivery Globus can do without an extra copy. `MemoryDestination` still works, including `form=BYTES`: the resolver transfers into a temporary file under `staging.accessible` and reads it back. That result is `strategy="staged"`. `Context(strict_efficiency=True)` allows the file delivery and refuses both memory forms.

`staging` is this machine, not a second source. `root` is the local path that corresponds to `/` on your collection. `accessible` lists prefixes the resolver is willing to write. The committed UUID and `/CHANGE_ME` are placeholders. Do not edit those in the repo. `setup.py` writes only the `staging` block into `~/.config/urisolver/catalog.yaml`. That block is merged over the bundled catalog, so a later edit to the repo catalog still applies. If an older `setup.py` copied the whole catalog into that file, run `setup.py` again. Optional `transfer_timeout` is a number of seconds; when it is omitted, a blocking transfer waits until the task finishes and is not cancelled. Another Globus scheme in the same file can point at the same block with `staging: *example-staging`. The example script registers this scheme. Installing the package does not.

`import urisolver` does not load the Globus SDK. The SDK is imported inside urisolver on the first transfer.

## Globus Connect Personal

Install [Globus Connect Personal](https://www.globus.org/globus-connect-personal) and start it. In the collection settings, note the collection UUID and the local directories it is allowed to serve (`config-paths` in the GCP configuration). Put that UUID in `staging.collection`. Put one of those directories in `staging.accessible`. `staging.root` stays `/` when the collection root is the filesystem root GCP is using.

The tutorial collection is the source. Your GCP collection is only the place files land. You do not need a second tutorial endpoint.

Record that collection. This does not store a credential:

```bash
python examples/globus/setup.py \
    --collection "<your GCP collection UUID>" \
    --accessible "$HOME"
```

Repeat `--accessible` for each directory GCP is allowed to write. The command writes `~/.config/urisolver/catalog.yaml`.

## Log in

Credentials go to the local secrets manager, `~/.config/urisolver/secrets/<secret_id>.json`, mode `0600`. The manager is not attached to a `Context` unless a script passes it. `login.py` is the setup write. `resolve.py` and the worker's parent are the readers. The child process never opens the directory.

Register a native app at [https://app.globus.org](https://app.globus.org). The redirect URL is `https://auth.globus.org/v2/web/auth-code`.

```bash
pip install -e ".[globus,dev]"
export URISOLVER_GLOBUS_CLIENT_ID="<app client id>"
python examples/globus/login.py
```

The script opens a consent URL on stderr. Paste the code it asks for. It stores `client_id` and `refresh_token` through `LocalSecretsManager` and prints the path. An access token is not stored.

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

`FileDestination` of a file submits one transfer to a hidden name in the destination directory and waits. On success it renames that name onto the destination. The call blocks until Globus reports the task, or until `transfer_timeout` when that is set. `strategy` is `"native"`. A directory is copied only when the URI ends in `?recursive`. `Context(allow_recursive=False)` refuses that copy. The flag is not part of the collection path, and a container materialized to memory does not pass it on to children.

`GlobusDestination(collection, path)` submits and returns. `value` is the task id, `strategy` is `"submitted"`, and the warning says the transfer is not finished. `strict_efficiency` does not apply. Waiting is the Tier 2 `wait(task_id, timeout)` on the resource.

`MemoryDestination` is `"staged"` because the bytes crossed a temporary file on the staging collection. A container materialized to memory is a map of child names (`strategy="reference"`) and does not transfer until a child is materialized.

With no `staging` block, `FileDestination` and `MemoryDestination` raise `UnsupportedDestinationError` naming the missing staging collection. `GlobusDestination` still submits, because the destination is a collection id rather than a local path.

## Confidential client

Skip `login.py` when the app is confidential. Share the source collection and the staging collection with `<client_id>@clients.auth.globus.org`. Store the same map with the local secrets manager, mode `0600`:

```json
{"client_id": "<client id>", "client_secret": "<client secret>"}
```

The resolver uses that pair as a client-credentials token. It still does not write an access token to disk.
