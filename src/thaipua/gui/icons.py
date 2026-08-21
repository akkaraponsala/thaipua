"""PySide6 `QIcon` provider backed by tinted SVG assets for the toolbar and pane buttons.

Every icon is a static SVG under `<assets>/icons/<name>.svg` — a 24-unit viewBox stroke
drawing with `stroke-width="2"`, round caps/joins, and `stroke="currentColor"`. `Normal`
mode is tinted with the palette's `ICON_FG` (or an explicit `color`), `Disabled` mode
with `TEXT_DIM`: the explicit disabled tint is needed because mid-gray `Normal` strokes
survive Qt's coarse auto-`Disabled` desaturation nearly unchanged, so a prepared dim
tint is the only way a disabled button visibly dims.

A theme switch must be followed by `clear_cache()` and a re-`setIcon` pass — the tinted
`QSvgRenderer` engines cache by tint.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from thaipua.core.constants import ASSETS_DIR
from thaipua.gui import theme

IconName = Literal[
    "folder-open",
    "save",
    "binary",
    "file-input",
    "search",
    "settings",
    "table",
    "arrow-left",
    "axis-x",
    "axis-y",
    "chevron-left",
    "chevron-right",
    "check",
]
_ICON_DIR: Final[Path] = ASSETS_DIR / "icons"
_CURRENT_COLOR: Final[str] = "currentColor"
_cache: dict[tuple[str, str], QIcon] = {}
_renderer_cache: dict[tuple[str, str], QSvgRenderer] = {}


def _load_svg(name: str) -> bytes:
    """Read the `name` icon's SVG asset, raising `FileNotFoundError` when absent."""
    return (_ICON_DIR / f"{name}.svg").read_bytes()


def _renderer_for(name: str, tint: str) -> QSvgRenderer:
    """Return a cached `QSvgRenderer` for `name` with the `currentColor` token set to `tint`.

    The SVG is read once per `name` and re-typed per `tint`, so a theme switch (new
    `ICON_FG`/`TEXT_DIM`) builds a fresh renderer without re-reading disk.
    """
    key = (name, tint)
    cached = _renderer_cache.get(key)
    if cached is not None:
        return cached
    svg_text = _load_svg(name).decode("utf-8").replace(_CURRENT_COLOR, tint)
    renderer = QSvgRenderer(svg_text.encode("utf-8"))
    _renderer_cache[key] = renderer
    return renderer


class _SvgIconEngine(QIconEngine):
    """`QIconEngine` that paints one `IconName` SVG asset with a caller-chosen tint.

    The engine keeps separate `QSvgRenderer` instances for the `Normal` and `Disabled`
    tints and repaints whichever matches `mode` at the caller's request: `Normal` mode
    in the constructor's `normal` tint (or the palette's `ICON_FG`), `Disabled` mode in
    `disabled` (the palette's `TEXT_DIM`) so a disabled button visibly dims.
    """

    def __init__(self, name: str, normal: str, disabled: str) -> None:
        super().__init__()
        self._name = name
        self._normal = normal
        self._disabled = disabled

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        tint = self._disabled if mode == QIcon.Mode.Disabled else self._normal
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _renderer_for(self._name, tint).render(painter, QRectF(rect))
        painter.restore()

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        pm = QPixmap(size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pm

    def clone(self) -> QIconEngine:
        return _SvgIconEngine(self._name, self._normal, self._disabled)


def icon(name: IconName, *, color: str | None = None) -> QIcon:
    """Return a cached, theme-tinted, SVG-backed `QIcon` for one of the `IconName` keys.

    `color=None` defaults to the active palette's `ICON_FG`; `Disabled` mode uses the
    palette's `TEXT_DIM` so a button flipped off by `setEnabled(False)` visibly dims. An
    unknown name raises `KeyError`; a missing SVG asset raises `FileNotFoundError`.
    """
    tint = color if color is not None else theme.get_palette().ICON_FG
    disabled_tint = theme.get_palette().TEXT_DIM
    cache_key = (name, tint)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    qi = QIcon(_SvgIconEngine(name, tint, disabled_tint))
    _cache[cache_key] = qi
    return qi


def clear_cache() -> None:
    """Drop every cached `QIcon` and `QSvgRenderer` (test isolation helper).

    Also frees the tinted renderers so a theme switch rebuilds them from the current
    palette.
    """
    _cache.clear()
    _renderer_cache.clear()


__all__ = ["IconName", "clear_cache", "icon"]
