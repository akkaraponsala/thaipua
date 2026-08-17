"""Translate fontTools pen protocol calls into a `QPainterPath`-compatible sink.

`QPainterPathPen` subclasses fontTools' `BasePen` and forwards every `moveTo`, `lineTo`,
quadratic/cubic curve, and `closePath` call to a duck-typed sink.
`PySide6.QtGui.QPainterPath` satisfies the sink protocol, and the unit tests substitute
a lightweight recorder — keeping this module PySide6-free so the pen logic stays unit-
testable without a `QApplication`.

Composite glyphs are decomposed by re-resolving each component through the glyph set
captured at construction time, with the component transform applied via a wrapped
`TransformPen`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol

from fontTools.pens.basePen import BasePen

if TYPE_CHECKING:
    from fontTools.ttLib import TTFont


class PathLike(Protocol):
    """Sink matching the subset of `QPainterPath` the pen drives.

    A `PySide6.QtGui.QPainterPath` exposes these methods directly; tests pass a light
    recorder with the same surface.
    """

    def moveTo(self, x: float, y: float) -> Any:
        """Begin a new subpath at the absolute point `(x, y)`."""
        return

    def lineTo(self, x: float, y: float) -> Any:
        """Append a straight segment from the current point to `(x, y)`."""
        return

    def quadTo(self, x1: float, y1: float, x2: float, y2: float) -> Any:
        """Append a quadratic curve with control `(x1, y1)` and endpoint `(x2, y2)`."""
        return

    def cubicTo(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> Any:
        """Append a cubic curve through controls `(x1,y1)`, `(x2,y2)` to `(x3,y3)`."""
        return

    def closeSubpath(self) -> Any:
        """Close the current subpath by appending a closing segment."""
        return


class QPainterPathPen(BasePen):  # type: ignore[misc]
    """Replay a fontTools glyph draw into a `QPainterPath`-compatible sink.

    Pass a `QPainterPath` from `PySide6.QtGui` (or any `PathLike`) as `path`. The pen
    decomposes nested components via the glyph set captured at construction time,
    applying each component's affine transform through a `TransformPen`.
    """

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
        """Resolve and draw the nested component `glyphName` under `transform`.

        The transform is fontTools' 6-tuple affine `(xx, xy, yx, yy, dx, dy)`;
        `TransformPen` re-applies it to every forwarded primitive so deep component
        chains compose correctly.
        """
        if self.glyphSet is None:
            return
        from fontTools.pens.transformPen import TransformPen

        sub_pen = TransformPen(self, transform)
        self.glyphSet[glyphName].draw(sub_pen)


def render_glyph_path(font: TTFont, glyph_name: str | None, path: PathLike, glyph_set: Any | None = None) -> None:
    """Draw the glyph `glyph_name` from `font` into `path`.

    `None` (or a name missing from the font) is a no-op so callers can render unmapped
    codepoints. `glyph_set` defaults to `font.getGlyphSet()`.
    """
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
    """Draw each `(glyph_name, transform)` pair of `components` into `path`.

    Each transform is a fontTools 6-tuple affine applied to the component exactly like
    `QPainterPathPen.addComponent` applies nested-component transforms, so a composite
    layout can be previewed from placements alone — no installed glyph required.
    Components missing from the font are skipped. `glyph_set` defaults to
    `font.getGlyphSet()`.
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
