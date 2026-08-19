"""Light/Dark/System theme integration via PyQtDarkTheme.

qdarktheme supplies a Material palette for its three theme names — `dark`, `light`, and
`auto` (the resolved OS theme); `apply_theme` installs the merged stylesheet plus the
matching `Palette`, resolving `SYSTEM` via `darkdetect` so both agree on a concrete
`light`/`dark` token. Custom-painted surfaces the global stylesheet cannot reach (grid
cells, the glyph canvas, the tinted toolbar/pane icons) read `get_palette()` so they stay
consistent after every swap.

App-scoped object-name-tagged widgets (`#PaneHeader`, `#MetaValue`, `QFrame#Divider`)
get `_local_overrides` on top of qdarktheme's defaults. The user-selected `ThemeMode` is
persisted to `settings.json` by `load_theme_mode()` / `save_theme_mode()`, round-tripping
the `theme` key while preserving sibling keys.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import qdarktheme
from PySide6.QtWidgets import QApplication

from thaipua.core.constants import DEFAULT_SETTINGS_PATH

logger = logging.getLogger(__name__)


class ThemeMode(Enum):
    """The three selectable theme modes offered by the Settings dialog.

    The enum value is the string qdarktheme accepts as its `theme` argument (`dark`,
    `light`, `auto`), so `apply_theme` can forward a resolved mode straight to
    `qdarktheme.load_stylesheet`.
    """

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "auto"


DEFAULT_THEME_MODE: ThemeMode = ThemeMode.DARK


@dataclass(frozen=True, slots=True)
class Palette:
    """The color tokens consumed by custom-painted surfaces for one theme.

    Mirrors qdarktheme's Material tokens for each theme so grid cells, the glyph canvas,
    and toolbar icons read identically to the global stylesheet. `ICON_FG` is the icon
    stroke tint for ordinary button surfaces; `GLYPH_FILL`/`GLYPH_PEN` are the preview
    glyph body/outline colors.
    """

    BG_APP: str
    BG_PANE: str
    BG_PANE_HEADER: str
    BG_GRID_CELL: str
    BG_GRID_CELL_HOVER: str
    BG_GRID_CELL_SELECTED: str
    BG_GRID_CELL_EMPTY: str
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


DARK_PALETTE: Palette = Palette(
    BG_APP="#202124",
    BG_PANE="#202124",
    BG_PANE_HEADER="#2A2B2E",
    BG_GRID_CELL="#2A2B2E",
    BG_GRID_CELL_HOVER="#3F4042",
    BG_GRID_CELL_SELECTED="#0A4A7A",
    BG_GRID_CELL_EMPTY="#1B1B1D",
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
)
LIGHT_PALETTE: Palette = Palette(
    BG_APP="#F8F9FA",
    BG_PANE="#F8F9FA",
    BG_PANE_HEADER="#E8EAED",
    BG_GRID_CELL="#FFFFFF",
    BG_GRID_CELL_HOVER="#E8EAED",
    BG_GRID_CELL_SELECTED="#D0E4FC",
    BG_GRID_CELL_EMPTY="#F1F3F4",
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
)
_active_palette: Palette = DARK_PALETTE
_active_mode: ThemeMode = DEFAULT_THEME_MODE


def get_palette() -> Palette:
    """Return the active theme palette consumed by custom-painted widgets."""
    return _active_palette


def current_theme_mode() -> ThemeMode:
    """Return the user-selected theme mode (`LIGHT`, `DARK`, or `SYSTEM`).

    This is the mode the Settings dialog radio group should reflect; it may be `SYSTEM`
    even though the *effective* palette is `DARK`/`LIGHT`. Use `resolved_theme_mode()`
    for the concrete theme driving the stylesheet.
    """
    return _active_mode


def resolved_theme_mode(mode: ThemeMode = DEFAULT_THEME_MODE) -> ThemeMode:
    """Return the concrete `LIGHT`/`DARK` mode that `mode` resolves to.

    `SYSTEM` is resolved via `darkdetect` (falling back to `DEFAULT_THEME_MODE` when
    detection fails); `LIGHT`/`DARK` pass through unchanged.
    """
    if mode is not ThemeMode.SYSTEM:
        return mode
    return resolve_system_theme()


def resolve_system_theme(default: ThemeMode = DEFAULT_THEME_MODE) -> ThemeMode:
    """Resolve the host OS theme to a concrete `LIGHT`/`DARK` mode.

    Mirrors `qdarktheme`'s internal probe (`darkdetect.theme()` returns `"Dark"`/
    `"Light"`/`None`) so the custom palette and qdarktheme's stylesheet agree on a
    single concrete token. A failed or unavailable probe yields `default` so the UI
    never breaks in a headless or undetectable environment.
    """
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
    installed by the panes and the `QFrame#Divider` separator widget. Every unscoped
    standard Qt widget stays on qdarktheme's defaults.
    """
    return f"""
QLabel#PaneHeader {{
    color: {palette.TEXT_PRIMARY};
    font-weight: bold;
    font-size: 12pt;
    padding: 8px 10px;
}}
QLabel#Breadcrumb {{ color: {palette.TEXT_SECONDARY}; padding: 4px 8px; }}
QLabel#Label {{ color: {palette.TEXT_SECONDARY}; }}
QLabel#MetaValue {{ color: {palette.TEXT_PRIMARY}; font-family: "Consolas", monospace; }}

QFrame#Divider {{ background-color: {palette.BORDER}; }}
"""


def apply_theme(app: QApplication | None = None, mode: ThemeMode = DEFAULT_THEME_MODE) -> ThemeMode:
    """Install qdarktheme's stylesheet plus local overrides for `mode`.

    Resolves `SYSTEM` to the host OS theme (via `darkdetect`) so the active palette and
    the qdarktheme stylesheet always share a concrete `dark`/`light` token, switches
    `_active_palette`/`_active_mode`, and sets the merged stylesheet on the
    `QApplication`. `app=None` defaults to `QApplication.instance()` and raises
    `RuntimeError` when none exists. `SYSTEM` resolves one-shot at call time; call again
    to update if the OS theme changes later. Returns the concrete `LIGHT`/`DARK` mode.
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
    instance.setStyleSheet(qdarktheme.load_stylesheet(effective.value) + _local_overrides(palette))
    return effective


def _theme_mode_from_value(value: str) -> ThemeMode:
    """Return the `ThemeMode` whose `.value` equals `value`, else the default."""
    for mode in ThemeMode:
        if mode.value == value:
            return mode
    logger.info("Unknown theme value %r; defaulting to %s", value, DEFAULT_THEME_MODE.value)
    return DEFAULT_THEME_MODE


def load_theme_mode(path: str | Path | None = None) -> ThemeMode:
    """Load the persisted theme mode from `settings.json`.

    A missing or unreadable file, a non-dict JSON payload, or an unrecognized `theme`
    value all fall back to `DEFAULT_THEME_MODE` so a corrupt or absent preferences file
    never blocks startup. `path=None` defaults to `DEFAULT_SETTINGS_PATH` under the per-
    user app-data directory.
    """
    settings_path = Path(path) if path is not None else Path(DEFAULT_SETTINGS_PATH)
    if not settings_path.is_file():
        return DEFAULT_THEME_MODE
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read settings at %s; using %s", settings_path, DEFAULT_THEME_MODE.value)
        return DEFAULT_THEME_MODE
    if not isinstance(raw, dict):
        logger.warning("Settings at %s is not a JSON object; using %s", settings_path, DEFAULT_THEME_MODE.value)
        return DEFAULT_THEME_MODE
    theme_value = raw.get("theme")
    if not isinstance(theme_value, str):
        return DEFAULT_THEME_MODE
    return _theme_mode_from_value(theme_value)


def save_theme_mode(mode: ThemeMode, path: str | Path | None = None) -> None:
    """Persist `mode` to `settings.json` under the `theme` key.

    Preserves any sibling keys already in the file by reading the current contents first
    and merging. `path=None` defaults to `DEFAULT_SETTINGS_PATH` under the per-user app-
    data directory.
    """
    settings_path = Path(path) if path is not None else Path(DEFAULT_SETTINGS_PATH)
    data = {}
    if settings_path.is_file():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                data = existing
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read existing settings at %s; rewriting", settings_path)
    data["theme"] = mode.value
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


__all__ = [
    "DARK_PALETTE",
    "DEFAULT_THEME_MODE",
    "LIGHT_PALETTE",
    "Palette",
    "ThemeMode",
    "apply_theme",
    "current_theme_mode",
    "get_palette",
    "load_theme_mode",
    "resolve_system_theme",
    "resolved_theme_mode",
    "save_theme_mode",
]
