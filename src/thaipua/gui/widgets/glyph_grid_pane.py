"""Left pane grid of consonant and PUA variant cells with breadcrumb and pagination."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QEvent, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QEnterEvent, QFont, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from thaipua.gui import icons, theme
from thaipua.gui.state import GRID_COLUMNS, GRID_ROWS
from thaipua.gui.theme import Palette

GridMode = Literal["consonant", "pua"]

_CELL_ART_MARGIN_PX = 5


@dataclass(slots=True)
class CellVisual:
    """Displayable content for one grid cell; `path` takes precedence over `display_text`."""

    key: int
    display_text: str
    subtitle: str
    path: QPainterPath | None = None
    ref_ascent: float = 0.0
    ref_descent: float = 0.0


class _GlyphSurface(QWidget):
    """Cell artwork painting a glyph path scaled to fit, or fallback text."""

    def __init__(self, parent: QWidget | None) -> None:
        """Initialize an empty surface with the fallback sans-serif font."""
        super().__init__(parent)
        self._text = ""
        self._path: QPainterPath | None = None
        self._ref_ascent = 0.0
        self._ref_descent = 0.0
        self._font = QFont("Tahoma", 24)
        self._font.setStyleHint(QFont.StyleHint.SansSerif)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_content(
        self,
        text: str,
        path: QPainterPath | None,
        *,
        ref_ascent: float = 0.0,
        ref_descent: float = 0.0,
    ) -> None:
        """Swap the painted content to `path` (or `text` when `path` is `None`)."""
        self._text = text
        self._path = path
        self._ref_ascent = ref_ascent
        self._ref_descent = ref_descent
        self.update()

    def _uniform_scale(self, rect: QRectF, avail: QRect) -> float:
        """Return one scale shared by every cell: fit the reference box, clamped by the glyph's own box."""
        ref_height = self._ref_ascent + self._ref_descent
        scale = avail.height() / ref_height if ref_height > 0.0 else float("inf")
        if rect.height() > 0:
            scale = min(scale, avail.height() / rect.height())
        if rect.width() > 0:
            scale = min(scale, avail.width() / rect.width())
        return scale

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the composed path at the shared optical size (centered), or the text label."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = theme.get_palette()
        self._paint_content(painter, palette)

    def _paint_content(self, painter: QPainter, palette: Palette) -> None:
        """Paint the glyph path or fallback text."""
        if self._path is not None:
            rect = self._path.boundingRect()
            if rect.width() <= 0 or rect.height() <= 0:
                return
            margin = _CELL_ART_MARGIN_PX
            avail = self.rect().adjusted(margin, margin, -margin, -margin)
            if avail.width() <= 0 or avail.height() <= 0:
                return
            scale = self._uniform_scale(rect, avail)
            painter.setPen(QPen(QColor(palette.GLYPH_PEN), 1.0 / scale))
            painter.setBrush(palette.GLYPH_FILL)
            painter.translate(avail.center().x(), avail.center().y())
            painter.scale(scale, -scale)
            painter.translate(-rect.center().x(), -rect.center().y())
            painter.drawPath(self._path)
        elif self._text:
            painter.setFont(self._font)
            painter.setPen(palette.TEXT_PRIMARY)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)


class _GlyphCell(QFrame):
    """Clickable grid tile emitting its payload key on left click."""

    cell_clicked = Signal(int)

    def __init__(self, visual: CellVisual | None, parent: QWidget | None) -> None:
        """Build a cell for `visual` (or an empty placeholder when `None`)."""
        super().__init__(parent)
        self._key = visual.key if visual is not None else None
        self._empty = visual is None
        self._selected = False
        self._hovered = False
        self._pressed = False
        self.setObjectName("GridCell")
        self.setMinimumSize(76, 76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(2)
        self._art = _GlyphSurface(self)
        self._small = QLabel(self)
        self._small.setObjectName("Subtitle")
        self._small.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._small.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._small.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._art)
        layout.addWidget(self._small)
        if visual is not None:
            self._art.set_content(visual.display_text, visual.path)
            self._small.setText(visual.subtitle)
        self._refresh_style()

    def rebind(self, visual: CellVisual | None) -> None:
        """Swap the cell to new content while keeping widget identity in the grid."""
        self._key = visual.key if visual is not None else None
        self._empty = visual is None
        self._selected = False
        self._pressed = False
        if visual is not None:
            self._art.set_content(
                visual.display_text,
                visual.path,
                ref_ascent=visual.ref_ascent,
                ref_descent=visual.ref_descent,
            )
            self._small.setText(visual.subtitle)
        else:
            self._art.set_content("", None)
            self._small.setText("")
            self.setToolTip("")
        self._refresh_style()

    def set_subtitle_font(self, font: QFont) -> None:
        """Apply `font` to the subtitle (a monospace family is passed by callers)."""
        self._small.setFont(font)

    def set_selected(self, selected: bool) -> None:
        """Toggle the selected highlight state; no-op when unchanged."""
        if self._selected == selected:
            return
        self._selected = selected
        self._refresh_style()

    def enterEvent(self, event: QEnterEvent) -> None:
        """Highlight the cell on hover; handled manually so child labels never paint stale."""
        if not self._empty and (not self._selected) and self.isEnabled():
            self._hovered = True
            self._refresh_style()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        """Clear the hover highlight."""
        if self._hovered:
            self._hovered = False
            self._refresh_style()
        super().leaveEvent(event)

    def _refresh_style(self) -> None:
        """Re-emit the per-cell stylesheet matching the current state."""
        palette = theme.get_palette()
        if self._empty:
            empty_bg = palette.BG_GRID_CELL_EMPTY
            self.setStyleSheet(
                f"QFrame {{ background-color: {empty_bg}; border-radius: 4px; }}QLabel {{ color: {palette.TEXT_DIM}; }}"
            )
        else:
            if self._selected:
                selected_bg = palette.BG_GRID_CELL_SELECTED
                self.setStyleSheet(
                    f"QFrame {{ background-color: {selected_bg}; border-radius: 4px; }}"
                    f"QLabel {{ color: {palette.TEXT_PRIMARY}; }}"
                )
            else:
                if self._pressed:
                    bg = palette.BG_GRID_CELL_SELECTED
                elif self._hovered:
                    bg = palette.BG_GRID_CELL_HOVER
                else:
                    bg = palette.BG_GRID_CELL
                self.setStyleSheet(
                    f"QFrame {{ background-color: {bg}; border-radius: 4px; }}"
                    f"QLabel#Subtitle {{ color: {palette.TEXT_DIM}; font-size: 8pt; }}"
                )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Enter the pressed visual state on a left-button press; emit nothing yet."""
        if self._empty or self._key is None:
            return None
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._refresh_style()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Emit `cell_clicked(self._key)` when a held press ends inside the cell."""
        if not self._pressed:
            return None
        self._pressed = False
        self._refresh_style()
        if (
            not self._empty
            and self._key is not None
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.cell_clicked.emit(self._key)


class GlyphGridPane(QWidget):
    """Left pane — header, breadcrumb, 6x6 grid, and footer pagination."""

    consonant_clicked = Signal(int)
    pua_clicked = Signal(int)
    back_requested = Signal()
    prev_page_requested = Signal()
    next_page_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the pane in an empty consonant-page state."""
        super().__init__(parent)
        self._mode = "consonant"
        self._cells: list[_GlyphCell] = []
        self._subtitle_font = QFont("Consolas", 8)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        outer.addWidget(self._build_breadcrumb_bar(), 1)
        outer.addWidget(self._build_grid(), 6)
        outer.addWidget(self._build_pagination(), 1)
        self.show_consonants([], page_index=0, total_pages=1)
        self.set_font_loaded(False)

    def _build_header(self) -> QLabel:
        """Build the static *Glyph Index* header label."""
        label = QLabel("Glyph Index", self)
        label.setObjectName("PaneHeader")
        return label

    def _build_breadcrumb_bar(self) -> QWidget:
        """Build the breadcrumb row (path text on the left, Back button on right)."""
        bar = QWidget(self)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        self._breadcrumb = QLabel("Path: Consonant", bar)
        self._breadcrumb.setObjectName("Breadcrumb")
        self._back_btn = QPushButton("Back", bar)
        self._back_btn.setIcon(icons.icon("arrow-left"))
        layout.addWidget(self._breadcrumb)
        layout.addStretch(1)
        layout.addWidget(self._back_btn)
        self._back_btn.clicked.connect(self.back_requested)
        return bar

    def _build_grid(self) -> QWidget:
        """Build the empty 6x6 grid container; cells get assigned per page."""
        self._grid_holder = QWidget(self)
        self._grid = QGridLayout(self._grid_holder)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._grid.setSpacing(4)
        for row in range(GRID_ROWS):
            for col in range(GRID_COLUMNS):
                cell = _GlyphCell(None, self._grid_holder)
                cell.set_subtitle_font(self._subtitle_font)
                cell.cell_clicked.connect(self._on_cell_clicked)
                self._grid.addWidget(cell, row, col)
                self._cells.append(cell)
        return self._grid_holder

    def _build_pagination(self) -> QWidget:
        """Build the *< Prev | Page X of Y | Next >* footer row."""
        bar = QWidget(self)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(6)
        self._prev_btn = QPushButton("Prev", bar)
        self._prev_btn.setIcon(icons.icon("chevron-left"))
        self._next_btn = QPushButton("Next", bar)
        self._next_btn.setIcon(icons.icon("chevron-right"))
        self._next_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._page_label = QLabel("Page 1 of 1", bar)
        self._page_label.setObjectName("Breadcrumb")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._prev_btn)
        layout.addStretch(1)
        layout.addWidget(self._page_label)
        layout.addStretch(1)
        layout.addWidget(self._next_btn)
        self._prev_btn.clicked.connect(self.prev_page_requested)
        self._next_btn.clicked.connect(self.next_page_requested)
        return bar

    def set_font_loaded(self, loaded: bool) -> None:
        """Toggle grid-cell interactivity on font availability."""
        self._grid_holder.setEnabled(loaded)

    def refresh_icons(self) -> None:
        """Re-tint the Back/Prev/Next icons for the active theme palette."""
        self._back_btn.setIcon(icons.icon("arrow-left"))
        self._prev_btn.setIcon(icons.icon("chevron-left"))
        self._next_btn.setIcon(icons.icon("chevron-right"))

    def show_consonants(self, visuals: list[CellVisual], *, page_index: int, total_pages: int) -> None:
        """Render the consonant-page grid using `visuals` for the current page."""
        self._mode = "consonant"
        self._breadcrumb.setText("Path: Consonant")
        self._back_btn.setEnabled(False)
        self._render_page(visuals, page_index, total_pages)

    def show_pua(self, visuals: list[CellVisual], *, consonant_label: str, page_index: int, total_pages: int) -> None:
        """Render a PUA-page grid using `visuals`, with the breadcrumb context `[x]`."""
        self._mode = "pua"
        self._breadcrumb.setText(f"Path: Consonant > PUA [{consonant_label}]")
        self._back_btn.setEnabled(True)
        self._render_page(visuals, page_index, total_pages)

    def _render_page(self, visuals: list[CellVisual], page_index: int, total_pages: int) -> None:
        """Refresh the grid cells with `visuals` and update the pagination footer."""
        for idx, cell in enumerate(self._cells):
            visual = visuals[idx] if idx < len(visuals) else None
            cell.rebind(visual)
        self._page_label.setText(f"Page {page_index + 1} of {max(total_pages, 1)}")
        self._prev_btn.setEnabled(total_pages > 1)
        self._next_btn.setEnabled(total_pages > 1)

    def set_selected(self, key: int | None) -> None:
        """Highlight the grid cell whose `key` matches; clear the prior selection."""
        for cell in self._cells:
            cell.set_selected(cell._key == key and (not cell._empty))

    def _on_cell_clicked(self, key: int) -> None:
        """Dispatch the cell click to the spec-appropriate signal by current mode."""
        if self._mode == "consonant":
            self.consonant_clicked.emit(key)
        else:
            self.pua_clicked.emit(key)
