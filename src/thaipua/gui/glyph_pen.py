"""Forward fontTools pen calls into `QPainterPath`-compatible sinks."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol

from fontTools.pens.basePen import BasePen

if TYPE_CHECKING:
    from fontTools.ttLib import TTFont


class PathLike(Protocol):
    """Sink matching the subset of `QPainterPath` the pen drives."""

    def moveTo(self, x: float, y: float) -> Any:
        return

    def lineTo(self, x: float, y: float) -> Any:
        return

    def quadTo(self, x1: float, y1: float, x2: float, y2: float) -> Any:
        return

    def cubicTo(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> Any:
        return

    def closeSubpath(self) -> Any:
        return


class QPainterPathPen(BasePen):  # type: ignore[misc]
    """Draw a fontTools glyph into a `PathLike` sink, decomposing nested components."""

    def __init__(self, glyph_set: Any, path: PathLike) -> None:
        """Bind the pen to `glyph_set` for component resolution and `path` as the sink."""
        super().__init__(glyph_set)
        self._path = path

    def _moveTo(self, pt: tuple[float, float]) -> None:
        x, y = pt
        self._path.moveTo(float(x), float(y))

    def _lineTo(self, pt: tuple[float, float]) -> None:
        x, y = pt
        self._path.lineTo(float(x), float(y))

    def _qCurveToOne(self, pt1: tuple[float, float], pt2: tuple[float, float]) -> None:
        x1, y1 = pt1
        x2, y2 = pt2
        self._path.quadTo(float(x1), float(y1), float(x2), float(y2))

    def _curveToOne(self, pt1: tuple[float, float], pt2: tuple[float, float], pt3: tuple[float, float]) -> None:
        x1, y1 = pt1
        x2, y2 = pt2
        x3, y3 = pt3
        self._path.cubicTo(float(x1), float(y1), float(x2), float(y2), float(x3), float(y3))

    def _closePath(self) -> None:
        self._path.closeSubpath()

    def _endPath(self) -> None:
        return

    def addComponent(self, glyphName: str, transform: tuple[float, ...]) -> None:
        """Draw a nested component with its transform applied."""
        if self.glyphSet is None:
            return
        from fontTools.pens.transformPen import TransformPen

        sub_pen = TransformPen(self, transform)
        self.glyphSet[glyphName].draw(sub_pen)


def render_glyph_path(font: TTFont, glyph_name: str | None, path: PathLike, glyph_set: Any | None = None) -> None:
    """Draw one glyph into `path`; no-op for names missing from the font."""
    if glyph_name is None or glyph_name not in font.getGlyphOrder():
        return None
    gs = glyph_set if glyph_set is not None else font.getGlyphSet()
    pen = QPainterPathPen(gs, path)
    gs[glyph_name].draw(pen)


def render_placed_components(
    font: TTFont,
    components: Sequence[tuple[str, Sequence[float]]],
    path: PathLike,
    glyph_set: Any | None = None,
) -> None:
    """Draw placed components into `path`, applying each transform.

    Preview a composite layout from placements alone without installing a glyph;
    components missing from the font are skipped.
    """
    if not components:
        return None
    gs = glyph_set if glyph_set is not None else font.getGlyphSet()
    pen = QPainterPathPen(gs, path)
    for glyph_name, transform in components:
        if glyph_name is None or glyph_name not in font.getGlyphOrder():
            continue
        from fontTools.pens.transformPen import TransformPen

        gs[glyph_name].draw(TransformPen(pen, transform))
