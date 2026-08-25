"""Footer status bar showing a persistent warning notice."""

from __future__ import annotations

from PySide6.QtWidgets import QStatusBar, QWidget


class StatusBar(QStatusBar):
    """Footer status bar showing a persistent warning notice."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the footer with no notice."""
        super().__init__(parent)
        self._notice: str | None = None

    def set_notice(self, notice: str | None) -> None:
        """Set or clear the persistent warning segment."""
        self._notice = notice
        self.showMessage(f"   ⚠ {self._notice}" if self._notice else "", 0)
