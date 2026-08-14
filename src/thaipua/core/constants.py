"""Shared filesystem locations.

User-mutable runtime files (`settings.json`, `pua_mapping.json`, `profiles/`) and the
bundled `assets/` tree live under a base directory dispatched by `is_standalone_build`:
the repository root when run from source, or the folder holding the running executable
under a `pyside6-deploy` standalone build so the travelled `.exe` stays self-contained.
"""

from __future__ import annotations

import sys
from pathlib import Path

PUA_RANGE_START: int = 57344
PUA_RANGE_END: int = 63743
STRING_TABLE_EXTENSIONS = {".ILSTRINGS", ".DLSTRINGS", ".STRINGS"}
SARA_AM_REPLACEMENTS: list[tuple[str, str]] = [("่ำ", "ํ่า"), ("้ำ", "ํ้า"), ("๊ำ", "ํ๊า"), ("๋ำ", "ํ๋า"), ("ำ", "ํา")]


def is_standalone_build() -> bool:
    """Return True when running as a packaged build.

    Nuitka (used by `pyside6-deploy`) sets a `__compiled__` global rather than
    `sys.frozen`, so both markers are checked.
    """
    return bool(getattr(sys, "frozen", False) or "__compiled__" in globals())


def standalone_root() -> Path:
    """Return the directory holding the running standalone executable."""
    return Path(sys.executable).resolve().parent


def _repo_root() -> Path:
    """Return the repository root inferred from this module's location."""
    return Path(__file__).resolve().parents[3]


def _runtime_root() -> Path:
    """Resolve the base directory holding both bundled assets and runtime data."""
    if is_standalone_build():
        return standalone_root()
    return _repo_root()


def _app_data_dir() -> Path:
    """Resolve the writable base directory for runtime data files."""
    return _runtime_root()


def _assets_dir() -> Path:
    """Resolve the root of the bundled `assets/` tree."""
    return _runtime_root() / "assets"


APP_DATA_DIR: Path = _app_data_dir()
ASSETS_DIR: Path = _assets_dir()
DEFAULT_PUA_MAP_PATH: str = str(APP_DATA_DIR / "pua_mapping.json")
DEFAULT_PROFILES_DIR: str = str(APP_DATA_DIR / "profiles")
DEFAULT_PROFILE_FILE_NAME: str = "default.json"
DEFAULT_SETTINGS_PATH: str = str(APP_DATA_DIR / "settings.json")


def ensure_app_data_dirs(base_dir: Path | None = None) -> None:
    """Materialize the runtime-data directories on demand.

    Creates `base_dir` (or `APP_DATA_DIR`) and its `profiles/` subdirectory, and seeds a
    starter `profiles/default.json` from the in-source empty settings when no default
    profile exists yet. `base_dir` lets tests isolate directory creation under a
    `tmp_path`.
    """
    root = Path(base_dir) if base_dir is not None else APP_DATA_DIR
    root.mkdir(parents=True, exist_ok=True)
    profiles_dir = root / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    default_profile = profiles_dir / DEFAULT_PROFILE_FILE_NAME
    if not default_profile.is_file():
        _seed_default_profile(default_profile)


def _seed_default_profile(path: Path) -> None:
    """Write a starter `default.json` profile matching the settings schema."""
    import json

    from thaipua.core.fonttools.settings import default_placement_settings, settings_to_dict

    payload = settings_to_dict(default_placement_settings())
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=4)
