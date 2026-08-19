"""Modal dialogs for the toolbar's Find-Substitution and Settings actions."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thaipua.core.fonttools.alternates import GlyphSubstitution
from thaipua.gui import theme
from thaipua.gui.theme import ThemeMode

ThemeCallback = Callable[[ThemeMode], None]


class FindSubstitutionDialog(QDialog):
    """Modal GSUB catalog browser with a free-text codepoint/glyph filter."""

    def __init__(self, catalog: dict[str, list[GlyphSubstitution]], parent: QWidget | None) -> None:
        """Build the dialog from `catalog`, a `find_glyph_substitutions` result.

        `catalog` is a per-category `{consonants, tone_marks, above_vowels,
        below_vowels}` map.
        """
        super().__init__(parent)
        self.setWindowTitle("Find Substitutions")
        self.resize(720, 520)
        outer = QVBoxLayout(self)
        outer.addLayout(self._build_search_row())
        outer.addWidget(self._build_tree(catalog), 1)
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)
        outer.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _build_search_row(self) -> QHBoxLayout:
        """Build the `Filter:` search input and Clear button."""
        row = QHBoxLayout()
        row.addWidget(QLabel("Filter:", self))
        self._query = QLineEdit(self)
        self._query.setPlaceholderText("codepoint, glyph name, or alternate")
        self._query.textChanged.connect(self._apply_filter)
        row.addWidget(self._query, 1)
        clear_btn = QPushButton("Clear", self)
        clear_btn.clicked.connect(self._query.clear)
        row.addWidget(clear_btn)
        return row

    def _build_tree(self, catalog: dict[str, list[GlyphSubstitution]]) -> QTreeWidget:
        """Build the category-grouped tree widget from `catalog`."""
        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["Category", "Codepoint", "Base Glyph", "Alternates"])
        self._all_items = []
        for category, entries in catalog.items():
            cat_root = QTreeWidgetItem(self._tree, [category, "", "", ""])
            cat_root.setExpanded(True)
            for entry in entries:
                cp_label = f"U+{entry.codepoint:04X}"
                alts = ", ".join(entry.alternate_glyph_names)
                row = QTreeWidgetItem(cat_root, [category, cp_label, entry.base_glyph_name or "(unmapped)", alts])
                self._all_items.append((category, entry, row))
                cat_root.addChild(row)
        return self._tree

    def _apply_filter(self, text: str) -> None:
        """Hide rows whose flattened text does not contain `text`."""
        needle = text.strip().lower()
        if not needle:
            for _, _, row in self._all_items:
                row.setHidden(False)
        else:
            for category, entry, row in self._all_items:
                haystack = " ".join(
                    [category, f"U+{entry.codepoint:04X}", entry.base_glyph_name or "", *entry.alternate_glyph_names]
                ).lower()
                row.setHidden(needle not in haystack)


class SettingsDialog(QDialog):
    """Application preferences: live Light/Dark/System theme switch.

    The theme radios apply the chosen `ThemeMode` immediately through an
    `on_theme_changed` callback (wired by the main window to `apply_theme`, persistence,
    and a pane/icon refresh).
    """

    def __init__(
        self, parent: QWidget | None, *, current_mode: ThemeMode | None, on_theme_changed: ThemeCallback | None
    ) -> None:
        """Build the preferences dialog.

        `current_mode=None` defaults to `theme.current_theme_mode()`.
        `on_theme_changed=None` leaves the radios inert (useful for tests/headless).
        """
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(440, 260)
        self._on_theme_changed = on_theme_changed
        self._current_mode = current_mode if current_mode is not None else theme.current_theme_mode()
        outer = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Theme:", self._build_theme_row())
        outer.addLayout(form)
        outer.addStretch(1)
        outer.addLayout(self._build_button_row())

    def _build_theme_row(self) -> QWidget:
        """Build the Theme radio row — Light / Dark (default) / System."""
        holder = QWidget(self)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        self._theme_group = QButtonGroup(self)
        self._theme_radios = {}
        labels = [(ThemeMode.LIGHT, "Light"), (ThemeMode.DARK, "Dark"), (ThemeMode.SYSTEM, "System")]
        for mode, label in labels:
            radio = QRadioButton(label, self)
            radio.setChecked(mode == self._current_mode)
            radio.toggled.connect(lambda checked, m=mode: self._on_theme_radio(m, checked))
            self._theme_group.addButton(radio)
            self._theme_radios[mode] = radio
            row.addWidget(radio)
        row.addStretch(1)
        return holder

    def _on_theme_radio(self, mode: ThemeMode, checked: bool) -> None:
        """Forward a freshly-checked theme radio to the live-apply callback."""
        if not checked or self._on_theme_changed is None:
            return None
        self._on_theme_changed(mode)

    def selected_theme_mode(self) -> ThemeMode:
        """Return the `ThemeMode` whose radio is currently checked."""
        for mode, radio in self._theme_radios.items():
            if radio.isChecked():
                return mode
        return self._current_mode

    def _build_button_row(self) -> QHBoxLayout:
        """Build the Close button row."""
        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        return row
