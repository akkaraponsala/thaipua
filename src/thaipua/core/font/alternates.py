"""Discover GSUB single and alternate substitutions for glyph-substitution catalogs."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fontTools.ttLib import TTFont

from thaipua.core.font.specs import ABOVE_VOWELS, BELOW_VOWELS, THAI_CONSONANTS, TONE_MARKS

logger = logging.getLogger(__name__)

SINGLE_SUBST = 1
ALTERNATE_SUBST = 3
EXTENSION_SUBST = 7


def iter_subtables(lookup: Any, extension_type: int) -> Iterator[tuple[int, Any]]:
    """Unwrap extension lookups and yield each subtable with its effective type."""
    for st in lookup.SubTable:
        if lookup.LookupType == extension_type:
            yield (st.ExtensionLookupType, st.ExtSubTable)
        else:
            yield (lookup.LookupType, st)


class GsubAlternateIndex:
    """An index of GSUB single and alternate substitutions for a font."""

    def __init__(self, font: TTFont) -> None:
        """Build the alternate-glyph index by scanning `font`'s GSUB lookups."""
        self.font = font
        self._alternates: dict[str, list[str]] = {}
        self._build()

    def _register(self, glyph_name: str, alt_name: str) -> None:
        """Record `alt_name` as an alternate of `glyph_name`, skipping duplicates."""
        alts = self._alternates.setdefault(glyph_name, [])
        if alt_name not in alts:
            alts.append(alt_name)

    def _register_singles(self, subtable: Any) -> None:
        """Register every `old → new` pair of a GSUB single-substitution subtable."""
        for old, new in subtable.mapping.items():
            self._register(old, new)

    def _register_alternates(self, subtable: Any) -> None:
        """Register every alternate glyph of a GSUB alternate-substitution subtable."""
        for glyph, alt_set in subtable.alternates.items():
            for alt in alt_set:
                self._register(glyph, alt)

    def _build(self) -> None:
        """Scan the font's GSUB lookups, registering single and alternate substitutions."""
        gsub = self.font.get("GSUB")
        if gsub is None or gsub.table.LookupList is None:
            logger.warning("[ALT-GSUB] This font has no GSUB table or no lookups at all")
            return
        for lookup in gsub.table.LookupList.Lookup:
            for lookup_type, subtable in iter_subtables(lookup, EXTENSION_SUBST):
                if lookup_type == SINGLE_SUBST:
                    self._register_singles(subtable)
                elif lookup_type == ALTERNATE_SUBST:
                    self._register_alternates(subtable)
        logger.info("[ALT-GSUB] Discovered alternates for %d glyph(s)", len(self._alternates))

    def get_alternates(self, glyph_name: str) -> list[str]:
        """Return the registered alternates of `glyph_name`, or an empty list."""
        return list(self._alternates.get(glyph_name, []))


@dataclass(slots=True, frozen=True)
class GlyphSubstitution:
    """Catalog entry pairing a codepoint's base glyph with its GSUB alternates."""

    codepoint: int
    base_glyph_name: str | None
    alternate_glyph_names: list[str]


def _categorize(codepoints: set[int], font: TTFont, gsub_index: GsubAlternateIndex) -> list[GlyphSubstitution]:
    """Build a complete ascending-codepoint catalog for one category, including unmapped codepoints."""
    cmap = font.getBestCmap()
    out = []
    for cp in sorted(codepoints):
        base_name = cmap.get(cp)
        alts = list(gsub_index.get_alternates(base_name)) if base_name else []
        out.append(GlyphSubstitution(codepoint=cp, base_glyph_name=base_name, alternate_glyph_names=alts))
    return out


def find_glyph_substitutions(font: TTFont) -> dict[str, list[GlyphSubstitution]]:
    """Build the four-category GSUB substitution catalog for `font`."""
    gsub_index = GsubAlternateIndex(font)
    return {
        "consonants": _categorize(THAI_CONSONANTS, font, gsub_index),
        "tone_marks": _categorize(TONE_MARKS, font, gsub_index),
        "above_vowels": _categorize(ABOVE_VOWELS, font, gsub_index),
        "below_vowels": _categorize(BELOW_VOWELS, font, gsub_index),
    }
