"""Unit tests for the injectable `RuntimeRoot` data-directory isolation (A14)."""

from __future__ import annotations

from pathlib import Path

from thaipua.core.paths import (
    DEFAULT_LAYOUT_PATH,
    DEFAULT_PROFILES_DIR,
    DEFAULT_PUA_MAP_PATH,
    RuntimeRoot,
    default_runtime_root,
)
from thaipua.gui.font_service import FontService


def test_default_root_matches_legacy_constants() -> None:
    root = default_runtime_root()
    assert str(root.profiles_dir) == DEFAULT_PROFILES_DIR
    assert str(root.pua_map_path) == DEFAULT_PUA_MAP_PATH
    assert str(root.layout_path) == DEFAULT_LAYOUT_PATH


def test_default_service_resolves_paths_from_default_root() -> None:
    service = FontService()
    assert service.root == default_runtime_root()
    assert service.pua_map_path == DEFAULT_PUA_MAP_PATH


def test_injected_root_isolates_layout_and_map_caches(tmp_path: Path) -> None:
    root = RuntimeRoot(app_data_dir=tmp_path / "data", assets_dir=tmp_path / "assets")
    service = FontService(root=root)
    assert service.root is root
    service.set_layout_path(str(root.layout_path))
    service.set_pua_map_path(str(root.pua_map_path))
    service.load_layout()
    assert (tmp_path / "data" / "layout.json").exists()
    assert (tmp_path / "data" / "pua_mapping.json").exists()
