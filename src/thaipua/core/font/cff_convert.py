"""Convert CFF-flavored fonts to TrueType outlines in memory so installs work on `.otf` sources."""

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
    """Return `True` when `font` carries PostScript outlines and no `glyf` table."""
    return "glyf" not in font and "CFF " in font


def convert_cff_to_truetype(font: TTFont) -> None:
    """Replace CFF outlines with TrueType quadratics, preserving metrics, `cmap`, and layout tables.

    A no-op when the font already carries a `glyf` table; only the in-memory copy changes.
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
    """Redraw every glyph as quadratic outlines."""
    quad_glyphs: dict[str, Any] = {}
    for name in glyph_set:
        glyph = glyph_set[name]
        tt_pen = TTGlyphPen(glyph_set)
        cu2qu_pen = Cu2QuPen(tt_pen, MAX_APPROXIMATION_ERROR, reverse_direction=True)
        glyph.draw(cu2qu_pen)
        quad_glyphs[name] = tt_pen.glyph()
    return quad_glyphs


def _update_hmtx_lsbs(font: TTFont, glyf: Any) -> None:
    """Align each `hmtx` left side bearing with the recomputed contour bounds."""
    hmtx = font["hmtx"]
    for name, glyph in glyf.glyphs.items():
        x_min = getattr(glyph, "xMin", None)
        if x_min is not None:
            hmtx[name] = (hmtx[name][0], x_min)


def _rebuild_maxp_for_truetype(font: TTFont, glyf: Any) -> None:
    """Swap the CFF `maxp` for the full TrueType version."""
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
    """Rebuild `post` with glyph names, dropping them on overflow."""
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
