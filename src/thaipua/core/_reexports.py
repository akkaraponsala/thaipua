"""Lazy re-export maps keeping parent packages import-cheap (PEP 562)."""

import importlib
from typing import Any

CORE_EXPORTS: dict[str, str] = {
    "ABOVE_VOWELS": "thaipua.core.font.specs",
    "BELOW_VOWELS": "thaipua.core.font.specs",
    "THAI_CONSONANTS": "thaipua.core.font.specs",
    "TONE_MARKS": "thaipua.core.font.specs",
    "CompositeSpec": "thaipua.core.font.specs",
    "ConsonantSettings": "thaipua.core.domain.settings",
    "GlyphSubstitution": "thaipua.core.font.alternates",
    "GsubAlternateIndex": "thaipua.core.font.alternates",
    "Metadata": "thaipua.core.domain.settings",
    "Offset": "thaipua.core.domain.settings",
    "ParsedStringTable": "thaipua.core.text.string_table",
    "PlacementSettings": "thaipua.core.domain.settings",
    "PuaEncodingMap": "thaipua.core.text.encoding",
    "SnapConfig": "thaipua.core.domain.settings",
    "StringEntry": "thaipua.core.text.string_table",
    "StringTableError": "thaipua.core.text.string_table",
    "ThaiPuaFontGenerator": "thaipua.core.font.composer",
    "decode_files": "thaipua.core.text.file_codec",
    "default_placement_settings": "thaipua.core.domain.settings",
    "detect_text_encoding": "thaipua.core.text.text_encoding",
    "encode_files": "thaipua.core.text.file_codec",
    "find_glyph_substitutions": "thaipua.core.font.alternates",
    "iter_composite_specs": "thaipua.core.font.specs",
    "load_decode_table": "thaipua.core.text.encoding",
    "load_encoding_map": "thaipua.core.text.encoding",
    "load_pua_map_dict": "thaipua.core.pua_map",
    "normalize_sara_am": "thaipua.core.text.encoding",
    "parse_string_table": "thaipua.core.text.string_table",
    "save_placement_settings": "thaipua.core.fonttools.settings",
    "settings_to_dict": "thaipua.core.domain.settings",
    "write_string_table": "thaipua.core.text.string_table",
}
"""Every legacy `thaipua.core` symbol with the submodule that actually defines it."""

APP_EXPORTS: dict[str, str] = dict.fromkeys(CORE_EXPORTS, "thaipua.core")
"""App-level re-exports; all resolve through the (now lazy) `thaipua.core` package."""


def resolve_lazy_export(export_map: dict[str, str], namespace: dict[str, Any], name: str) -> Any:
    """Import `name` from its owning submodule on first use, then cache it; raise `KeyError` when unknown."""
    module = importlib.import_module(export_map[name])
    value = getattr(module, name)
    namespace[name] = value
    return value
