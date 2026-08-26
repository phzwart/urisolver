"""Baseline conformance suite (§31) — matches installed API."""

from __future__ import annotations

import pickle
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from urisolver.context import ResolveContext
from urisolver.destinations import FileDestination, Form, MemoryDestination, ReferencePolicy
from urisolver.errors import (
    AuthorizationError,
    ContextClosedError,
    InefficientOperationError,
    MemoryLimitError,
    UnsupportedDestinationError,
    UnsupportedFormError,
)
from urisolver.info import Kind
from urisolver.plugins import ensure_builtin_file_resolver

_TIER0 = frozenset({"info", "materialize", "facets", "facet", "supports", "capabilities"})


@dataclass
class BaselineResult:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ConformanceFixtures:
    restricted_uri: str | None = None
    auth_failure_uri: str | None = None
    policy_filtered_uri: str | None = None


class ConformanceFailure(AssertionError):
    def __init__(self, result: BaselineResult) -> None:
        self.result = result
        super().__init__(_format_summary(result))


def _format_summary(result: BaselineResult) -> str:
    lines = [
        f"baseline: {len(result.passed)} passed, {len(result.failed)} failed, {len(result.skipped)} skipped"
    ]
    for name in result.failed:
        lines.append(f"  FAILED: {name}")
    for name, reason in result.skipped:
        lines.append(f"  SKIPPED: {name} ({reason})")
    return "\n".join(lines)


def _tmp_siblings(parent: Path) -> list[Path]:
    return list(parent.glob(".urisolver-*.tmp"))


class _Expects:
    """Minimal exception assertion without importing pytest."""

    def __init__(self, exc_type: type[BaseException], *, match: str | None = None) -> None:
        self.exc_type = exc_type
        self.match = match

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: object) -> bool:
        if exc_type is None:
            raise AssertionError(f"expected {self.exc_type.__name__}, no exception raised")
        if not issubclass(exc_type, self.exc_type):
            return False
        if self.match is not None and exc is not None:
            import re

            if not re.search(self.match, str(exc)):
                raise AssertionError(f"exception {exc!r} did not match {self.match!r}")
        return True


def _check_overwrite_and_atomic(r: object, td: Path) -> None:
    dest = Path(td) / "ow.bin"
    dest.write_bytes(b"old")
    before = _tmp_siblings(Path(td))

    with _Expects(FileExistsError):
        r.materialize(FileDestination(dest, overwrite=False))  # type: ignore[attr-defined]
    assert _tmp_siblings(Path(td)) == before, "overwrite=False must not create temp files"

    r.materialize(FileDestination(dest, overwrite=True))  # type: ignore[attr-defined]
    assert dest.read_bytes() != b"old"
    assert not _tmp_siblings(Path(td)), "overwrite=True must leave no temp siblings"


def _check_failure_no_partial(r: object, td: Path, info: object) -> None:
    if getattr(info, "kind", None) is Kind.CONTAINER:
        return
    blocked = Path(td) / "blocked-dir"
    blocked.mkdir()
    (blocked / "keep").write_text("unchanged")
    before = set(blocked.iterdir())

    with _Expects(OSError):
        r.materialize(FileDestination(blocked, overwrite=True))  # type: ignore[attr-defined]

    assert not _tmp_siblings(Path(td)), "failed copy must leave no temp siblings"
    assert set(blocked.iterdir()) == before, "destination directory contents must be unchanged"


def run_baseline_suite(
    make_uri: Callable[[], str],
    *,
    context_factory: Callable[..., ResolveContext] | None = None,
    expect_array_selection: bool = False,
    expect_bytes: bool = True,
    fixtures: ConformanceFixtures | None = None,
    raise_on_failure: bool = True,
) -> BaselineResult:
    ensure_builtin_file_resolver()
    result = BaselineResult()
    fixtures = fixtures or ConformanceFixtures()

    def _ctx(**kwargs: object) -> ResolveContext:
        if context_factory is None:
            return ResolveContext(**{k: v for k, v in kwargs.items() if v is not None})
        return context_factory(**kwargs)

    def _pass(name: str) -> None:
        result.passed.append(name)

    def _fail(name: str, exc: BaseException) -> None:
        result.failed.append(f"{name}: {exc}")

    def _skip(name: str, reason: str) -> None:
        result.skipped.append((name, reason))

    def _run(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
            _pass(name)
        except _SkipCheck as exc:
            _skip(name, str(exc))
        except BaseException as exc:
            _fail(name, exc)

    uri = make_uri()
    resource = None

    def _check_resolve_and_tier0() -> None:
        nonlocal resource
        with _ctx() as ctx:
            resource = ctx.resolve(uri)
            info = resource.info()
            assert info.uri == uri or info.uri == resource.uri
            assert info.protocol
            assert isinstance(info.kind, Kind)
            assert isinstance(info.exists, bool)

            caps = resource.capabilities()
            for name in _TIER0:
                assert name in caps, f"{name!r} missing from capabilities()"
                assert resource.supports(name), name
                assert hasattr(resource, name), name
            for name in caps:
                assert resource.supports(name), name
                assert hasattr(resource, name), name

    _run("resolve_and_tier0", _check_resolve_and_tier0)
    if resource is None:
        if raise_on_failure and result.failed:
            print(_format_summary(result), file=sys.stderr)
            raise ConformanceFailure(result)
        return result

    def _check_memory_and_strategy() -> None:
        with _ctx() as ctx:
            r = ctx.resolve(uri)
            mem = r.materialize(MemoryDestination())
            assert mem.value is not None
            assert mem.strategy
            assert mem.source_uri
            assert mem.resolved_uri

    _run("materialize_memory", _check_memory_and_strategy)

    def _check_bytes_and_file() -> None:
        with _ctx() as ctx:
            r = ctx.resolve(uri)
            info = r.info()
            if info.kind is Kind.CONTAINER:
                return
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                dest = td_path / "out.bin"
                file_result = r.materialize(FileDestination(dest))
                assert Path(file_result.value).exists()
                assert file_result.form is Form.PATH
                assert file_result.strategy

                if info.canonical_media_type is not None and expect_bytes:
                    raw = r.materialize(MemoryDestination(form=Form.BYTES))
                    assert isinstance(raw.value, (bytes, bytearray, memoryview))
                    assert raw.media_type == info.canonical_media_type
                    assert raw.strategy
                    with _Expects(UnsupportedFormError):
                        r.materialize(
                            MemoryDestination(form=Form.BYTES, media_type="application/x-nope")
                        )
                    _check_overwrite_and_atomic(r, td_path)
                    _check_failure_no_partial(r, td_path, info)
                elif expect_bytes:
                    with _Expects(UnsupportedFormError):
                        r.materialize(MemoryDestination(form=Form.BYTES))

    _run("bytes_and_file", _check_bytes_and_file)

    if expect_array_selection:
        def _check_selection() -> None:
            with _ctx() as ctx:
                r = ctx.resolve(uri)
                info = r.info()
                if info.kind is not Kind.ARRAY:
                    return
                selection: object = (
                    (slice(0, 1), Ellipsis) if (info.shape and len(info.shape) >= 1) else slice(0, 1)
                )
                block = r.materialize(MemoryDestination(), selection=selection)
                assert block.strategy in {
                    "native", "native-selection", "read-then-select", "converted",
                }

        _run("array_selection", _check_selection)
    else:
        _skip("array_selection", "capability:not_requested")

    if expect_array_selection:
        def _check_strict_efficiency() -> None:
            with _ctx(strict_efficiency=True) as ctx:
                r = ctx.resolve(uri)
                if r.info().kind is not Kind.ARRAY:
                    return
                r.materialize(MemoryDestination(), selection=slice(0, 1))

        _run("strict_efficiency", _check_strict_efficiency)
    else:
        _skip("strict_efficiency", "capability:not_requested")

    def _check_memory_limit() -> None:
        with _ctx() as ctx:
            r = ctx.resolve(uri)
            info = r.info()
            if info.kind is Kind.CONTAINER or info.size_bytes is None:
                return
            with _ctx(memory_limit=info.size_bytes - 1) as limited:
                lr = limited.resolve(uri)
                with _Expects(MemoryLimitError):
                    lr.materialize(MemoryDestination())

    _run("memory_limit_known_size", _check_memory_limit)

    def _check_reference_survives() -> None:
        with _ctx() as ctx:
            r = ctx.resolve(uri)
            info = r.info()
            if info.kind is Kind.CONTAINER:
                return
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                ref_path: Path | None = None
                try:
                    ref = r.materialize(
                        FileDestination(td_path / "ignored", reference=ReferencePolicy.IN_PLACE)
                    )
                    assert ref.is_reference is True
                    ref_path = Path(ref.value)
                    assert ref_path.exists()
                except UnsupportedDestinationError:
                    ref = r.materialize(MemoryDestination())
                    assert ref.value is not None

                blocked = td_path / "blocked"
                blocked.mkdir()
                (blocked / "keep").write_text("x")
                with _Expects(OSError):
                    r.materialize(FileDestination(blocked, overwrite=True))
                if ref_path is not None:
                    assert ref_path.exists()
                assert ref.value is not None

    _run("reference_survives_failure", _check_reference_survives)

    def _check_close_and_pickle() -> None:
        with _ctx() as ctx:
            r = ctx.resolve(uri)
        with _Expects(ContextClosedError):
            r.info()
        with _Expects(TypeError, match="not picklable|not pickle"):
            pickle.dumps(r)

    _run("context_close_and_picklable", _check_close_and_pickle)

    def _check_canonical_reader() -> None:
        with _ctx() as ctx:
            r = ctx.resolve(uri)
            info = r.info()
            if info.canonical_media_type != "application/x-npy":
                return
            try:
                import io

                import numpy as np
            except ImportError:
                raise _SkipCheck("reader:numpy_not_installed")
            data = r.materialize(MemoryDestination(form=Form.BYTES)).value
            loaded = np.load(io.BytesIO(data))
            assert loaded is not None

    _run("canonical_reader", _check_canonical_reader)

    if fixtures.restricted_uri is not None:
        def _check_restricted_metadata() -> None:
            with _ctx() as ctx:
                r = ctx.resolve(fixtures.restricted_uri)  # type: ignore[arg-type]
                try:
                    info = r.info()
                except AuthorizationError:
                    return
                assert info.exists is False, "restricted resource must report exists=False or raise AuthorizationError"

        _run("restricted_metadata", _check_restricted_metadata)
    else:
        _skip("restricted_metadata", "fixture:not_supplied")

    if fixtures.auth_failure_uri is not None:
        def _check_auth_refusal() -> None:
            with _ctx() as ctx:
                r = ctx.resolve(fixtures.auth_failure_uri)  # type: ignore[arg-type]
                try:
                    r.materialize(MemoryDestination())
                except AuthorizationError:
                    return
                try:
                    r.info()
                except AuthorizationError:
                    return
                raise AssertionError("expected AuthorizationError, not AttributeError or silent success")

        _run("auth_refusal", _check_auth_refusal)
    else:
        _skip("auth_refusal", "fixture:not_supplied")

    if fixtures.policy_filtered_uri is not None:
        def _check_policy_tier0() -> None:
            with _ctx() as ctx:
                r = ctx.resolve(fixtures.policy_filtered_uri)  # type: ignore[arg-type]
                caps = r.capabilities()
                for name in _TIER0:
                    assert name in caps, f"{name!r} missing from capabilities() under policy filter"
                    assert r.supports(name), name
                    assert hasattr(r, name), name

        _run("policy_tier0_preserved", _check_policy_tier0)
    else:
        _skip("policy_tier0_preserved", "fixture:not_supplied")

    if raise_on_failure and result.failed:
        print(_format_summary(result), file=sys.stderr)
        raise ConformanceFailure(result)
    return result


class _SkipCheck(Exception):
    pass
