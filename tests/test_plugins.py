"""Plugin discovery and conflict tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from urisolver.errors import PluginConflictError, UnknownSchemeError
from urisolver.plugins import (
    _CONFLICTS,
    _ENUMERATED,
    _SOURCES,
    clear_plugin_conflict,
    enumerate_resolver_entry_points,
)
from urisolver.registry import Registry, register_resolver
from urisolver.resolvers.file import FileResolver


@pytest.fixture(autouse=True)
def _reset_plugin_state():
    _ENUMERATED.clear()
    _SOURCES.clear()
    _CONFLICTS.clear()
    yield
    _ENUMERATED.clear()
    _SOURCES.clear()
    _CONFLICTS.clear()


def _fake_entry_point(name: str, source: str):
    ep = MagicMock()
    ep.name = name
    dist = MagicMock()
    dist.name = source
    ep.dist = dist
    ep.value = source
    return ep


def test_enumerate_collects_all_conflicts(monkeypatch):
    eps = [
        _fake_entry_point("dup", "pkg-a"),
        _fake_entry_point("dup", "pkg-b"),
        _fake_entry_point("ok", "pkg-c"),
    ]
    monkeypatch.setattr(
        "urisolver.plugins._entry_points",
        lambda group: eps,
    )
    found = enumerate_resolver_entry_points()
    assert "ok" in found
    assert "dup" in found
    assert _CONFLICTS["dup"] == ("pkg-a", "pkg-b")


def test_registry_get_conflict_before_unknown(monkeypatch):
    reg = Registry()
    reg.register("file", FileResolver(), source="builtin")
    monkeypatch.setattr(
        "urisolver.plugins._entry_points",
        lambda group: [_fake_entry_point("dup", "a"), _fake_entry_point("dup", "b")],
    )
    enumerate_resolver_entry_points()
    with pytest.raises(PluginConflictError, match="dup"):
        reg.get("dup")
    with pytest.raises(UnknownSchemeError):
        reg.get("missing")


def test_override_clears_conflict(monkeypatch):
    monkeypatch.setattr(
        "urisolver.plugins._entry_points",
        lambda group: [_fake_entry_point("dup", "a"), _fake_entry_point("dup", "b")],
    )
    enumerate_resolver_entry_points()
    assert "dup" in _CONFLICTS
    register_resolver("dup", FileResolver(), source="explicit")
    assert "dup" not in _CONFLICTS

    reg = Registry()
    reg.register("dup", FileResolver(), source="explicit")
    assert reg.get("dup") is not None


def test_clear_plugin_conflict():
    _CONFLICTS["x"] = ("a", "b")
    clear_plugin_conflict("x")
    assert "x" not in _CONFLICTS
