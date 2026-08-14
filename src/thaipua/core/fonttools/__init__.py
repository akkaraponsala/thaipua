"""PUA composite font generation subpackage."""

from thaipua.core.fonttools.alternates import GlyphSubstitution, GsubAlternateIndex, find_glyph_substitutions
from thaipua.core.fonttools.composer import ThaiPuaFontGenerator
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
from thaipua.core.fonttools.specs import (
    ABOVE_VOWELS,
    BELOW_VOWELS,
    THAI_CONSONANTS,
    TONE_MARKS,
    CompositeSpec,
    decompose_thai_cluster,
    iter_composite_specs,
)

__all__ = [
    "ABOVE_VOWELS",
    "BELOW_VOWELS",
    "THAI_CONSONANTS",
    "TONE_MARKS",
    "CompositeSpec",
    "ConsonantSettings",
    "GlyphSubstitution",
    "GsubAlternateIndex",
    "Metadata",
    "Offset",
    "PlacementSettings",
    "SnapConfig",
    "ThaiPuaFontGenerator",
    "decompose_thai_cluster",
    "default_placement_settings",
    "find_glyph_substitutions",
    "iter_composite_specs",
    "load_placement_settings",
    "save_placement_settings",
    "settings_to_dict",
]
