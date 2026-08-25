"""PySide6 application entry point."""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from thaipua.core.bootstrap import ensure_app_data_dirs
from thaipua.core.logging import setup_logging
from thaipua.core.paths import ASSETS_DIR
from thaipua.gui.main_window import MainWindow
from thaipua.gui.widgets.anchored_tooltip import install_anchored_tooltips

logger = logging.getLogger(__name__)

_LOGO_PATH: Path = ASSETS_DIR / "images" / "logo.png"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the application: prepare data directories, then open the main window."""
    ensure_app_data_dirs()
    setup_logging()
    logger.info("Starting thaipua")
    app = QApplication(list(argv) if argv is not None else sys.argv)
    _set_window_icon(app)
    install_anchored_tooltips(app)
    window = MainWindow()
    window.show()
    return int(app.exec())


def _set_window_icon(app: QApplication) -> None:
    if not _LOGO_PATH.is_file():
        logger.warning("Logo not found at %s; skipping window icon", _LOGO_PATH)
    else:
        app.setWindowIcon(QIcon(str(_LOGO_PATH)))


if __name__ == "__main__":
    raise SystemExit(main())
