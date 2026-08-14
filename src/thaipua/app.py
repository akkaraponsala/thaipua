"""PySide6 desktop application entry point.

`app.main` is the application's sole PySide6-importing entry point; the rest of the
package (`thaipua.core`, `thaipua.gui.state`, `thaipua.gui.font_service`,
`thaipua.gui.glyph_pen`) is GUI-free and stays unit-testable without a `QApplication`.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from thaipua.core.constants import ASSETS_DIR, ensure_app_data_dirs
from thaipua.gui.main_window import MainWindow

_LOGO_PATH: Path = ASSETS_DIR / "images" / "logo.png"


def main(argv: Sequence[str] | None = None) -> int:
    """Create the `QApplication`, show the `MainWindow`, and run the event loop.

    Materializes the runtime-data directory before the GUI opens so a writable home for
    `settings.json`, `pua_mapping.json`, and `profiles/` exists on first run.
    """
    ensure_app_data_dirs()
    app = QApplication(list(argv) if argv is not None else sys.argv)
    _set_window_icon(app)
    window = MainWindow()
    window.show()
    return int(app.exec())


def _set_window_icon(app: QApplication) -> None:
    if not _LOGO_PATH.is_file():
        print(f"[APP] Logo not found at {_LOGO_PATH}; skipping window icon", file=sys.stderr)
    else:
        app.setWindowIcon(QIcon(str(_LOGO_PATH)))


if __name__ == "__main__":
    raise SystemExit(main())
