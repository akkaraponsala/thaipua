"""Light/dark/system theming with persisted mode selection."""

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PySide6.QtWidgets import QApplication

import qdarktheme
from thaipua.core.paths import DEFAULT_CONFIG_PATH

logger = logging.getLogger(__name__)


class ThemeMode(Enum):
    """Selectable theme modes; values match the qdarktheme theme names."""

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "auto"


DEFAULT_THEME_MODE: ThemeMode = ThemeMode.DARK


@dataclass(frozen=True, slots=True)
class Palette:
    """Color tokens consumed by custom-painted surfaces for one theme."""

    BG_APP: str
    BG_PANE: str
    BG_PANE_HEADER: str
    BG_GRID_CELL: str
    BG_GRID_CELL_HOVER: str
    BG_GRID_CELL_SELECTED: str
    BG_GRID_CELL_EMPTY: str
    BG_TOOLTIP: str
    TEXT_PRIMARY: str
    TEXT_SECONDARY: str
    TEXT_DIM: str
    ACCENT: str
    ACCENT_HOVER: str
    BORDER: str
    BORDER_FOCUS: str
    ICON_FG: str
    GLYPH_FILL: str
    GLYPH_PEN: str
    ERROR: str
    WARNING: str


DARK_PALETTE: Palette = Palette(
    BG_APP="#202124",
    BG_PANE="#202124",
    BG_PANE_HEADER="#2A2B2E",
    BG_GRID_CELL="#2A2B2E",
    BG_GRID_CELL_HOVER="#3F4042",
    BG_GRID_CELL_SELECTED="#0A4A7A",
    BG_GRID_CELL_EMPTY="#1B1B1D",
    BG_TOOLTIP="#2B2D31",
    TEXT_PRIMARY="#E4E7EB",
    TEXT_SECONDARY="#9AA0A6",
    TEXT_DIM="#80868B",
    ACCENT="#8AB4F7",
    ACCENT_HOVER="#A1C4FA",
    BORDER="#3F4042",
    BORDER_FOCUS="#8AB4F7",
    ICON_FG="#E1E5E9",
    GLYPH_FILL="#FFFFFF",
    GLYPH_PEN="#F0F0F0",
    ERROR="#BE3C3C",
    WARNING="#D8A028",
)
LIGHT_PALETTE: Palette = Palette(
    BG_APP="#F8F9FA",
    BG_PANE="#F8F9FA",
    BG_PANE_HEADER="#E8EAED",
    BG_GRID_CELL="#FFFFFF",
    BG_GRID_CELL_HOVER="#E8EAED",
    BG_GRID_CELL_SELECTED="#D0E4FC",
    BG_GRID_CELL_EMPTY="#F1F3F4",
    BG_TOOLTIP="#FFFFFF",
    TEXT_PRIMARY="#4D5157",
    TEXT_SECONDARY="#5F6368",
    TEXT_DIM="#9AA0A6",
    ACCENT="#1A73E8",
    ACCENT_HOVER="#1765CC",
    BORDER="#DADCE0",
    BORDER_FOCUS="#1A73E8",
    ICON_FG="#494D53",
    GLYPH_FILL="#202124",
    GLYPH_PEN="#3F4042",
    ERROR="#C5221F",
    WARNING="#B06000",
)
_active_palette: Palette = DARK_PALETTE
_active_mode: ThemeMode = DEFAULT_THEME_MODE


def get_palette() -> Palette:
    """Return the active theme palette consumed by custom-painted widgets."""
    return _active_palette


def current_theme_mode() -> ThemeMode:
    """Return the user-selected theme mode, which may be `SYSTEM`."""
    return _active_mode


def resolved_theme_mode(mode: ThemeMode = DEFAULT_THEME_MODE) -> ThemeMode:
    """Resolve `mode` to the concrete light/dark mode driving the stylesheet."""
    if mode is not ThemeMode.SYSTEM:
        return mode
    return resolve_system_theme()


def resolve_system_theme(default: ThemeMode = DEFAULT_THEME_MODE) -> ThemeMode:
    """Resolve the host OS theme to a concrete mode, defaulting when detection fails."""
    try:
        import darkdetect
    except Exception:
        logger.debug("darkdetect unavailable; system theme defaults to %s", default.value)
        return default
    detected = darkdetect.theme()
    if detected is None:
        logger.info("System theme not detected; defaulting to %s", default.value)
        return default
    if detected.lower() == "light":
        return ThemeMode.LIGHT
    return ThemeMode.DARK


def _palette_for(mode: ThemeMode) -> Palette:
    """Return the palette for a concrete `mode` (`LIGHT`/`DARK`).

    `SYSTEM` raises `ValueError` because the palette is only defined for a resolved
    mode.
    """
    if mode is ThemeMode.DARK:
        return DARK_PALETTE
    if mode is ThemeMode.LIGHT:
        return LIGHT_PALETTE
    raise ValueError(f"_palette_for needs a concrete mode, got {mode!r}")


def _local_overrides(palette: Palette) -> str:
    """Build the app-scoped QSS block for object-name-tagged widgets.

    App-scoped overrides qdarktheme does not know about: the object-name-tagged labels
    installed by the panes, the `QFrame#Divider` separator widget, and the
    `CollapsibleSection` header/body card. Every unscoped standard Qt widget stays on
    qdarktheme's defaults.
    """
    return f"""
QLabel#PaneHeader {{
    color: {palette.TEXT_PRIMARY};
    font-weight: bold;
    font-size: 12pt;
    padding: 6px 10px;
}}
QLabel#Breadcrumb {{ color: {palette.TEXT_SECONDARY}; }}
QLabel#Label {{ color: {palette.TEXT_SECONDARY}; }}
QLabel#MetaValue {{ color: {palette.TEXT_PRIMARY}; font-family: "Consolas", monospace; }}

QFrame#Divider {{ background-color: {palette.BORDER}; }}

QToolButton#SectionToggle {{
    background-color: transparent;
    border: none;
    color: {palette.TEXT_PRIMARY};
    font-weight: bold;
    text-align: left;
    padding: 0px;
}}
QToolButton#SectionToggle:hover {{ color: {palette.ACCENT}; }}
QLabel#SectionSummary {{ color: {palette.TEXT_SECONDARY}; }}
"""


def apply_theme(app: QApplication | None = None, mode: ThemeMode = DEFAULT_THEME_MODE) -> ThemeMode:
    """Install the stylesheet and palette for `mode`; return the resolved concrete mode.

    `SYSTEM` resolves one-shot at call time.
    """
    global _active_palette
    global _active_mode
    instance = app if app is not None else QApplication.instance()
    if instance is None:
        raise RuntimeError("apply_theme() needs a running QApplication; construct one before calling it.")
    if not isinstance(instance, QApplication):
        raise RuntimeError(
            "apply_theme() needs a QApplication, not a plain QCoreApplication; "
            "construct a QApplication before calling it."
        )
    effective = resolved_theme_mode(mode)
    palette = _palette_for(effective)
    _active_palette = palette
    _active_mode = mode
    instance.setStyleSheet(qdarktheme.load_stylesheet(effective.value) + _local_overrides(palette))  # type: ignore[attr-defined]
    return effective


def _theme_mode_from_value(value: str) -> ThemeMode:
    """Return the `ThemeMode` whose `.value` equals `value`, else the default."""
    for mode in ThemeMode:
        if mode.value == value:
            return mode
    logger.info("Unknown theme value %r; defaulting to %s", value, DEFAULT_THEME_MODE.value)
    return DEFAULT_THEME_MODE


def load_theme_mode(path: str | Path | None = None) -> ThemeMode:
    """Load the persisted theme mode from `config.json`, defaulting on any failure."""
    config_path = Path(path) if path is not None else Path(DEFAULT_CONFIG_PATH)
    if not config_path.is_file():
        return DEFAULT_THEME_MODE
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        logger.warning("Could not read config at %s; using %s", config_path, DEFAULT_THEME_MODE.value)
        return DEFAULT_THEME_MODE
    if not isinstance(raw, dict):
        logger.warning("Config at %s is not a JSON object; using %s", config_path, DEFAULT_THEME_MODE.value)
        return DEFAULT_THEME_MODE
    theme_value = raw.get("theme")
    if not isinstance(theme_value, str):
        return DEFAULT_THEME_MODE
    return _theme_mode_from_value(theme_value)


def save_theme_mode(mode: ThemeMode, path: str | Path | None = None) -> None:
    """Persist `mode` to `config.json`, preserving sibling keys."""
    config_path = Path(path) if path is not None else Path(DEFAULT_CONFIG_PATH)
    data = {}
    if config_path.is_file():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                data = existing
        except OSError, json.JSONDecodeError:
            logger.warning("Could not read existing config at %s; rewriting", config_path)
    data["theme"] = mode.value
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
