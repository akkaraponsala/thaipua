"""G8: document persistence runs against an in-memory store with zero disk IO."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from thaipua.core.domain.errors import SettingsError
from thaipua.core.domain.settings import (
    default_placement_settings,
    settings_to_dict,
)
from thaipua.core.fonttools.settings import (
    load_placement_settings,
    save_placement_settings,
)
from thaipua.core.layout import LayoutState, load_layout_state, save_layout_state
from thaipua.core.pua_map import load_pua_map_dict, save_pua_map
from thaipua.core.store.json_store import MemoryJsonStore


def _phantom(tmp_path: Path, name: str) -> Path:
    return tmp_path / "phantom" / name


def test_layout_roundtrip_through_memory_store(tmp_path: Path) -> None:
    store = MemoryJsonStore()
    path = _phantom(tmp_path, "layout.json")
    state = LayoutState(
        base=0xE100,
        relocations={"ก่": chr(0xE900), "กุิ": chr(0xE901), "bogus": chr(0xE902)},
        approvals={"font-A": frozenset({0xE600})},
    )
    save_layout_state(state, path, store=store)
    loaded = load_layout_state(path, store=store)
    assert loaded is not None
    assert loaded.base == state.base
    assert loaded.relocations == {"ก่": chr(0xE900)}
    assert loaded.approvals == state.approvals
    assert loaded.effective_map()["ก่"] == chr(0xE900)
    assert not (tmp_path / "phantom").exists()


def test_layout_missing_and_malformed_without_disk(tmp_path: Path) -> None:
    store = MemoryJsonStore()
    assert load_layout_state(_phantom(tmp_path, "missing.json"), store=store) is None
    bad = _phantom(tmp_path, "bad.json")
    store.save(bad, ["not", "a", "document"])
    assert load_layout_state(bad, store=store) is None
    assert not (tmp_path / "phantom").exists()


def test_pua_map_roundtrip_and_skips_through_memory_store(tmp_path: Path) -> None:
    store = MemoryJsonStore()
    path = _phantom(tmp_path, "pua.json")
    assert load_pua_map_dict(path, store=store) == {}
    raw: dict[str, Any] = {"ก่": "\ue900", "bogus-value": "XY", "k": 5}
    save_pua_map(raw, path, store=store)
    assert load_pua_map_dict(path, store=store) == {"ก่": "\ue900"}
    assert not (tmp_path / "phantom").exists()


def test_settings_roundtrip_and_version_error_through_memory_store(tmp_path: Path) -> None:
    store = MemoryJsonStore()
    path = _phantom(tmp_path, "profile.json")
    assert settings_to_dict(load_placement_settings(path, store=store)) == settings_to_dict(
        default_placement_settings()
    )
    save_placement_settings(default_placement_settings(), path, store=store)
    assert settings_to_dict(load_placement_settings(path, store=store)) == settings_to_dict(
        default_placement_settings()
    )
    store.save(path, {"version": 999})
    with pytest.raises(SettingsError):
        load_placement_settings(path, store=store)
    assert not (tmp_path / "phantom").exists()


def test_memory_store_rejects_non_serializable_payloads(tmp_path: Path) -> None:
    store = MemoryJsonStore()
    with pytest.raises(TypeError):
        store.save(_phantom(tmp_path, "bad.json"), {"key": object()})
    assert not (tmp_path / "phantom").exists()
