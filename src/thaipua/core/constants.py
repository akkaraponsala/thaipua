"""Filesystem locations for runtime data and bundled assets."""

from __future__ import annotations

import sys
from pathlib import Path

PUA_RANGE_START: int = 0xE000
PUA_RANGE_END: int = 0xF8FF
STRING_TABLE_EXTENSIONS = {".ILSTRINGS", ".DLSTRINGS", ".STRINGS"}
SARA_AM_REPLACEMENTS: list[tuple[str, str]] = [("่ำ", "ํ่า"), ("้ำ", "ํ้า"), ("๊ำ", "ํ๊า"), ("๋ำ", "ํ๋า"), ("ำ", "ํา")]


def is_standalone_build() -> bool:
    """Return True when running as a packaged executable."""
    return bool(getattr(sys, "frozen", False) or "__compiled__" in globals())


def standalone_root() -> Path:
    return Path(sys.executable).resolve().parent


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _runtime_root() -> Path:
    if is_standalone_build():
        return standalone_root()
    return _repo_root()


def _app_data_dir() -> Path:
    return _runtime_root()


def _assets_dir() -> Path:
    return _runtime_root() / "assets"


APP_DATA_DIR: Path = _app_data_dir()
ASSETS_DIR: Path = _assets_dir()
DEFAULT_PUA_MAP_PATH: str = str(APP_DATA_DIR / "pua_mapping.json")
DEFAULT_LAYOUT_PATH: str = str(APP_DATA_DIR / "layout.json")
DEFAULT_PROFILES_DIR: str = str(APP_DATA_DIR / "profiles")
DEFAULT_PROFILE_FILE_NAME: str = "default.json"
DEFAULT_SETTINGS_PATH: str = str(APP_DATA_DIR / "settings.json")


def ensure_app_data_dirs(base_dir: Path | None = None) -> None:
    """Create the runtime-data directories and seed the default profile when missing."""
    root = Path(base_dir) if base_dir is not None else APP_DATA_DIR
    root.mkdir(parents=True, exist_ok=True)
    profiles_dir = root / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    default_profile = profiles_dir / DEFAULT_PROFILE_FILE_NAME
    if not default_profile.is_file():
        _seed_default_profile(default_profile)


def _seed_default_profile(path: Path) -> None:
    """Write a starter `default.json` profile."""
    import json

    from thaipua.core.fonttools.settings import default_placement_settings, settings_to_dict

    payload = settings_to_dict(default_placement_settings())
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=4)
