"""Scan a font's PUA range and report each occupied slot's owner and content for user review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from thaipua.core.constants import PUA_RANGE_END, PUA_RANGE_START
from thaipua.core.fonttools.ownership import SlotOwnership, classify_pua_slot

if TYPE_CHECKING:
    from fontTools.ttLib import TTFont


@dataclass(slots=True, frozen=True)
class PuaOccupant:
    """One occupied PUA codepoint with enough context for a user decision."""

    codepoint: int
    glyph_name: str
    ownership: SlotOwnership
    detail: str


def scan_pua_occupants(font: TTFont) -> list[PuaOccupant]:
    """Classify every cmap entry inside the PUA range, sorted by codepoint ascending."""
    glyf = font.get("glyf")
    cmap = font.getBestCmap()
    occupants = []
    for codepoint in sorted(cmap):
        if not PUA_RANGE_START <= codepoint <= PUA_RANGE_END:
            continue
        glyph_name = cmap[codepoint]
        ownership = classify_pua_slot(glyph_name, glyf)
        occupants.append(PuaOccupant(codepoint, glyph_name, ownership, _describe(glyph_name, glyf)))
    return occupants


def _describe(glyph_name: str, glyf: Any) -> str:
    """Return a short human-readable description of the glyph occupying one slot."""
    if glyf is None:
        return "font has no glyf table"
    if glyph_name not in glyf:
        return "dangling cmap entry"
    glyph = glyf[glyph_name]
    if glyph.isComposite():
        names = [component.glyphName for component in getattr(glyph, "components", [])]
        return f"composite of {', '.join(names)}" if names else "empty composite"
    contours = getattr(glyph, "numberOfContours", None)
    if contours is None:
        return "simple glyph"
    return f"simple glyph ({contours} contour{'s' if contours != 1 else ''})"
