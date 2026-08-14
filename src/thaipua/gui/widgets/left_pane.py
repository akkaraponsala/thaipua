"""Left pane: the glyph index grid with breadcrumb and pagination.

`GlyphGridPane` renders two contextual pages: the Consonant Page (42 Thai consonants,
paginated 36 per page) and the PUA Page, the variants of a selected consonant (also 36
per page). Each 6x6 grid is a `QGridLayout` of `_GlyphCell` frames; the pane
differentiates click semantics via its current mode so the emitted signal matches the
state machine (`consonant_clicked` vs `pua_clicked`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QEnterEvent, QFont, QMouseEvent
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from thaipua.gui import icons, theme
from thaipua.gui.state import GRID_COLUMNS, GRID_ROWS

GridMode = Literal["consonant", "pua"]


@dataclass(slots=True)
class CellVisual:
    """One grid cell's displayable content.

    `key` is a consonant codepoint on the index page or a PUA codepoint on the variant
    page.
    """

    key: int
    display_text: str
    subtitle: str


class _GlyphCell(QFrame):
    """A single borderless grid tile that emits its payload on a left click."""

    cell_clicked = Signal(int)

    def __init__(self, visual: CellVisual | None, parent: QWidget | None) -> None:
        """Build a cell for `visual` (or an empty placeholder when `None`)."""
        super().__init__(parent)
        self._key = visual.key if visual is not None else None
        self._empty = visual is None
        self._selected = False
        self._hovered = False
        self.setObjectName("GridCell")
        self.setMinimumSize(76, 76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(2)
        self._big = QLabel(self)
        self._big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._big.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._big.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._small = QLabel(self)
        self._small.setObjectName("Subtitle")
        self._small.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._small.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._small.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._big)
        layout.addWidget(self._small)
        if visual is not None:
            self._big.setText(visual.display_text)
            self._small.setText(visual.subtitle)
        self._refresh_style()

    def rebind(self, visual: CellVisual | None) -> None:
        """Rebind this existing cell to `visual` (or `None` for an empty slot).

        Reuses the live `QLabel` children and `cell_clicked` signal set up at
        construction so the containing `QGridLayout` keeps its widget identity.
        """
        self._key = visual.key if visual is not None else None
        self._empty = visual is None
        self._selected = False
        if visual is not None:
            self._big.setText(visual.display_text)
            self._small.setText(visual.subtitle)
        else:
            self._big.setText("")
            self._small.setText("")
        self._refresh_style()

    def set_big_font(self, font: QFont | None) -> None:
        """Apply `font` (or a default sans-serif fallback) to the big label."""
        if font is None:
            fallback = QFont("Tahoma", 24)
            fallback.setStyleHint(QFont.StyleHint.SansSerif)
            self._big.setFont(fallback)
        else:
            sized = QFont(font)
            sized.setPointSize(26)
            self._big.setFont(sized)

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
        """Highlight the cell on hover (only for clickable, unselected cells).

        Driven manually rather than via a `QFrame:hover` stylesheet rule: a stylesheet
        reinstall triggers a full repaint including the regions behind the child
        `QLabel`s, which a pure `:hover` pseudo-state would leave stale. Qt still
        delivers `Enter` events to disabled widgets (unlike mouse press/release), so
        the `isEnabled()` check keeps the grid visually inert until a font is loaded.
        """
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
                bg = palette.BG_GRID_CELL_HOVER if self._hovered else palette.BG_GRID_CELL
                self.setStyleSheet(
                    f"QFrame {{ background-color: {bg}; border-radius: 4px; }}"
                    f"QLabel#Subtitle {{ color: {palette.TEXT_DIM}; font-size: 8pt; }}"
                )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Emit `cell_clicked(self._key)` on a left-button press; ignore when empty."""
        if self._empty or self._key is None:
            return None
        if event.button() == Qt.MouseButton.LeftButton:
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
        self._loaded_font: QFont | None = None
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
                cell.set_big_font(self._loaded_font)
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

    def set_loaded_font(self, font: QFont | None) -> None:
        """Set the font used by every cell's big visual; updates live on refresh."""
        self._loaded_font = font
        for cell in self._cells:
            cell.set_big_font(font)

    def set_font_loaded(self, loaded: bool) -> None:
        """Toggle grid-cell interactivity on font availability.

        The consonant grid is populated from a fixed constant rather than the loaded
        font, so the 42 cells render even before a font is opened. Disabling the grid
        holder keeps the cells visible (informational) but blocks selection until a
        font loads, so the user cannot drop into a PUA page with no composites and
        enable per-consonant controls with nothing to compose against.
        """
        self._grid_holder.setEnabled(loaded)

    def refresh_icons(self) -> None:
        """Re-tint the Back / Prev / Next icons for the active theme palette.

        Called by the main window after a theme switch (which follows
        `icons.clear_cache`) so the breadcrumb/pager icons do not keep a stale light-
        gray stroke on a newly light background.
        """
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
        """Refresh the 36 grid cells with `visuals` and the pagination footer.

        Each existing `_GlyphCell` is rebound visually rather than rebuilt, so the
        `cell_clicked` signal wiring set up at construction stays intact.
        """
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
