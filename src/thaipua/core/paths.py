"""Filesystem locations for runtime data and bundled assets."""

from __future__ import annotations

import sys
from pathlib import Path

DATA_DIR_NAME: str = "data"
ASSETS_DIR_NAME: str = "assets"
PROFILES_DIR_NAME: str = "profiles"
DEFAULT_PROFILE_FILE_NAME: str = "default.json"


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


APP_DATA_DIR: Path = _runtime_root() / DATA_DIR_NAME
ASSETS_DIR: Path = _runtime_root() / ASSETS_DIR_NAME
DEFAULT_PROFILES_DIR: str = str(APP_DATA_DIR / PROFILES_DIR_NAME)
DEFAULT_PUA_MAP_PATH: str = str(APP_DATA_DIR / "pua_mapping.json")
DEFAULT_LAYOUT_PATH: str = str(APP_DATA_DIR / "layout.json")
DEFAULT_CONFIG_PATH: str = str(APP_DATA_DIR / "config.json")
