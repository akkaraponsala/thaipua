"""Footer status bar showing the loaded font filename and dirty indicator."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QStatusBar, QWidget


class StatusBar(QStatusBar):
    """Footer status bar showing the loaded font name, unsaved-changes marker, and a persistent notice."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the footer with no font, no unsaved edits, and no notice."""
        super().__init__(parent)
        self._font_name: str | None = None
        self._dirty = False
        self._notice: str | None = None
        self._refresh()

    def set_font(self, path: str | None) -> None:
        """Update the displayed font name from `path` (basename only)."""
        self._font_name = Path(path).name if path is not None else None
        self._refresh()

    def set_dirty(self, dirty: bool) -> None:
        """Toggle the unsaved-changes marker (`*`)."""
        self._dirty = dirty
        self._refresh()

    def set_notice(self, notice: str | None) -> None:
        """Set or clear the persistent warning segment shown after the font name."""
        self._notice = notice
        self._refresh()

    def _refresh(self) -> None:
        """Re-render the composite status message into the footer."""
        name = self._font_name or "—"
        marker = " *" if self._dirty else ""
        segment = f"   ⚠ {self._notice}" if self._notice else ""
        self.showMessage(f"Font: {name}{marker}{segment}", 0)
