# Workflow across machines

Machine A holds the secrets store and never fetches data. Machines B and C run the same worker. The worker receives a URI, a destination path, and a loopback exchange URL. The per-job bearer token arrives on stdin. It is not placed in the command line.

The offline URI `com.urisolver.example.offline:///<secret-id>` needs no network. Its path segment is the secret id. A successful delivery writes the fixed payload `offline\n`.

## Local mode

Put a canary map in the local store. `CANARY-refresh-7f3a` is a test value, not a real credential.

```bash
python -c "
from urisolver.secrets.jsonfile import LocalSecretsManager
LocalSecretsManager.default().put_secret(
    'globus-example', {'token': 'CANARY-refresh-7f3a'}
)
"
python examples/workflow/orchestrate.py --local --allow globus-example \
  com.urisolver.example.offline:///globus-example staged.txt
```

The orchestrator opens one loopback endpoint for that job, starts `worker.py` on this machine, and closes the endpoint when the worker exits. `--allow` is the only set of secret ids that job can obtain. An id that is not listed is refused with the same response bytes as an unknown id.

A public `file:` URI does not ask for a secret, so the worker still finishes when nothing is listening on the exchange URL.

## Two machines

On machine A, the same script prints the exact `ssh -R` command and runs it. The token is the stdin of that ssh process. It does not appear in the command. The deck's port `8700` is an illustration; the script binds an ephemeral loopback port and forwards that port.

```bash
python examples/workflow/orchestrate.py --ssh worker.example --allow globus-example \
  com.urisolver.example.globus:///share/godata/file1.txt file1.txt
```

The printed command has the shape:

```text
ssh -R <port>:127.0.0.1:<port> worker.example <python> <worker.py> <uri> <dest> http://127.0.0.1:<port>/
```

Machine B is that ssh session. Machine C is the same `worker.py` with no forwarded port: a public Zenodo record or the public Tiled demo still resolves, and any lookup that needs a secret fails with `SecretLookupError`. The worker does not read a secrets file on the node.

## What this does not protect against

Other processes of the same user on the worker node can reach the forwarded loopback port during the job. The per-job bearer token is the mitigation for that. The endpoint is closed when the worker exits, and the token is not reused for the next job.
