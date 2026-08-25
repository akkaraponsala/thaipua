"""Main window coordinating panes, state mutations, and backend calls."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fontTools.ttLib import TTLibError
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QPainterPath
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from thaipua.core.file_codec import decode_files, encode_files
from thaipua.core.fonttools.map_validation import IssueSeverity, PuaMapIssue
from thaipua.core.fonttools.ownership import SlotOwnership
from thaipua.core.fonttools.settings import (
    SUB_ABOVE_VOWEL,
    SUB_BELOW_VOWEL,
    SUB_CONSONANT,
    SUB_TONE_MARK,
    PlacementSettings,
    default_placement_settings,
)
from thaipua.core.fonttools.specs import CompositeSpec
from thaipua.core.layout import LayoutConflict
from thaipua.core.paths import DEFAULT_PROFILES_DIR
from thaipua.core.string_table import StringTableError
from thaipua.gui import icons, theme
from thaipua.gui.font_service import FontService
from thaipua.gui.state import (
    GRID_PAGE_SIZE,
    AppState,
    MarkCategory,
    apply_base_offset,
    apply_glyph_substitution,
    apply_offset,
    apply_snap,
    categories_for,
    current_mark_offset,
    group_composites_by_consonant,
    infer_category,
    inferable_consonants,
    present_roles_for,
    pua_specs_for_consonant,
)
from thaipua.gui.theme import ThemeMode
from thaipua.gui.widgets.controls_pane import ControlsPane
from thaipua.gui.widgets.dialogs import FindSubstitutionDialog, SettingsDialog
from thaipua.gui.widgets.glyph_grid_pane import CellVisual, GlyphGridPane
from thaipua.gui.widgets.occupancy_dialog import OccupancyDialog, OccupancyRow
from thaipua.gui.widgets.preview_pane import GlyphPreviewPane
from thaipua.gui.widgets.pua_mapping_dialog import PuaMappingDialog
from thaipua.gui.widgets.status_footer import StatusBar
from thaipua.gui.widgets.top_toolbar import TopToolbar

if TYPE_CHECKING:
    from thaipua.core.fonttools.alternates import GlyphSubstitution

logger = logging.getLogger(__name__)

FONT_FILTER = "Font files (*.ttf *.otf);;All files (*.*)"
PROFILE_FILTER = "Profile JSON (*.json);;All files (*.*)"
TEXT_FILTER = "Text / string-table files (*.txt *.strings *.dlstrings *.ilstrings);;All files (*.*)"
_SAVE_BLOCK_PREVIEW_LIMIT = 8
"""Maximum mapping issues listed in the save-blocked dialog before an ellipsis line."""


def _compress_runs(codepoints: list[int]) -> list[tuple[int, int]]:
    """Collapse sorted codepoints into inclusive (start, end) ranges for compact display."""
    if not codepoints:
        return []
    runs: list[tuple[int, int]] = [(codepoints[0], codepoints[0])]
    for codepoint in codepoints[1:]:
        start, end = runs[-1]
        if codepoint == end + 1:
            runs[-1] = (start, codepoint)
        else:
            runs.append((codepoint, codepoint))
    return runs


class MainWindow(QMainWindow):
    """Main window: top toolbar, three-column splitter, and status bar."""

    def __init__(self) -> None:
        """Build the window with empty state; load the first Consonant page."""
        super().__init__()
        self.setWindowTitle("ThaiPUA")
        self.resize(1520, 855)
        self._state = AppState()
        self._service = FontService()
        self._pua_index: dict[int, CompositeSpec] = {}
        self._current_category: MarkCategory | None = None
        self._sub_catalog: dict[str, list[GlyphSubstitution]] = {}
        self._settings_generation = 0
        self._installed_generations: dict[int, int] = {}
        self._occupancy_dialog: OccupancyDialog | None = None
        self._conflicts_cache: tuple[int, list[LayoutConflict]] | None = None
        self._last_occupancy_notice: str | None = None
        self._grid_refresh_timer = QTimer(self)
        self._grid_refresh_timer.setSingleShot(True)
        self._grid_refresh_timer.setInterval(300)
        self._grid_refresh_timer.timeout.connect(self._refresh_grid_pane)
        self._build_layout()
        self._connect_signals()
        theme.apply_theme(mode=theme.load_theme_mode())
        self._refresh_theme_surfaces()
        self._refresh_footer()

    def _build_layout(self) -> None:
        """Assemble toolbar, three-column splitter, and footer into the main window."""
        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._toolbar = TopToolbar(central)
        outer.addWidget(self._toolbar)
        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self._grid_pane = GlyphGridPane(splitter)
        self._preview_pane = GlyphPreviewPane(splitter)
        self._controls_pane = ControlsPane(splitter)
        splitter.addWidget(self._grid_pane)
        splitter.addWidget(self._preview_pane)
        splitter.addWidget(self._controls_pane)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([320, 620, 320])
        outer.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self._status_bar = StatusBar(self)
        self.setStatusBar(self._status_bar)

    def _connect_signals(self) -> None:
        """Wire each pane's signals to the corresponding `_on_*` slot."""
        toolbar = self._toolbar
        toolbar.open_font_requested.connect(self._on_open_font)
        toolbar.save_font_requested.connect(self._on_save_font)
        toolbar.profile_load_requested.connect(self._on_load_profile)
        toolbar.profile_save_requested.connect(self._on_save_profile)
        toolbar.decode_pua_requested.connect(self._on_decode_pua)
        toolbar.encode_thai_requested.connect(self._on_encode_thai)
        toolbar.find_substitution_requested.connect(self._on_find_substitution)
        toolbar.edit_mapping_requested.connect(self._on_edit_mapping)
        toolbar.pua_slots_requested.connect(self._on_pua_slots)
        toolbar.settings_requested.connect(self._on_settings)
        grid = self._grid_pane
        grid.consonant_clicked.connect(self._on_consonant_clicked)
        grid.pua_clicked.connect(self._on_pua_clicked)
        grid.back_requested.connect(self._on_back_to_consonants)
        grid.prev_page_requested.connect(self._on_prev_page)
        grid.next_page_requested.connect(self._on_next_page)
        controls = self._controls_pane
        controls.offset_changed.connect(self._on_offset_changed)
        controls.base_offset_changed.connect(self._on_base_offset_changed)
        controls.glyph_substitution_changed.connect(self._on_glyph_substitution_changed)
        controls.snap_changed.connect(self._on_snap_changed)
        controls.category_changed.connect(self._on_category_changed)
        controls.reset_defaults_requested.connect(self._on_reset_defaults)

    def _on_open_font(self) -> None:
        """Open a font via a native dialog; load it through `FontService`."""
        path, _ = QFileDialog.getOpenFileName(self, "Open Font", "", FONT_FILTER)
        if not path:
            return
        try:
            self._service.load_font(path, profiles_dir=DEFAULT_PROFILES_DIR)
        except (TTLibError, OSError) as exc:
            logger.exception("Failed to open font %s", path)
            QMessageBox.critical(self, "Open Font", f"Could not open font:\n{exc}")
            return
        self._state.font_path = path
        self._state.pua_map = self._service.load_layout()
        self._sub_catalog = self._service.find_substitutions()
        self._rebuild_pua_index()
        self._settings_generation = 0
        self._installed_generations = {}
        generator = self._service.generator
        if generator is not None:
            self._state.settings = generator.settings
        self._state.active_consonant_uni = None
        self._state.active_pua_code = None
        self._state.consonants_page = 0
        self._state.pua_page = 0
        self._state.dirty = False
        self._grid_pane.set_font_loaded(True)
        self._toolbar.set_font_loaded(True)
        self._controls_pane.set_font_loaded(True)
        self._refresh_grid_pane()
        self._refresh_footer()
        self._preview_pane.clear()
        self._preview_pane.set_metadata(None, None)
        self._controls_pane.set_enabled(False)
        self._controls_pane.clear_consonant_settings()

    def _on_save_font(self) -> None:
        """Pick a destination and write the rebuilt font through `FontService`."""
        errors = [
            issue
            for issue in self._service.validation_issues(self._state.pua_map)
            if issue.severity is IssueSeverity.ERROR
        ]
        if errors:
            self._report_mapping_errors(errors)
            return
        default = self._service.output_path or "thaipua.ttf"
        path, _ = QFileDialog.getSaveFileName(self, "Save Font", default, FONT_FILTER)
        if not path:
            return
        try:
            self._service.save_font(path, self._state.settings, self._state.pua_map)
        except (TTLibError, OSError) as exc:
            logger.exception("Failed to save font to %s", path)
            QMessageBox.critical(self, "Save Font", f"Could not save font:\n{exc}")
            return None
        self._installed_generations = {pua: self._settings_generation for pua in self._pua_index}
        self._state.dirty = False
        self._refresh_footer()
        QMessageBox.information(self, "Save Font", f"Saved:\n{path}")

    def _on_load_profile(self) -> None:
        """Pick a profile JSON file and replace the live placement settings with it."""
        if not self._service.is_loaded:
            return
        start = str(self._service.default_profile_path() or DEFAULT_PROFILES_DIR)
        path, _ = QFileDialog.getOpenFileName(self, "Load Profile", start, PROFILE_FILTER)
        if not path:
            return
        self._replace_placement_settings(self._service.load_profile(path))

    def _on_save_profile(self) -> None:
        """Pick a destination and write the current placement settings as profile JSON."""
        if not self._service.is_loaded:
            return
        default = str(self._service.default_profile_path() or "profile.json")
        path, _ = QFileDialog.getSaveFileName(self, "Save Profile", default, PROFILE_FILTER)
        if not path:
            return
        try:
            target = self._service.save_profile(path, self._state.settings)
        except OSError as exc:
            logger.exception("Failed to save profile to %s", path)
            QMessageBox.critical(self, "Save Profile", f"Could not save profile:\n{exc}")
            return
        QMessageBox.information(self, "Save Profile", f"Saved:\n{target}")

    def _on_reset_defaults(self) -> None:
        """Reset the live placement settings to in-code defaults after confirmation."""
        if not self._service.is_loaded:
            return
        reply = QMessageBox.question(
            self,
            "Reset Placement Defaults",
            "Replace all placement settings with defaults? Unsaved profile edits are lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._replace_placement_settings(default_placement_settings())

    def _replace_placement_settings(self, settings: PlacementSettings) -> None:
        """Swap in `settings`, invalidate installed composites, and refresh every dependent view."""
        self._state.settings = settings
        self._settings_generation += 1
        self._installed_generations = {}
        self._state.dirty = True
        self._refresh_footer()
        self._schedule_grid_refresh()
        pua_code = self._state.active_pua_code
        if pua_code is not None:
            self._on_pua_clicked(pua_code)
        elif self._state.active_consonant_uni is not None:
            self._controls_pane.load_consonant_settings(
                self._state.active_consonant_uni, self._state.settings, self._sub_catalog
            )

    def _report_mapping_errors(self, errors: list[PuaMapIssue]) -> None:
        """Show the mapping errors blocking the save, previewing at most `_SAVE_BLOCK_PREVIEW_LIMIT`."""
        lines = [f"{issue.thai_key}: {issue.message}" for issue in errors[:_SAVE_BLOCK_PREVIEW_LIMIT]]
        hidden = len(errors) - len(lines)
        if hidden > 0:
            lines.append(f"… and {hidden} more")
        QMessageBox.critical(
            self,
            "Save Font",
            f"Save blocked: {len(errors)} PUA mapping error(s). "
            "Fix them in PUA Mapping, or review occupied slots under PUA Slots & Overrides.\n\n" + "\n".join(lines),
        )

    def _on_decode_pua(self) -> None:
        """Pick text/string-table files and decode their PUA codepoints to Thai."""
        if not self._service.is_loaded:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Decode PUA → Thai", "", TEXT_FILTER)
        if not paths:
            return
        try:
            decode_files(self._service.pua_map_path, [Path(p) for p in paths])
        except (OSError, StringTableError) as exc:
            logger.exception("PUA decode failed")
            QMessageBox.critical(self, "Decode PUA → Thai", f"Decode failed:\n{exc}")
            return None
        QMessageBox.information(self, "Decode PUA → Thai", f"Decoded {len(paths)} file(s).")

    def _on_encode_thai(self) -> None:
        """Pick text/string-table files and encode their Thai text to PUA codepoints."""
        if not self._service.is_loaded:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Encode Thai → PUA", "", TEXT_FILTER)
        if not paths:
            return
        try:
            encode_files(self._service.pua_map_path, [Path(p) for p in paths])
        except (OSError, StringTableError) as exc:
            logger.exception("PUA encode failed")
            QMessageBox.critical(self, "Encode Thai → PUA", f"Encode failed:\n{exc}")
            return None
        QMessageBox.information(self, "Encode Thai → PUA", f"Encoded {len(paths)} file(s).")

    def _on_find_substitution(self) -> None:
        """Open the GSUB catalog dialog populated from the live font."""
        if not self._service.is_loaded:
            return
        dialog = FindSubstitutionDialog(self._service.find_substitutions(), self)
        dialog.exec()
        dialog.deleteLater()

    def _on_edit_mapping(self, initial_query: str | None = None) -> None:
        """Edit the PUA mapping, applying accepted results to state and disk."""
        if not self._service.is_loaded:
            return
        self._open_mapping_dialog(initial_query)

    def _open_mapping_dialog(self, initial_query: str | None = None) -> None:
        """Run the mapping editor, optionally pre-filtered; persist an accepted result."""
        dialog = PuaMappingDialog(
            dict(self._state.pua_map),
            self._service.pua_slot_context(),
            self,
            allowed_locked=self._service.allowed_locked(),
            initial_query=initial_query,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return
        new_map = dialog.result_mapping()
        dialog.deleteLater()
        if new_map == self._state.pua_map:
            return
        self._state.pua_map = self._service.apply_manual_edits(new_map)
        self._rebuild_pua_index()
        self._state.dirty = True
        self._refresh_footer()
        self._schedule_grid_refresh()

    def _on_pua_slots(self) -> None:
        """Open the foreign-slot report; its actions route through `FontService` mutations."""
        if not self._service.is_loaded:
            return
        self._occupancy_dialog = OccupancyDialog(self._build_occupancy_rows(), self)
        self._occupancy_dialog.override_toggled.connect(self._on_override_toggled)
        self._occupancy_dialog.relocate_requested.connect(self._on_relocate_requested)
        self._occupancy_dialog.remap_requested.connect(self._on_remap_requested)
        self._occupancy_dialog.bulk_override_requested.connect(self._on_bulk_override)
        self._occupancy_dialog.bulk_relocate_requested.connect(self._on_bulk_relocate)
        self._occupancy_dialog.bulk_remap_requested.connect(self._on_bulk_remap)
        self._occupancy_dialog.exec()
        # Parented dialogs outlive their Python reference — destroy explicitly to avoid per-open accumulation.
        self._occupancy_dialog.deleteLater()
        self._occupancy_dialog = None

    def _build_occupancy_rows(self) -> list[OccupancyRow]:
        """Snapshot foreign slots with thumbnails and mapping context for the report."""
        rows = []
        mapped_codes = {ord(char) for char in self._state.pua_map.values()}
        allowed = self._service.allowed_locked()
        for occupant in self._service.pua_occupants():
            if occupant.ownership is SlotOwnership.OWNED:
                continue
            path = QPainterPath()
            self._service.render_glyph(occupant.codepoint, path)
            rows.append(
                OccupancyRow(
                    occupant=occupant,
                    path=None if path.isEmpty() else path,
                    mapped=occupant.codepoint in mapped_codes,
                    overridden=occupant.codepoint in allowed,
                )
            )
        return rows

    def _on_override_toggled(self, codepoint: int, approve: bool) -> None:
        """Persist an override decision and refresh every surface that reflects it."""
        if approve:
            self._service.override_slot(codepoint)
        else:
            self._service.clear_override(codepoint)
        logger.info("User %s the override for U+%04X", "approved" if approve else "revoked", codepoint)
        self._refresh_after_resolutions(layout_changed=False)

    def _on_remap_requested(self, codepoint: int) -> None:
        """Open the mapping editor pre-filtered to the key occupying `codepoint`."""
        self._open_mapping_dialog(initial_query=f"{codepoint:04X}")
        if self._occupancy_dialog is not None:
            self._occupancy_dialog.refresh(self._build_occupancy_rows())

    def _current_conflicts(self) -> list[LayoutConflict]:
        """Return layout-vs-font conflicts, rescanning only after a service mutation."""
        version = self._service.state_version
        if self._conflicts_cache is None or self._conflicts_cache[0] != version:
            self._conflicts_cache = (version, self._service.layout_conflicts())
        return self._conflicts_cache[1]

    def _update_occupancy_notice(self) -> None:
        """Summarize unresolved layout-vs-font conflicts into the footer notice.

        Foreign glyphs on unmapped slots ride along harmlessly; only mapped slots
        still sitting on foreign content raise the ⚠ segment. The warning logs
        once per change of the conflict set, not on every footer refresh.
        """
        conflicts = self._current_conflicts()
        if not conflicts:
            if self._last_occupancy_notice is not None:
                logger.info("All mapped slots are conflict-free")
            self._last_occupancy_notice = None
            self._status_bar.set_notice(None)
            return
        runs = _compress_runs(sorted(c.codepoint for c in conflicts))
        label = ", ".join(f"U+{start:04X}-U+{end:04X}" if end > start else f"U+{start:04X}" for start, end in runs)
        notice = f"{len(conflicts)} mapped slot(s) conflict: {label}"
        if notice != self._last_occupancy_notice:
            logger.warning(
                "%d mapped slot(s) still hold foreign content: %s",
                len(conflicts),
                "; ".join(f"U+{c.codepoint:04X}={c.occupant.glyph_name} ({c.occupant.detail})" for c in conflicts[:10]),
            )
            self._last_occupancy_notice = notice
        self._status_bar.set_notice(notice)

    def _key_for_codepoint(self, codepoint: int) -> str | None:
        """Return the Thai key currently mapped onto `codepoint`, or `None`."""
        for thai_key, pua_char in self._state.pua_map.items():
            if len(pua_char) == 1 and ord(pua_char) == codepoint:
                return thai_key
        return None

    def _refresh_after_resolutions(self, *, layout_changed: bool) -> None:
        """Propagate override/relocate resolutions into state and every dependent view."""
        if layout_changed:
            self._state.pua_map = self._service.pua_map
            self._rebuild_pua_index()
        self._state.dirty = True
        self._refresh_footer()
        self._schedule_grid_refresh()
        if self._occupancy_dialog is not None:
            self._occupancy_dialog.refresh(self._build_occupancy_rows())

    def _on_relocate_requested(self, codepoint: int) -> None:
        """Move the key mapped onto `codepoint` into the tail zone and refresh."""
        thai_key = self._key_for_codepoint(codepoint)
        if thai_key is None:
            logger.warning("Cannot relocate U+%04X: no mapped key", codepoint)
            return
        if self._service.relocate_key(thai_key) is None:
            return
        self._refresh_after_resolutions(layout_changed=True)

    def _on_bulk_override(self) -> None:
        """Approve overrides for every mapped locked slot still holding foreign content."""
        allowed = self._service.allowed_locked()
        mapped_codes = {ord(char) for char in self._state.pua_map.values() if len(char) == 1}
        targets = [
            o.codepoint
            for o in self._service.pua_occupants()
            if o.codepoint in mapped_codes and o.ownership is SlotOwnership.LOCKED and o.codepoint not in allowed
        ]
        if not targets or not self._service.override_slots(targets):
            return
        self._refresh_after_resolutions(layout_changed=False)

    def _on_bulk_relocate(self) -> None:
        """Relocate every Thai key whose slot still conflicts with the font."""
        keys = [c.thai_key for c in self._current_conflicts()]
        if not keys or not self._service.relocate_keys(keys):
            return
        self._refresh_after_resolutions(layout_changed=True)

    def _on_bulk_remap(self) -> None:
        """Open the mapping editor pre-filtered to every slot still conflicting."""
        conflicts = self._current_conflicts()
        if self._occupancy_dialog is not None:
            self._occupancy_dialog.reject()
        self._open_mapping_dialog(initial_query=" ".join(f"{c.codepoint:04X}" for c in conflicts) or None)

    def _on_base_changed(self, base: int) -> None:
        """Rebase the canonical layout, refresh every view, then surface any new conflicts."""
        self._state.pua_map = self._service.set_base_codepoint(base)
        self._rebuild_pua_index()
        self._state.dirty = True
        self._refresh_footer()
        self._schedule_grid_refresh()

    def _on_settings(self) -> None:
        """Open the preferences dialog with live theme and layout-base switching."""
        dialog = SettingsDialog(
            self,
            current_mode=theme.current_theme_mode(),
            on_theme_changed=self._on_theme_changed,
            base_codepoint=self._service.layout_base(),
            base_tail_start=self._service.layout_tail_start(),
            on_base_changed=self._on_base_changed,
        )
        dialog.exec()
        dialog.deleteLater()

    def _on_theme_changed(self, mode: ThemeMode) -> None:
        """Apply and persist `mode`, then refresh custom-painted surfaces."""
        theme.apply_theme(mode=mode)
        theme.save_theme_mode(mode)
        self._refresh_theme_surfaces()

    def _refresh_theme_surfaces(self) -> None:
        """Re-render custom-painted surfaces for the newly active palette."""
        icons.clear_cache()
        self._toolbar.refresh_icons()
        self._grid_pane.refresh_icons()
        self._controls_pane.refresh_icons()
        self._refresh_grid_pane()
        self._preview_pane.refresh()

    def _on_consonant_clicked(self, cons_uni: int) -> None:
        """Transition the grid into the PUA page for `cons_uni`; no-op without a loaded font."""
        if not self._service.is_loaded:
            return
        self._state.active_consonant_uni = cons_uni
        self._state.pua_page = 0
        self._state.active_pua_code = None
        self._refresh_grid_pane()
        self._render_codepoint(cons_uni)
        self._controls_pane.load_consonant_settings(cons_uni, self._state.settings, self._sub_catalog)
        self._controls_pane.set_enabled(False)

    def _on_pua_clicked(self, pua_code: int) -> None:
        """Mark `pua_code` selected and load its preview and controls."""
        self._state.active_pua_code = pua_code
        spec = self._pua_index.get(pua_code)
        if spec is None:
            return
        if (
            self._service.has_codepoint(pua_code)
            and self._installed_generations.get(pua_code) == self._settings_generation
        ):
            self._render_installed_spec(spec)
        else:
            self._render_pua_spec(spec)
        self._grid_pane.set_selected(pua_code)
        category = infer_category(spec)
        if category is None:
            self._controls_pane.set_enabled(False)
            return
        self._current_category = category
        offset = current_mark_offset(spec, self._state.settings, category=category)
        self._controls_pane.set_enabled(True, categories_for(spec))
        self._controls_pane.load_offset(offset.x, offset.y, category)
        self._controls_pane.load_spec_mark_substitutions(spec, self._state.settings, self._sub_catalog)
        self._controls_pane.load_consonant_sub_for_spec(spec, self._state.settings, self._sub_catalog, spec.cons_uni)

    def _on_back_to_consonants(self) -> None:
        """Reset to the consonant index page."""
        self._state.active_consonant_uni = None
        self._state.active_pua_code = None
        self._state.pua_page = 0
        self._refresh_grid_pane()
        self._preview_pane.clear()
        self._preview_pane.set_metadata(None, None)
        self._controls_pane.set_enabled(False)
        self._controls_pane.clear_consonant_settings()

    def _on_prev_page(self) -> None:
        """Decrement the current grid page; `_refresh_grid_pane` clamps to the first page."""
        if self._state.active_consonant_uni is None:
            self._state.consonants_page -= 1
        else:
            self._state.pua_page -= 1
        self._refresh_grid_pane()

    def _on_next_page(self) -> None:
        """Increment the current grid page; `_refresh_grid_pane` clamps to the last page."""
        if self._state.active_consonant_uni is None:
            self._state.consonants_page += 1
        else:
            self._state.pua_page += 1
        self._refresh_grid_pane()

    def _on_offset_changed(self, x: int, y: int) -> None:
        """Commit a live mark-offset edit and refresh the previews."""
        spec = self._active_spec()
        if spec is None or self._current_category is None:
            return None
        self._settings_generation += 1
        apply_offset(spec, self._state.settings, x, y, category=self._current_category)
        self._render_pua_spec(spec, mark_dirty=True)
        self._schedule_grid_refresh()

    def _on_base_offset_changed(self, role: str, x: int, y: int) -> None:
        """Commit a base-offset edit for `role` and refresh the previews."""
        cons_uni = self._state.active_consonant_uni
        if cons_uni is None:
            return
        self._settings_generation += 1
        apply_base_offset(cons_uni, role, x, y, self._state.settings)
        self._state.dirty = True
        self._refresh_footer()
        spec = self._active_spec()
        if spec is not None:
            self._render_pua_spec(spec)
        self._schedule_grid_refresh()

    def _on_glyph_substitution_changed(self, role: str, glyph_name: str) -> None:
        """Commit a substitution override for the active role and context, then refresh the previews.

        An empty `glyph_name` clears the matching rule.
        """
        spec = self._active_spec()
        codepoint: int | None
        if role == SUB_CONSONANT:
            cons_uni_or_none = self._state.active_consonant_uni
            if cons_uni_or_none is None:
                return
            cons_uni = cons_uni_or_none
            codepoint = cons_uni
            present_roles = present_roles_for(spec) if spec is not None else frozenset()
        else:
            if spec is None:
                return
            cons_uni = spec.cons_uni
            present_roles = present_roles_for(spec)
            if role == SUB_TONE_MARK:
                codepoint = spec.tone_uni
            elif role == SUB_ABOVE_VOWEL:
                codepoint = spec.above_uni
            elif role == SUB_BELOW_VOWEL:
                codepoint = spec.below_uni
            else:
                return None
        if codepoint is None:
            return
        self._settings_generation += 1
        apply_glyph_substitution(
            codepoint, cons_uni, glyph_name or None, self._state.settings, conditions=present_roles
        )
        self._state.dirty = True
        self._refresh_footer()
        spec_after = self._active_spec()
        if spec_after is not None:
            self._render_pua_spec(spec_after)
        self._schedule_grid_refresh()

    def _on_snap_changed(self, snap_name: str, enabled: bool, gap: int) -> None:
        """Commit a snap toggle or gap change and refresh the previews."""
        cons_uni = self._state.active_consonant_uni
        if cons_uni is None:
            return
        self._settings_generation += 1
        apply_snap(cons_uni, snap_name, enabled, gap, self._state.settings)
        self._state.dirty = True
        self._refresh_footer()
        spec = self._active_spec()
        if spec is not None:
            self._render_pua_spec(spec)
        self._schedule_grid_refresh()

    def _on_category_changed(self, category: object) -> None:
        """Reload the X/Y inputs for the newly selected category's role."""
        spec = self._active_spec()
        if spec is None or not isinstance(category, MarkCategory):
            return None
        self._current_category = category
        offset = current_mark_offset(spec, self._state.settings, category=category)
        self._controls_pane.load_offset(offset.x, offset.y, category)
        spec_active = self._state.active_pua_code is not None
        self._controls_pane.set_enabled(spec_active, categories_for(spec))

    def _render_codepoint(self, codepoint: int) -> None:
        """Render a base `cmap` codepoint (no offset edits) into the preview."""
        if not self._service.is_loaded:
            self._preview_pane.clear()
            self._preview_pane.set_metadata(codepoint, None)
            return
        path = QPainterPath()
        render = self._service.render_glyph(codepoint, path)
        self._preview_pane.set_metadata(codepoint, render.glyph_name)
        self._preview_pane.set_render(render, path)

    def _render_pua_spec(self, spec: CompositeSpec, *, mark_dirty: bool = False) -> None:
        """Regenerate `spec` under current settings and paint its preview."""
        if not self._service.is_loaded:
            self._preview_pane.clear()
            self._preview_pane.set_metadata(spec.pua_code, None)
            return
        path = QPainterPath()
        render = self._service.regenerate_composite(spec, self._state.settings, path)
        self._installed_generations[spec.pua_code] = self._settings_generation
        self._preview_pane.set_metadata(spec.pua_code, render.glyph_name)
        self._preview_pane.set_render(render, path)
        if mark_dirty:
            self._state.dirty = True
            self._refresh_footer()

    def _render_installed_spec(self, spec: CompositeSpec) -> None:
        """Paint an already-installed composite without rebuilding it."""
        if not self._service.is_loaded:
            self._preview_pane.clear()
            self._preview_pane.set_metadata(spec.pua_code, None)
            return
        path = QPainterPath()
        render = self._service.render_glyph(spec.pua_code, path, spec=spec)
        self._preview_pane.set_metadata(spec.pua_code, render.glyph_name)
        self._preview_pane.set_render(render, path)

    def _active_spec(self) -> CompositeSpec | None:
        """Return the spec for the currently selected PUA codepoint, or `None`."""
        pua_code = self._state.active_pua_code
        if pua_code is None:
            return None
        return self._pua_index.get(pua_code)

    def _rebuild_pua_index(self) -> None:
        """Rebuild the `pua_code → CompositeSpec` index from `state.pua_map`."""
        index: dict[int, CompositeSpec] = {}
        for _cons_uni, specs in group_composites_by_consonant(self._state.pua_map).items():
            for spec in specs:
                index[spec.pua_code] = spec
        self._pua_index = index

    def _refresh_grid_pane(self) -> None:
        """Re-render the grid pane per the current view-state and pagination."""
        if self._state.active_consonant_uni is None:
            self._show_consonants_page()
        else:
            self._show_pua_page()

    def _schedule_grid_refresh(self) -> None:
        """Queue a debounced grid refresh after a settings mutation."""
        self._grid_refresh_timer.start()

    def _show_consonants_page(self) -> None:
        """Render the current consonant-index page (clamped pagination)."""
        cons = inferable_consonants()
        total_pages = max(1, (len(cons) + GRID_PAGE_SIZE - 1) // GRID_PAGE_SIZE)
        self._state.consonants_page = max(0, min(self._state.consonants_page, total_pages - 1))
        page = self._state.consonants_page
        start = page * GRID_PAGE_SIZE
        slice_items = cons[start : start + GRID_PAGE_SIZE]
        ref_ascent, ref_descent = self._service.display_extents() if self._service.is_loaded else (0.0, 0.0)
        groups = group_composites_by_consonant(self._state.pua_map)
        visuals = []
        for cp in slice_items:
            path: QPainterPath | None = None
            if self._service.is_loaded:
                cell_path = QPainterPath()
                self._service.render_glyph(cp, cell_path)
                if not cell_path.isEmpty():
                    path = cell_path
            range_label = self._pua_range_label(groups.get(cp, []))
            visuals.append(
                CellVisual(
                    key=cp,
                    display_text=chr(cp),
                    subtitle=f"U+{cp:04X}",
                    path=path,
                    ref_ascent=ref_ascent,
                    ref_descent=ref_descent,
                    tooltip=f"PUA block: {range_label}" if range_label else "",
                )
            )
        self._grid_pane.show_consonants(visuals, page_index=page, total_pages=total_pages)

    def _show_pua_page(self) -> None:
        """Render the current PUA-variant page (clamped pagination) for the cursor."""
        cons_uni = self._state.active_consonant_uni
        if cons_uni is None:
            return
        specs = pua_specs_for_consonant(self._state.pua_map, cons_uni)
        total_pages = max(1, (len(specs) + GRID_PAGE_SIZE - 1) // GRID_PAGE_SIZE)
        self._state.pua_page = max(0, min(self._state.pua_page, total_pages - 1))
        page = self._state.pua_page
        start = page * GRID_PAGE_SIZE
        slice_specs = specs[start : start + GRID_PAGE_SIZE]
        ref_ascent, ref_descent = self._service.display_extents() if self._service.is_loaded else (0.0, 0.0)
        visuals = []
        for spec in slice_specs:
            path: QPainterPath | None = None
            if self._service.is_loaded:
                cell_path = QPainterPath()
                if self._service.render_composite_path(spec, self._state.settings, cell_path) is not None:
                    path = cell_path
            visuals.append(
                CellVisual(
                    key=spec.pua_code,
                    display_text=spec.thai_key,
                    subtitle=f"U+{spec.pua_code:04X}",
                    path=path,
                    ref_ascent=ref_ascent,
                    ref_descent=ref_descent,
                )
            )
        self._grid_pane.show_pua(
            visuals,
            consonant_label=chr(cons_uni),
            range_label=self._pua_range_label(specs),
            page_index=page,
            total_pages=total_pages,
        )
        if self._state.active_pua_code is not None:
            self._grid_pane.set_selected(self._state.active_pua_code)

    def _pua_range_label(self, specs: list[CompositeSpec]) -> str | None:
        """Return the consonant's PUA block label, or `None` when the map holds no slot for it.

        Contiguous blocks render as a `U+lo-U+hi` span; relocated (scattered) slots
        fall back to a slot count anchored at the lowest codepoint.
        """
        if not specs:
            return None
        codes = sorted(spec.pua_code for spec in specs)
        lo, hi = codes[0], codes[-1]
        if hi - lo + 1 == len(codes):
            return f"U+{lo:04X}-U+{hi:04X}"
        return f"U+{lo:04X}+{len(codes)} slot(s)"

    def _refresh_footer(self) -> None:
        """Re-render the title bar and footer: font path with dirty marker, and occupancy notice."""
        font_path = self._state.font_path
        marker = "*" if self._state.dirty else ""
        self.setWindowTitle(f"{marker}{font_path} — ThaiPUA" if font_path else "ThaiPUA")
        self._update_occupancy_notice()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Prompt to save unsaved edits before closing; allow cancel via the prompt."""
        if not self._state.dirty:
            super().closeEvent(event)
            return
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "There are unsaved changes. Discard and exit?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            event.ignore()
        else:
            super().closeEvent(event)
