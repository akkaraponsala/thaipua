"""Collapsible section widget with a clickable header for space-constrained panes."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from thaipua.gui import theme


class CollapsibleSection(QFrame):
    """A titled section whose body hides behind a clickable header row."""

    expanded_changed = Signal(bool)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        """Lay out the header row and an empty hidden body; start collapsed."""
        super().__init__(parent)
        self.setObjectName("CollapsibleSection")
        self._expanded = False
        self._content: QWidget | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._header_row = QWidget(self)
        self._header_row.setObjectName("SectionHeader")
        self._header_row.setStyleSheet("background: transparent; border: none;")
        header_layout = QHBoxLayout(self._header_row)
        header_layout.setContentsMargins(8, 3, 8, 3)
        header_layout.setSpacing(4)
        self._toggle_btn = QToolButton(self._header_row)
        self._toggle_btn.setObjectName("SectionToggle")
        self._toggle_btn.setText(title)
        self._toggle_btn.setAutoRaise(True)
        self._toggle_btn.setArrowType(Qt.ArrowType.RightArrow)
        self._toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(lambda: self.set_expanded(not self._expanded))
        self._summary_label = QLabel("", self._header_row)
        self._summary_label.setObjectName("SectionSummary")
        header_layout.addWidget(self._toggle_btn)
        header_layout.addStretch(1)
        header_layout.addWidget(self._summary_label)
        self._body = QFrame(self)
        self._body.setObjectName("SectionBody")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(8, 4, 8, 6)
        self._body_layout.setSpacing(0)
        outer.addWidget(self._header_row)
        outer.addWidget(self._body)
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply per-widget styles; bypass app-sheet specificity."""
        palette = theme.get_palette()
        self.setStyleSheet(
            f"QFrame#CollapsibleSection {{ background-color: {palette.BG_PANE_HEADER}; "
            f"border: 1px solid {palette.BORDER}; border-radius: 6px; }}"
        )
        is_dark = palette is theme.DARK_PALETTE
        combo_bg = "#4A4D51" if is_dark else "#FFFFFF"
        combo_border = "#5F6368" if is_dark else palette.BORDER
        self._body.setStyleSheet(
            f"QFrame#SectionBody {{ background-color: {palette.BG_PANE}; "
            f"border-top: 1px solid {palette.BORDER}; "
            f"border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; }}"
            f"QFrame#SectionBody QComboBox {{ background-color: {combo_bg}; "
            f"border: 1px solid {combo_border}; border-radius: 4px; }}"
            f"QFrame#SectionBody QComboBox:focus {{ border-color: {palette.BORDER_FOCUS}; }}"
            f"QFrame#SectionBody QAbstractSpinBox {{ background-color: {combo_bg}; "
            f"border: 1px solid {combo_border}; border-radius: 4px; }}"
            f"QFrame#SectionBody QAbstractSpinBox:focus {{ border-color: "
            f"{palette.BORDER_FOCUS}; }}"
        )

    def refresh_style(self) -> None:
        """Re-apply palette-dependent per-widget styles after a theme switch."""
        self._apply_styles()

    def set_content(self, content: QWidget) -> None:
        """Install `content` as the collapsible body, hidden until expanded."""
        self._content = content
        content.setVisible(self._expanded)
        self._body_layout.addWidget(content)

    def is_expanded(self) -> bool:
        """Return whether the body is currently visible."""
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        """Show or hide the body, rotating the header arrow; emit only on change."""
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._toggle_btn.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        if self._content is not None:
            self._content.setVisible(expanded)
        self.expanded_changed.emit(expanded)

    def set_summary(self, text: str | None) -> None:
        """Set the trailing header hint, hiding it when `text` is `None`."""
        self._summary_label.setText(text or "")
        self._summary_label.setVisible(text is not None)
