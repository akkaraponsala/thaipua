"""Placement-settings subpackage; font modules live in `core.font`."""

from thaipua.core.fonttools.settings import (
    ConsonantSettings,
    Metadata,
    Offset,
    PlacementSettings,
    SnapConfig,
    default_placement_settings,
    load_placement_settings,
    save_placement_settings,
    settings_to_dict,
)

__all__ = [
    "ConsonantSettings",
    "Metadata",
    "Offset",
    "PlacementSettings",
    "SnapConfig",
    "default_placement_settings",
    "load_placement_settings",
    "save_placement_settings",
    "settings_to_dict",
]
