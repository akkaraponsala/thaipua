"""Unit tests for runtime-data bootstrap and default-profile seeding."""

from __future__ import annotations

import json
from pathlib import Path

from thaipua.core.bootstrap import ensure_app_data_dirs
from thaipua.core.fonttools.settings import default_placement_settings, load_placement_settings
from thaipua.core.profiles import seed_default_profile


def test_ensure_app_data_dirs_creates_profiles_subtree(tmp_path: Path) -> None:
    ensure_app_data_dirs(tmp_path)
    assert (tmp_path / "profiles").is_dir()


def test_ensure_app_data_dirs_is_idempotent(tmp_path: Path) -> None:
    ensure_app_data_dirs(tmp_path)
    ensure_app_data_dirs(tmp_path)
    assert (tmp_path / "profiles").is_dir()


def test_seed_default_profile_writes_loadable_settings(tmp_path: Path) -> None:
    target = seed_default_profile(tmp_path)
    assert target == tmp_path / "default.json"
    assert load_placement_settings(target) == default_placement_settings()


def test_seed_default_profile_preserves_existing_file(tmp_path: Path) -> None:
    existing = tmp_path / "default.json"
    existing.write_text(json.dumps({"version": 1, "consonants": {}}), encoding="utf-8")
    seed_default_profile(tmp_path)
    assert json.loads(existing.read_text(encoding="utf-8")) == {"version": 1, "consonants": {}}
