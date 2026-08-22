"""PySide6 desktop application entry point.

`app.main` is the application's sole PySide6-importing entry point; the rest of the
package (`thaipua.core`, `thaipua.gui.state`, `thaipua.gui.font_service`,
`thaipua.gui.glyph_pen`) is GUI-free and stays unit-testable without a `QApplication`.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from thaipua.core.constants import ASSETS_DIR, ensure_app_data_dirs
from thaipua.core.logging import setup_logging
from thaipua.gui.main_window import MainWindow

logger = logging.getLogger(__name__)

_LOGO_PATH: Path = ASSETS_DIR / "images" / "logo.png"


def main(argv: Sequence[str] | None = None) -> int:
    """Create the `QApplication`, show the `MainWindow`, and run the event loop.

    Materializes the runtime-data directory before the GUI opens so a writable home for
    `settings.json`, `pua_mapping.json`, `profiles/`, and the log file exists on first run.
    """
    ensure_app_data_dirs()
    setup_logging()
    logger.info("Starting thaipua")
    app = QApplication(list(argv) if argv is not None else sys.argv)
    _set_window_icon(app)
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
