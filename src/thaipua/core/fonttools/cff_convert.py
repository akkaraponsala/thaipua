"""In-place CFF-to-TrueType outline conversion for editable working copies.

Composite installs require a `glyf` table, so a CFF-flavored source (.otf) is rebuilt
as quadratic TrueType outlines at load time: every glyph's cubics are approximated by
cu2qu (`MAX_APPROXIMATION_ERROR` font units of deviation), the `maxp`/`post` tables are
swapped to their TrueType shapes, and `sfntVersion` flips to TrueType. Only the
in-memory working copy changes — the source file on disk is never touched, and saved
output becomes a `.ttf`. The routine follows fontTools' reference `otf2ttf` recipe.
"""

from __future__ import annotations

import logging
from typing import Any

from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable

logger = logging.getLogger(__name__)

MAX_APPROXIMATION_ERROR = 1.0
"""Maximum cu2qu deviation from the source cubic outlines, in font units."""

_POST_FORMAT_WITH_NAMES = 2.0
_TRUETYPE_SFNT_VERSION = "\000\001\000\000"


def has_cff_outlines(font: TTFont) -> bool:
    """Return True when `font` carries PostScript outlines and no `glyf` table."""
    return "glyf" not in font and "CFF " in font


def convert_cff_to_truetype(font: TTFont) -> None:
    """Replace the CFF outlines of the in-memory `font` with TrueType quadratics.

    Glyph order, names, metrics tables, cmap, and GSUB/GPOS layout data pass through
    unchanged; only outline storage and flavor markers are rebuilt. A no-op when the
    font already has a `glyf` table.
    """
    if not has_cff_outlines(font):
        return
    glyph_order = font.getGlyphOrder()
    glyph_set = font.getGlyphSet()
    font["loca"] = newTable("loca")
    font["glyf"] = glyf = newTable("glyf")
    glyf.glyphOrder = glyph_order
    glyf.glyphs = _glyphs_to_quadratic(glyph_set)
    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]
    glyf.compile(font)
    _update_hmtx_lsbs(font, glyf)
    _rebuild_maxp_for_truetype(font, glyf)
    _rebuild_post_for_truetype(font, glyph_order)
    font.sfntVersion = _TRUETYPE_SFNT_VERSION
    logger.info("Converted %d CFF glyph outlines to TrueType quadratics", len(glyf.glyphs))


def _glyphs_to_quadratic(glyph_set: Any) -> dict[str, Any]:
    """Redraw every glyph's contours through cu2qu into `TTGlyphPen` quadratics."""
    quad_glyphs: dict[str, Any] = {}
    for name in glyph_set:
        glyph = glyph_set[name]
        tt_pen = TTGlyphPen(glyph_set)
        cu2qu_pen = Cu2QuPen(tt_pen, MAX_APPROXIMATION_ERROR, reverse_direction=True)
        glyph.draw(cu2qu_pen)
        quad_glyphs[name] = tt_pen.glyph()
    return quad_glyphs


def _update_hmtx_lsbs(font: TTFont, glyf: Any) -> None:
    """Align each `hmtx` left side bearing with the recomputed contour `xMin`."""
    hmtx = font["hmtx"]
    for name, glyph in glyf.glyphs.items():
        x_min = getattr(glyph, "xMin", None)
        if x_min is not None:
            hmtx[name] = (hmtx[name][0], x_min)


def _rebuild_maxp_for_truetype(font: TTFont, glyf: Any) -> None:
    """Swap the version-0.5 CFF `maxp` for the full version-1.0 TrueType shape."""
    glyphs = list(glyf.glyphs.values())
    maxp = newTable("maxp")
    maxp.tableVersion = 0x00010000
    maxp.maxZones = 1
    maxp.maxTwilightPoints = 0
    maxp.maxStorage = 0
    maxp.maxFunctionDefs = 0
    maxp.maxInstructionDefs = 0
    maxp.maxStackElements = 0
    maxp.maxSizeOfInstructions = 0
    maxp.maxComponentElements = max((len(getattr(g, "components", [])) for g in glyphs), default=0)
    font["maxp"] = maxp
    maxp.compile(font)


def _rebuild_post_for_truetype(font: TTFont, glyph_order: list[str]) -> None:
    """Point `post` at format 2.0 carrying the glyph names; drop names on overflow."""
    post = font["post"]
    post.formatType = _POST_FORMAT_WITH_NAMES
    post.extraNames = []
    post.mapping = {}
    post.glyphOrder = glyph_order
    try:
        post.compile(font)
    except OverflowError:
        post.formatType = 3.0
        logger.warning("Dropping glyph names, they do not fit in 'post' table.")
