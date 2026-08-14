"""GSUB single and alternate substitution discovery for the PUA font generator.

`GsubAlternateIndex` indexes a font's GSUB single and alternate substitutions, and
`find_glyph_substitutions` builds the per-category catalog backing `glyph_substitutions`
settings discovery.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fontTools.ttLib import TTFont

from thaipua.core.fonttools.common import ALTERNATE_SUBST, EXTENSION_SUBST, SINGLE_SUBST, iter_subtables
from thaipua.core.fonttools.specs import ABOVE_VOWELS, BELOW_VOWELS, THAI_CONSONANTS, TONE_MARKS

logger = logging.getLogger(__name__)


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

    def _process_single(self, subtable: Any) -> None:
        """Register every `old -> new` pair of a GSUB single-substitution subtable."""
        for old, new in subtable.mapping.items():
            self._register(old, new)

    def _process_alternate(self, subtable: Any) -> None:
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
                    self._process_single(subtable)
                elif lookup_type == ALTERNATE_SUBST:
                    self._process_alternate(subtable)
        logger.info("[ALT-GSUB] Discovered alternates for %d glyph(s)", len(self._alternates))

    def get_alternates(self, glyph_name: str) -> list[str]:
        """Return the alternate glyph names registered for `glyph_name`.

        Returns an empty list when no alternates are registered.
        """
        return list(self._alternates.get(glyph_name, []))


@dataclass(slots=True, frozen=True)
class GlyphSubstitution:
    """A category entry in a `find_glyph_substitutions` catalog.

    Attributes:
        base_glyph_name: The glyph name `codepoint` maps to in the font's cmap, or
            `None` when the codepoint has no cmap entry.
        alternate_glyph_names: The GSUB alternate glyph names registered for
            `base_glyph_name` (empty when unmapped or no alternates), in GSUB discovery
            order.
    """

    codepoint: int
    base_glyph_name: str | None
    alternate_glyph_names: list[str]


def _categorize(codepoints: set[int], font: TTFont, gsub_index: GsubAlternateIndex) -> list[GlyphSubstitution]:
    """Build an ascending-codepoint-ordered catalog for one category.

    Every codepoint in `codepoints` produces exactly one `GlyphSubstitution`, regardless
    of cmap coverage or alternate count, so the caller renders a complete catalog per
    category.
    """
    cmap = font.getBestCmap()
    out = []
    for cp in sorted(codepoints):
        base_name = cmap.get(cp)
        alts = list(gsub_index.get_alternates(base_name)) if base_name else []
        out.append(GlyphSubstitution(codepoint=cp, base_glyph_name=base_name, alternate_glyph_names=alts))
    return out


def find_glyph_substitutions(font: TTFont) -> dict[str, list[GlyphSubstitution]]:
    """Build a per-category GSUB substitution catalog for `font`.

    Returns a `dict` with exactly the four category keys (`consonants`, `tone_marks`,
    `above_vowels`, `below_vowels`), each mapping to a per-codepoint `GlyphSubstitution`
    list in ascending-codepoint order, including codepoints with no cmap entry or
    alternates.
    """
    gsub_index = GsubAlternateIndex(font)
    return {
        "consonants": _categorize(THAI_CONSONANTS, font, gsub_index),
        "tone_marks": _categorize(TONE_MARKS, font, gsub_index),
        "above_vowels": _categorize(ABOVE_VOWELS, font, gsub_index),
        "below_vowels": _categorize(BELOW_VOWELS, font, gsub_index),
    }
