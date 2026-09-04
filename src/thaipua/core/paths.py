"""Filesystem locations for runtime data and bundled assets."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

DATA_DIR_NAME: str = "data"
ASSETS_DIR_NAME: str = "assets"
PROFILES_DIR_NAME: str = "profiles"


def is_standalone_build() -> bool:
    """Return `True` when running as a packaged executable."""
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


@dataclass(frozen=True, slots=True)
class RuntimeRoot:
    """Injectable filesystem root; derived paths replace the import-time constants."""

    app_data_dir: Path
    assets_dir: Path

    @property
    def profiles_dir(self) -> Path:
        """Return the `<app_data>/profiles` directory."""
        return self.app_data_dir / PROFILES_DIR_NAME

    @property
    def pua_map_path(self) -> Path:
        """Return the materialized PUA-map cache path."""
        return self.app_data_dir / "pua_mapping.json"

    @property
    def layout_path(self) -> Path:
        """Return the layout state path."""
        return self.app_data_dir / "layout.json"

    @property
    def config_path(self) -> Path:
        """Return the app config path."""
        return self.app_data_dir / "config.json"


def default_runtime_root() -> RuntimeRoot:
    """Build the production root from the import-time data/asset directories."""
    return RuntimeRoot(app_data_dir=APP_DATA_DIR, assets_dir=ASSETS_DIR)
