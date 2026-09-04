"""Settings file persistence; the schema itself lives in `core.domain.settings`."""

from thaipua.core.fonttools.settings import (
    load_placement_settings,
    save_placement_settings,
)

__all__ = [
    "load_placement_settings",
    "save_placement_settings",
]
