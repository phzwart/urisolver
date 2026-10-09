"""Binder entry points stay lazy, and conflicts wait until first use."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from urisolver.binders._plugins import bootstrap, reset_plugin_state
from urisolver.binders._registry import BinderRegistry
from urisolver.errors import PluginConflictError, PluginVersionError


@pytest.fixture(autouse=True)
def _reset():
    reset_plugin_state()
    yield
    reset_plugin_state()


def _fake_entry_point(name: str, source: str):
    entry_point = MagicMock()
    entry_point.name = name
    dist = MagicMock()
    dist.name = source
    entry_point.dist = dist
    entry_point.value = source
    return entry_point


def test_protocol_conflict_is_deferred_until_get(monkeypatch):
    entries = [_fake_entry_point("dup", "pkg-a"), _fake_entry_point("dup", "pkg-b")]

    def entry_points(group: str):
        if group == "urisolver.binders":
            return entries
        return []

    monkeypatch.setattr("urisolver.binders._plugins._entry_points", entry_points)
    registry = BinderRegistry()
    bootstrap(registry)
    with pytest.raises(PluginConflictError, match="dup"):
        registry.get("dup")


def test_api_version_1_is_refused():
    class OldBinder:
        api_version = 1
        protocol = "old"

        def plan(self, *args, **kwargs):
            return None

    registry = BinderRegistry()
    registry.register("old", OldBinder(), source="test")
    with pytest.raises(PluginVersionError, match="api_version=1"):
        registry.get("old")


def test_lazy_proxies_do_not_import_at_bootstrap(monkeypatch):
    monkeypatch.setattr("urisolver.binders._plugins._entry_points", lambda group: [])
    for name in (
        "urisolver.binders.tiled",
        "urisolver.binders.globus",
        "urisolver.binders.zenodo",
    ):
        sys.modules.pop(name, None)
    registry = BinderRegistry()
    bootstrap(registry)
    for name in (
        "urisolver.binders.tiled",
        "urisolver.binders.globus",
        "urisolver.binders.zenodo",
    ):
        assert name not in sys.modules
    registry.get("file")
    assert "urisolver.binders.file" in sys.modules
    assert "urisolver.binders.globus" not in sys.modules
