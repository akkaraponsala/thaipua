"""Top action toolbar: Open/Save Font, Decode PUA, Encode Thai, Find Substitutions, Settings."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from thaipua.gui import icons


class TopToolbar(QWidget):
    """Horizontal action bar emitting a `*_requested` signal per button."""

    open_font_requested = Signal()
    save_font_requested = Signal()
    decode_pua_requested = Signal()
    encode_thai_requested = Signal()
    edit_mapping_requested = Signal()
    find_substitution_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the toolbar with empty state — no font loaded yet."""
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        self._open_btn = QPushButton(self)
        self._open_btn.setIcon(icons.icon("folder-open"))
        self._open_btn.setToolTip("Open Font")
        self._save_btn = QPushButton(self)
        self._save_btn.setIcon(icons.icon("save"))
        self._save_btn.setToolTip("Save Font")
        self._decode_btn = QPushButton(self)
        self._decode_btn.setIcon(icons.icon("file-type-corner"))
        self._decode_btn.setToolTip("Decode PUA → Thai")
        self._encode_btn = QPushButton(self)
        self._encode_btn.setIcon(icons.icon("file-digit"))
        self._encode_btn.setToolTip("Encode Thai → PUA")
        self._find_btn = QPushButton(self)
        self._find_btn.setIcon(icons.icon("search"))
        self._find_btn.setToolTip("Find Substitutions")
        self._mapping_btn = QPushButton(self)
        self._mapping_btn.setIcon(icons.icon("table"))
        self._mapping_btn.setToolTip("Edit PUA Mapping")
        self._settings_btn = QPushButton(self)
        self._settings_btn.setIcon(icons.icon("settings"))
        self._settings_btn.setToolTip("Settings")
        for btn in [
            self._open_btn,
            self._save_btn,
            self._decode_btn,
            self._encode_btn,
            self._find_btn,
            self._mapping_btn,
            self._settings_btn,
        ]:
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            btn.setMinimumSize(28, 28)
        layout.addWidget(self._open_btn)
        layout.addWidget(self._save_btn)
        layout.addWidget(self._decode_btn)
        layout.addWidget(self._encode_btn)
        layout.addWidget(self._find_btn)
        layout.addWidget(self._mapping_btn)
        layout.addStretch(1)
        layout.addWidget(self._settings_btn)
        self._open_btn.clicked.connect(self.open_font_requested)
        self._save_btn.clicked.connect(self.save_font_requested)
        self._decode_btn.clicked.connect(self.decode_pua_requested)
        self._encode_btn.clicked.connect(self.encode_thai_requested)
        self._find_btn.clicked.connect(self.find_substitution_requested)
        self._mapping_btn.clicked.connect(self.edit_mapping_requested)
        self._settings_btn.clicked.connect(self.settings_requested)
        self.set_font_loaded(False)

    def set_font_loaded(self, loaded: bool) -> None:
        """Toggle the actions that require a loaded font."""
        self._save_btn.setEnabled(loaded)
        self._decode_btn.setEnabled(loaded)
        self._encode_btn.setEnabled(loaded)
        self._mapping_btn.setEnabled(loaded)
        self._find_btn.setEnabled(loaded)

    def refresh_icons(self) -> None:
        """Re-tint every button icon for the active theme palette."""
        self._open_btn.setIcon(icons.icon("folder-open"))
        self._save_btn.setIcon(icons.icon("save"))
        self._decode_btn.setIcon(icons.icon("file-type-corner"))
        self._encode_btn.setIcon(icons.icon("file-digit"))
        self._find_btn.setIcon(icons.icon("search"))
        self._mapping_btn.setIcon(icons.icon("table"))
        self._settings_btn.setIcon(icons.icon("settings"))
