"""Create runtime-data directories under the app-data root."""

from __future__ import annotations

from pathlib import Path

from thaipua.core.constants import APP_DATA_DIR, PROFILES_DIR_NAME


def ensure_app_data_dirs(base_dir: Path | None = None) -> None:
    """Create the app-data root and its subdirectories when missing."""
    root = Path(base_dir) if base_dir is not None else APP_DATA_DIR
    (root / PROFILES_DIR_NAME).mkdir(parents=True, exist_ok=True)
