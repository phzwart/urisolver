"""Globus resolver tests with a fake transfer client (no Globus SDK)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from urisolver import (
    AuthenticationError,
    AuthorizationError,
    Context,
    FileDestination,
    Form,
    InefficientOperationError,
    InvalidURIError,
    Kind,
    MaterializationError,
    MemoryDestination,
    NativeAccessDenied,
    ResolutionError,
    ResourceUnavailableError,
    SecretLookupError,
    UnsupportedDestinationError,
)
from urisolver.registry import get_global_registry
from urisolver.resolvers.globus import (
    GlobusDestination,
    GlobusResolver,
    StagingCollection,
    collection_path,
)
from urisolver.testing.baseline import run_baseline_suite

SCHEME = "com.urisolver.test.globus"
FILE_URI = f"{SCHEME}:///share/godata/file1.txt"
DIR_URI = f"{SCHEME}:///share/folder"
CANARY = "refresh-token-canary-value"
SECRET = "client-secret-canary-value"


class _APIError(Exception):
    def __init__(self, status: int, message: str = "globus http", info: dict | None = None) -> None:
        super().__init__(message)
        self.http_status = status
        self.info = info or {}


class NetworkError(Exception):
    """Same type name the resolver treats as a transport failure."""


class FakeTransfer:
    """Local copy stand-in. Destination paths are absolute paths on this machine."""

    def __init__(
        self,
        source: Path,
        *,
        status: str = "SUCCEEDED",
        wait: bool = True,
        events: list | None = None,
        land: bool = True,
    ) -> None:
        self.source = source
        self.status = status
        self.wait = wait
        self.events = events or []
        self.land = land
        self.submitted: list = []
        self.cancelled: list[str] = []
        self.wait_calls: list[str] = []
        self.tasks: dict[str, str] = {}

    def operation_ls(self, endpoint: str, path: str = "/", filter: str | None = None, **kwargs: object):
        del endpoint, kwargs
        base = self.source / path.lstrip("/")
        if isinstance(filter, str) and filter.startswith("name:="):
            name = filter[len("name:=") :]
            candidate = base / name
            if not candidate.exists():
                return {"DATA": []}
            return {"DATA": [_stat(candidate)]}
        if not base.is_dir():
            return {"DATA": []}
        return {"DATA": [_stat(child) for child in sorted(base.iterdir())]}

    def submit_transfer(self, submission: object) -> dict[str, str]:
        self.submitted.append(submission)
        task_id = f"task-{len(self.submitted)}"
        self.tasks[task_id] = self.status
        if self.land:
            for item in submission.items:  # type: ignore[attr-defined]
                _land(self.source, item, partial=self.status != "SUCCEEDED")
        return {"task_id": task_id}

    def task_wait(self, task_id: str, timeout: float | None = None, polling_interval: float | None = None) -> bool:
        del timeout, polling_interval
        self.wait_calls.append(task_id)
        return self.wait

    def get_task(self, task_id: str) -> dict[str, str]:
        return {"status": self.tasks.get(task_id, self.status)}

    def task_event_list(self, task_id: str) -> list:
        del task_id
        return self.events

    def cancel_task(self, task_id: str) -> dict[str, str]:
        self.cancelled.append(task_id)
        return {"code": "Canceled"}


def _stat(path: Path) -> dict:
    return {
        "name": path.name,
        "type": "dir" if path.is_dir() else "file",
        "size": path.stat().st_size if path.is_file() else 0,
    }


def _land(source: Path, item: object, *, partial: bool) -> None:
    dst = Path(item.destination_path)  # type: ignore[attr-defined]
    if not dst.parent.is_dir():
        return
    if partial:
        if item.recursive:  # type: ignore[attr-defined]
            dst.mkdir(exist_ok=True)
            (dst / "partial").write_bytes(b"x")
        else:
            dst.write_bytes(b"partial")
        return
    src = source / str(item.source_path).lstrip("/")  # type: ignore[attr-defined]
    if item.recursive:  # type: ignore[attr-defined]
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def _tree(tmp_path: Path) -> None:
    godata = tmp_path / "share" / "godata"
    godata.mkdir(parents=True)
    (godata / "file1.txt").write_bytes(b"hello globus\n")
    folder = tmp_path / "share" / "folder"
    folder.mkdir()
    (folder / "a.txt").write_bytes(b"aaa")
    (folder / "b.txt").write_bytes(b"bbbb")


def _install(tmp_path: Path, client: FakeTransfer, **kwargs: object) -> GlobusResolver:
    accessible = kwargs.pop("accessible", (str(tmp_path), "/private", "/var", "/tmp"))
    if "staging" in kwargs:
        staging = kwargs.pop("staging")
    else:
        staging = StagingCollection("staging-collection", "/", tuple(accessible))  # type: ignore[arg-type]
    resolver = GlobusResolver(
        collection="source-collection",
        protocol_name=SCHEME,
        staging=staging,  # type: ignore[arg-type]
        native_modes=frozenset({"file"}),
        transfer_client=client,
        transfer_timeout=kwargs.pop("transfer_timeout", 5.0),  # type: ignore[arg-type]
        secret_id=kwargs.pop("secret_id", None),  # type: ignore[arg-type]
        allow_native=kwargs.pop("allow_native", True),  # type: ignore[arg-type]
    )
    get_global_registry().override(SCHEME, resolver)
    return resolver


def test_collection_path_decodes_and_rejects_authority() -> None:
    assert collection_path(f"{SCHEME}:///share/godata/file%201.txt") == "/share/godata/file 1.txt"
    assert collection_path(f"{SCHEME}:///") == "/"
    with pytest.raises(InvalidURIError):
        collection_path(f"{SCHEME}://6c54cade-bde5-45c1-bdea-f4bd71dba2cc/share/godata/file1.txt")
    with pytest.raises(InvalidURIError):
        collection_path(f"{SCHEME}:///share//godata")


def test_baseline_file(tmp_path: Path) -> None:
    _tree(tmp_path)
    _install(tmp_path, FakeTransfer(tmp_path))
    run_baseline_suite(lambda: FILE_URI)


def test_file_copy_is_native_checksum_transfer(tmp_path: Path) -> None:
    _tree(tmp_path)
    client = FakeTransfer(tmp_path)
    _install(tmp_path, client)
    dest = tmp_path / "out" / "file1.txt"
    with Context() as ctx:
        result = ctx.resolve(FILE_URI).materialize(FileDestination(dest))
    assert dest.read_bytes() == b"hello globus\n"
    assert result.strategy == "native"
    assert result.size_bytes == 13
    item = client.submitted[0]
    assert item.sync_level == "checksum"
    assert item.verify_checksum is True
    assert item.notify_on_succeeded is False
    assert item.items[0].recursive is False


def test_inaccessible_path_names_prefixes(tmp_path: Path) -> None:
    _tree(tmp_path)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    _install(tmp_path, FakeTransfer(tmp_path), accessible=(str(allowed),))
    dest = tmp_path / "elsewhere" / "file1.txt"
    with Context() as ctx:
        resource = ctx.resolve(FILE_URI)
        with pytest.raises(UnsupportedDestinationError, match="accessible staging prefixes") as exc:
            resource.materialize(FileDestination(dest))
    assert str(allowed) in str(exc.value)


def test_missing_staging_blocks_file_and_memory(tmp_path: Path) -> None:
    _tree(tmp_path)
    client = FakeTransfer(tmp_path)
    _install(tmp_path, client, staging=None)
    dest = tmp_path / "file1.txt"
    with Context() as ctx:
        resource = ctx.resolve(FILE_URI)
        with pytest.raises(UnsupportedDestinationError, match="staging collection"):
            resource.materialize(FileDestination(dest))
        with pytest.raises(UnsupportedDestinationError, match="staging collection"):
            resource.materialize(MemoryDestination())
        submitted = resource.materialize(GlobusDestination("dest-collection", "/incoming/file1.txt"))
    assert submitted.strategy == "submitted"
    assert submitted.form.value == "native"
    assert submitted.value == "task-1"
    assert "not finished" in submitted.warnings[0]
    assert client.wait_calls == []


def test_failed_task_removes_partial(tmp_path: Path) -> None:
    _tree(tmp_path)
    client = FakeTransfer(
        tmp_path,
        status="FAILED",
        events=[{"is_error": True, "description": "checksum mismatch"}],
    )
    _install(tmp_path, client)
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    with Context() as ctx:
        with pytest.raises(MaterializationError, match="checksum mismatch"):
            ctx.resolve(FILE_URI).materialize(FileDestination(dest_dir / "file1.txt"))
    assert list(dest_dir.glob(".urisolver-*.tmp")) == []
    assert not (dest_dir / "file1.txt").exists()


def test_timeout_cancels_and_removes_partial(tmp_path: Path) -> None:
    _tree(tmp_path)
    client = FakeTransfer(tmp_path, status="ACTIVE", wait=False)
    _install(tmp_path, client, transfer_timeout=0.01)
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    with Context() as ctx:
        with pytest.raises(MaterializationError, match="timed out"):
            ctx.resolve(FILE_URI).materialize(FileDestination(dest_dir / "file1.txt"))
    assert client.cancelled
    assert list(dest_dir.glob(".urisolver-*.tmp")) == []


def test_recursive_container_copy(tmp_path: Path) -> None:
    _tree(tmp_path)
    client = FakeTransfer(tmp_path)
    _install(tmp_path, client)
    dest = tmp_path / "out" / "folder"
    with Context() as ctx:
        result = ctx.resolve(DIR_URI).materialize(FileDestination(dest))
    assert (dest / "a.txt").read_bytes() == b"aaa"
    assert (dest / "b.txt").read_bytes() == b"bbbb"
    assert result.size_bytes is None
    assert result.strategy == "native"
    assert client.submitted[0].items[0].recursive is True


def test_container_memory_is_a_lazy_map(tmp_path: Path) -> None:
    _tree(tmp_path)
    _install(tmp_path, FakeTransfer(tmp_path))
    with Context() as ctx:
        result = ctx.resolve(DIR_URI).materialize(MemoryDestination())
        assert result.strategy == "reference"
        assert result.is_reference is True
        assert sorted(result.value) == ["a.txt", "b.txt"]
        child = result.value["a.txt"]
        assert child.info().kind is Kind.FILE
        assert child.info().size_bytes == 3


def test_strict_efficiency_refuses_memory_not_file_or_submit(tmp_path: Path) -> None:
    _tree(tmp_path)
    client = FakeTransfer(tmp_path)
    _install(tmp_path, client)
    dest = tmp_path / "out" / "file1.txt"
    with Context(strict_efficiency=True) as ctx:
        resource = ctx.resolve(FILE_URI)
        with pytest.raises(InefficientOperationError, match="memory delivery"):
            resource.materialize(MemoryDestination())
        staged = resource.materialize(MemoryDestination(form=Form.BYTES))
        copied = resource.materialize(FileDestination(dest))
        submitted = resource.materialize(GlobusDestination("dest-collection", "/incoming/file1.txt"))
    assert staged.strategy == "staged"
    assert copied.strategy == "native"
    assert submitted.strategy == "submitted"


def test_consent_required_names_scopes(tmp_path: Path) -> None:
    _tree(tmp_path)

    class _Consent(FakeTransfer):
        def operation_ls(self, *args: object, **kwargs: object):
            raise _APIError(
                403,
                "consent",
                {"consent_required": True, "required_scopes": ["urn:example:data_access"]},
            )

    _install(tmp_path, _Consent(tmp_path))
    with Context() as ctx:
        with pytest.raises(AuthorizationError, match="login.py") as exc:
            ctx.resolve(FILE_URI).info()
    text = str(exc.value)
    assert "required_scopes" in text
    assert "urn:example:data_access" in text


def test_http_status_mapping(tmp_path: Path) -> None:
    _tree(tmp_path)
    expectations = (
        (401, AuthenticationError),
        (403, AuthorizationError),
        (404, ResolutionError),
        (503, ResourceUnavailableError),
    )
    for status, exc_type in expectations:
        class _Fail(FakeTransfer):
            def operation_ls(self, *args: object, **kwargs: object):
                if status == 503:
                    raise _APIError(status)
                raise _APIError(status)

        _install(tmp_path, _Fail(tmp_path))
        with Context() as ctx:
            with pytest.raises(exc_type):
                ctx.resolve(FILE_URI).info()

    class _Down(FakeTransfer):
        def operation_ls(self, *args: object, **kwargs: object):
            raise NetworkError("reset")

    _install(tmp_path, _Down(tmp_path))
    with Context() as ctx:
        with pytest.raises(ResourceUnavailableError):
            ctx.resolve(FILE_URI).info()


def test_secret_values_are_scrubbed(tmp_path: Path) -> None:
    _tree(tmp_path)

    class _Boom(FakeTransfer):
        def operation_ls(self, *args: object, **kwargs: object):
            raise RuntimeError(f"refresh_token={CANARY} client_secret={SECRET}")

    class _Secrets:
        def get_secret(self, secret_id: str) -> dict[str, str]:
            assert secret_id == "globus-example"
            return {"client_id": "cid", "refresh_token": CANARY, "client_secret": SECRET}

    _install(tmp_path, _Boom(tmp_path), secret_id="globus-example")
    with Context(secrets=_Secrets()) as ctx:
        with pytest.raises(ResolutionError) as exc:
            ctx.resolve(FILE_URI).info()
    text = str(exc.value)
    assert CANARY not in text
    assert SECRET not in text


def test_missing_secret_keys_do_not_echo_values(tmp_path: Path) -> None:
    _tree(tmp_path)

    class _Secrets:
        def get_secret(self, secret_id: str) -> dict[str, str]:
            return {"client_id": "cid", "note": CANARY}

    resolver = GlobusResolver(
        collection="source-collection",
        protocol_name=SCHEME,
        secret_id="globus-example",
        staging=StagingCollection("staging-collection", "/", (str(tmp_path),)),
        transfer_client=None,
    )
    get_global_registry().override(SCHEME, resolver)
    with Context(secrets=_Secrets()) as ctx:
        with pytest.raises(SecretLookupError, match="refresh_token or client_secret") as exc:
            resource = ctx.resolve(FILE_URI)
            resource.info()
        assert CANARY not in str(exc.value)
        assert CANARY not in repr(resource)
    assert CANARY not in repr(resolver)


def test_native_operations_follow_allow_native(tmp_path: Path) -> None:
    _tree(tmp_path)
    client = FakeTransfer(tmp_path)
    _install(tmp_path, client, allow_native=False)
    with Context() as ctx:
        resource = ctx.resolve(FILE_URI)
        assert resource.supports("info")
        assert not resource.supports("transfer_client")
        with pytest.raises(NativeAccessDenied):
            resource.transfer_client()
    _install(tmp_path, client, allow_native=True)
    with Context() as ctx:
        resource = ctx.resolve(FILE_URI)
        assert resource.transfer_client() is client
        assert resource.supports("wait")
        rows = resource.operation_ls("/share/folder")
        assert {row["name"] for row in rows} == {"a.txt", "b.txt"}
