"""Settings file persistence; the schema itself lives in `core.domain.settings`."""

import json
import logging
from pathlib import Path

from thaipua.core.domain.settings import (
    PlacementSettings,
    default_placement_settings,
    settings_from_dict,
    settings_to_dict,
)
from thaipua.core.store.json_store import DiskJsonStore
from thaipua.core.store.ports import JsonStore

logger = logging.getLogger(__name__)

__all__ = [
    "load_placement_settings",
    "save_placement_settings",
]


def load_placement_settings(path: str | Path, *, store: JsonStore | None = None) -> PlacementSettings:
    """Load settings from a JSON file, falling back to defaults on unreadable content.

    Unreadable files, invalid JSON, and non-object documents fall back to defaults;
    a present-but-unsupported version or any malformed entry raises `SettingsError`.
    """
    source = store if store is not None else DiskJsonStore()
    try:
        data = source.load(path)
    except OSError as exc:
        logger.warning("Cannot read settings file %s: %s; using defaults", path, exc)
        return default_placement_settings()
    except json.JSONDecodeError as exc:
        logger.warning("Invalid JSON in %s: %s; using defaults", path, exc)
        return default_placement_settings()
    if not isinstance(data, dict):
        logger.warning("Top-level settings JSON in %s is not an object; using defaults", path)
        return default_placement_settings()
    return settings_from_dict(data)


def save_placement_settings(settings: PlacementSettings, path: str | Path, *, store: JsonStore | None = None) -> None:
    """Write `settings` to `path` as JSON, emitting codepoints in `U+XXXX` notation and omitting empty entries."""
    source = store if store is not None else DiskJsonStore()
    source.save(path, settings_to_dict(settings))
    logger.info("Settings saved: %s", path)
