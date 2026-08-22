"""Cached glyph bounding-box reading for composite-glyph generation.

Bounding boxes are computed via `BoundsPen` over the font's glyph set, which
transparently flattens nested component composites, and are cached per glyph name for
the lifetime of a `BoundingBoxCache`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fontTools.pens.boundsPen import BoundsPen

if TYPE_CHECKING:
    from fontTools.ttLib import TTFont

logger = logging.getLogger(__name__)

BoundingBoxTuple = tuple[int, int, int, int]


@dataclass(slots=True, frozen=True)
class BoundingBox:
    """An immutable glyph bounding box in font design units."""

    x_min: int
    y_min: int
    x_max: int
    y_max: int

    def as_tuple(self) -> BoundingBoxTuple:
        """Return the bounding box as an `(x_min, y_min, x_max, y_max)` tuple."""
        return (self.x_min, self.y_min, self.x_max, self.y_max)


class BoundingBoxCache:
    """Cached reader of glyph bounding boxes for a single font."""

    def __init__(self, font: TTFont) -> None:
        """Build a bounding-box reader backed by `font`'s glyph set."""
        self._font = font
        self._glyphset = font.getGlyphSet()
        self._cache: dict[str, BoundingBox | None] = {}

    def get_bounding_box(self, glyph_name: str | None) -> BoundingBox | None:
        """Return the bounding box of `glyph_name`, computing it on first access.

        Returns `None` for an empty name or a glyph that is absent from the font or has
        no drawable contour.
        """
        if not glyph_name:
            return None
        if glyph_name in self._cache:
            return self._cache[glyph_name]
        bounding_box = self._compute_bounding_box(glyph_name)
        self._cache[glyph_name] = bounding_box
        return bounding_box

    def invalidate(self, glyph_name: str | None) -> None:
        """Drop `glyph_name` from the cache so the next access recomputes it.

        Call after a glyph's contours are replaced in place (e.g. a composite rebuilt at
        an existing name) to avoid serving a stale bounding box.
        """
        if glyph_name is not None:
            self._cache.pop(glyph_name, None)

    def _compute_bounding_box(self, glyph_name: str) -> BoundingBox | None:
        """Compute the bounding box of `glyph_name`, or `None` if undrawable."""
        if glyph_name not in self._font.getGlyphOrder():
            return None
        try:
            glyph = self._glyphset[glyph_name]
        except KeyError:
            return None
        pen = BoundsPen(self._glyphset)
        glyph.draw(pen)
        bounds = pen.bounds
        if bounds is None:
            return None
        x_min, y_min, x_max, y_max = bounds
        return BoundingBox(int(x_min), int(y_min), int(x_max), int(y_max))
