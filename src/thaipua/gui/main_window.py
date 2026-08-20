"""Top-level window wiring the three-column layout to `AppState`/`FontService`.

`MainWindow` is the single mutator of `AppState`: every pane's signal lands here,
mutates state, and re-renders whichever other pane cares.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fontTools.ttLib import TTLibError
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QFont, QFontDatabase, QPainterPath
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QSplitter, QVBoxLayout, QWidget

from thaipua.core.constants import DEFAULT_PROFILES_DIR
from thaipua.core.creation_engine import StringTableError
from thaipua.core.file_codec import decode_files, encode_files
from thaipua.core.fonttools.settings import SUB_ABOVE_VOWEL, SUB_BELOW_VOWEL, SUB_CONSONANT, SUB_TONE_MARK
from thaipua.core.fonttools.specs import CompositeSpec
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
    inference_supported_consonants,
    present_roles_for,
    pua_specs_for_consonant,
)
from thaipua.gui.theme import ThemeMode
from thaipua.gui.widgets.dialogs import FindSubstitutionDialog, SettingsDialog
from thaipua.gui.widgets.left_pane import CellVisual, GlyphGridPane
from thaipua.gui.widgets.middle_pane import GlyphPreviewPane
from thaipua.gui.widgets.right_pane import ControlsPane
from thaipua.gui.widgets.status_footer import StatusBar
from thaipua.gui.widgets.top_toolbar import TopToolbar

if TYPE_CHECKING:
    from thaipua.core.fonttools.alternates import GlyphSubstitution
logger = logging.getLogger(__name__)
FONT_FILTER = "Font files (*.ttf *.otf);;All files (*.*)"
TEXT_FILTER = "Text / string-table files (*.txt *.strings *.dlstrings *.ilstrings);;All files (*.*)"


class MainWindow(QMainWindow):
    """The main window: top toolbar, three-column splitter, status bar."""

    def __init__(self) -> None:
        """Build the window with empty state; load the first Consonant page."""
        super().__init__()
        self.setWindowTitle("ThaiPUA")
        self.resize(1520, 855)
        self._state = AppState()
        self._service = FontService()
        self._pua_index: dict[int, CompositeSpec] = {}
        self._qfont: QFont | None = None
        self._current_category: MarkCategory | None = None
        self._sub_catalog: dict[str, list[GlyphSubstitution]] = {}
        self._settings_generation = 0
        self._installed_generations: dict[int, int] = {}
        self._grid_refresh_timer = QTimer(self)
        self._grid_refresh_timer.setSingleShot(True)
        self._grid_refresh_timer.setInterval(300)
        self._grid_refresh_timer.timeout.connect(self._refresh_left_pane)
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
        toolbar.decode_pua_requested.connect(self._on_decode_pua)
        toolbar.encode_thai_requested.connect(self._on_encode_thai)
        toolbar.find_substitution_requested.connect(self._on_find_substitution)
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
        self._state.pua_map = self._service.ensure_pua_map()
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
        self._qfont = self._qfont_from_path(path)
        self._grid_pane.set_loaded_font(self._qfont)
        self._grid_pane.set_font_loaded(True)
        self._toolbar.set_font_loaded(True)
        self._refresh_left_pane()
        self._refresh_footer()
        self._preview_pane.clear()
        self._preview_pane.set_metadata(None, None)
        self._controls_pane.set_enabled(False)
        self._controls_pane.clear_consonant_settings()

    def _on_save_font(self) -> None:
        """Pick a destination and write the rebuilt font through `FontService`."""
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

    def _on_decode_pua(self) -> None:
        """Pick text/string-table files and decode their PUA codepoints to Thai."""
        if not self._service.is_loaded:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Decode PUA -> Thai", "", TEXT_FILTER)
        if not paths:
            return
        try:
            decode_files(self._service.pua_map_path, [Path(p) for p in paths])
        except (OSError, StringTableError) as exc:
            logger.exception("PUA decode failed")
            QMessageBox.critical(self, "Decode PUA -> Thai", f"Decode failed:\n{exc}")
            return None
        QMessageBox.information(self, "Decode PUA -> Thai", f"Decoded {len(paths)} file(s).")

    def _on_encode_thai(self) -> None:
        """Pick text/string-table files and encode their Thai text to PUA codepoints."""
        if not self._service.is_loaded:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Encode Thai -> PUA", "", TEXT_FILTER)
        if not paths:
            return
        try:
            encode_files(self._service.pua_map_path, [Path(p) for p in paths])
        except (OSError, StringTableError) as exc:
            logger.exception("PUA encode failed")
            QMessageBox.critical(self, "Encode Thai -> PUA", f"Encode failed:\n{exc}")
            return None
        QMessageBox.information(self, "Encode Thai -> PUA", f"Encoded {len(paths)} file(s).")

    def _on_find_substitution(self) -> None:
        """Open the GSUB catalog dialog populated from the live font."""
        if not self._service.is_loaded:
            return
        dialog = FindSubstitutionDialog(self._service.find_substitutions(), self)
        dialog.exec()

    def _on_settings(self) -> None:
        """Open the preferences dialog with live Light/Dark/System theme switching.

        The dialog applies each radio change immediately via `_on_theme_changed`
        (stylesheet swap, persistence, and a pane/icon refresh).
        """
        SettingsDialog(self, current_mode=theme.current_theme_mode(), on_theme_changed=self._on_theme_changed).exec()

    def _on_theme_changed(self, mode: ThemeMode) -> None:
        """Apply `mode` live, persist it, and re-theme the custom-painted surfaces.

        qdarktheme's stylesheet re-skins every standard Qt widget across the app as soon
        as `apply_theme` sets the merged stylesheet. The custom-painted surfaces — grid-
        cell stylesheets, the glyph canvas, and the toolbar/pager icons — are not
        reached by the global stylesheet, so they are refreshed explicitly by
        `_refresh_theme_surfaces`.
        """
        theme.apply_theme(mode=mode)
        theme.save_theme_mode(mode)
        self._refresh_theme_surfaces()

    def _refresh_theme_surfaces(self) -> None:
        """Re-render every custom-painted surface for the newly-active palette.

        Drops the cached icon engines and re-`setIcon`s the toolbar/pager buttons, re-
        renders the grid cells (their per-cell stylesheets embed palette colors), and
        repaints the glyph preview canvas. `paintEvent`/`_refresh_style` read
        `theme.get_palette()` at draw time, so a fresh render picks up the switched
        palette even though qdarktheme's global stylesheet cannot reach these widgets.
        """
        icons.clear_cache()
        self._toolbar.refresh_icons()
        self._grid_pane.refresh_icons()
        self._controls_pane.refresh_icons()
        self._refresh_left_pane()
        self._preview_pane.refresh()

    def _on_consonant_clicked(self, cons_uni: int) -> None:
        """Transition the grid into the PUA page for `cons_uni`; no-op without a loaded font."""
        if not self._service.is_loaded:
            return
        self._state.active_consonant_uni = cons_uni
        self._state.pua_page = 0
        self._state.active_pua_code = None
        self._refresh_left_pane()
        self._render_codepoint(cons_uni)
        self._controls_pane.load_consonant_settings(cons_uni, self._state.settings, self._sub_catalog)
        self._controls_pane.set_enabled(False)

    def _on_pua_clicked(self, pua_code: int) -> None:
        """Mark `pua_code` selected; load preview + controls."""
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
        self._refresh_left_pane()
        self._preview_pane.clear()
        self._preview_pane.set_metadata(None, None)
        self._controls_pane.set_enabled(False)
        self._controls_pane.clear_consonant_settings()

    def _on_prev_page(self) -> None:
        """Decrement the current grid page; clamps to the first page."""
        if self._state.active_consonant_uni is None:
            self._state.consonants_page -= 1
        else:
            self._state.pua_page -= 1
        self._refresh_left_pane()

    def _on_next_page(self) -> None:
        """Increment the current grid page; clamps via `_refresh_left_pane`."""
        if self._state.active_consonant_uni is None:
            self._state.consonants_page += 1
        else:
            self._state.pua_page += 1
        self._refresh_left_pane()

    def _on_offset_changed(self, x: int, y: int) -> None:
        """Live-commit an offset change for the active glyph under the radio role.

        Mutates `state.settings` immediately and recomposes the preview, marking the
        document dirty for save.
        """
        spec = self._active_spec()
        if spec is None or self._current_category is None:
            return None
        self._settings_generation += 1
        apply_offset(spec, self._state.settings, x, y, category=self._current_category)
        self._render_pua_spec(spec, mark_dirty=True)
        self._schedule_grid_refresh()

    def _on_base_offset_changed(self, role: str, x: int, y: int) -> None:
        """Live-commit a per-consonant base-offset delta and re-render the glyph.

        Base Offsets lives in its own `base_offsets` tier, fully independent of per-
        glyph Mark Offset (`mark_offsets`/`combo_offsets`). The active PUA spec (if any)
        is recomposed so the preview reflects the new baseline.
        """
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
        """Live-commit a contextual glyph substitution and re-render the glyph.

        An empty `glyph_name` clears the matching rule (whose `conditions` equals the
        active context's canonicalised mark-role set), leaving other rules for the same
        codepoint untouched. Per-role dispatch: consonant uses `active_consonant_uni` as
        both `codepoint` and `cons_uni`, with `present_roles` from the PUA spec (or
        empty when only the consonant page is active); mark roles use the spec's mark
        codepoint, `spec.cons_uni`, and the spec's present roles (requiring a selected
        PUA glyph).         `conditions` is canonicalised per codepoint category
        (`context_canonicaliser`): a tone-mark codepoint merges the below-vowel family
        with the tone-only family; an ascender-protruding consonant (e.g. ฬ) merges every
        above-stack context (`above_vowel` and/or `tone_mark`, with or without a below
        vowel) into one family — so a consonant substitution defined on an `above_vowel`
        cluster also applies to its tone clusters. Every other consonant and vowel
        codepoint uses the generic tone-within-vowel-family canonicalisation, which
        keeps a below-vowel rule from firing in no-below-vowel clusters.
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
        """Live-commit a per-consonant snap pair and re-render the glyph.

        A disabled snap is cleared from the settings (the composer treats an absent snap
        and an explicitly disabled snap identically); an enabled snap records its gap
        and recomposes the active PUA spec (if any).
        """
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
        """Reload X/Y inputs for the newly-selected radio category's role.

        Reads via `current_mark_offset` so the sliders show only the per-glyph
        `mark_offsets`/`combo_offsets` override — never the per-consonant Base Offset —
        keeping Mark Offset and Base Offsets fully independent surfaces.
        """
        spec = self._active_spec()
        if spec is None or not isinstance(category, MarkCategory):
            return None
        self._current_category = category
        offset = current_mark_offset(spec, self._state.settings, category=category)
        self._controls_pane.load_offset(offset.x, offset.y, category)
        spec_active = self._state.active_pua_code is not None
        self._controls_pane.set_enabled(spec_active, categories_for(spec))

    def _render_codepoint(self, codepoint: int) -> None:
        """Render a base cmap codepoint (no offset edits) into the preview."""
        if not self._service.is_loaded:
            self._preview_pane.clear()
            self._preview_pane.set_metadata(codepoint, None)
            return
        path = QPainterPath()
        render = self._service.render_glyph(codepoint, path)
        self._preview_pane.set_metadata(codepoint, render.glyph_name)
        self._preview_pane.set_render(render, path)

    def _render_pua_spec(self, spec: CompositeSpec, *, mark_dirty: bool = False) -> None:
        """Regenerate `spec` under current settings and paint its preview.

        `mark_dirty=True` flips `state.dirty` (slider drag); `False` for selection-only
        re-renders.
        """
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
        """Paint `spec`'s already-installed composite without rebuilding it.

        A PUA glyph whose composite is already present in the live font — installed by
        an earlier click or edit — is drawn directly. Eviction and recreation are only
        needed when the settings changed, so a pure selection must not pay that cost on
        every click.
        """
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
        """Rebuild the `pua_code -> CompositeSpec` index from `state.pua_map`."""
        index: dict[int, CompositeSpec] = {}
        for _cons_uni, specs in group_composites_by_consonant(self._state.pua_map).items():
            for spec in specs:
                index[spec.pua_code] = spec
        self._pua_index = index

    def _refresh_left_pane(self) -> None:
        """Re-render the left pane per the current view-state and pagination."""
        if self._state.active_consonant_uni is None:
            self._show_consonants_page()
        else:
            self._show_pua_page()

    def _schedule_grid_refresh(self) -> None:
        """Debounce a left-pane re-render after a settings mutation.

        The PUA grid is not live: its cell paths are recomputed once the settings have
        settled, so fast slider drags only re-render the viewport (which rebuilds the
        single active composite per tick) while the grid catches up 300 ms after the
        last change.
        """
        self._grid_refresh_timer.start()

    def _show_consonants_page(self) -> None:
        """Render the current consonant-index page (clamped pagination)."""
        cons = inference_supported_consonants()
        total_pages = max(1, (len(cons) + GRID_PAGE_SIZE - 1) // GRID_PAGE_SIZE)
        self._state.consonants_page = max(0, min(self._state.consonants_page, total_pages - 1))
        page = self._state.consonants_page
        start = page * GRID_PAGE_SIZE
        slice_items = cons[start : start + GRID_PAGE_SIZE]
        visuals = [CellVisual(key=cp, display_text=chr(cp), subtitle=f"U+{cp:04X}") for cp in slice_items]
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
        visuals = []
        for spec in slice_specs:
            path: QPainterPath | None = None
            if self._service.is_loaded:
                cell_path = QPainterPath()
                if self._service.render_composite_path(spec, self._state.settings, cell_path) is not None:
                    path = cell_path
            visuals.append(
                CellVisual(key=spec.pua_code, display_text=spec.thai_key, subtitle=f"U+{spec.pua_code:04X}", path=path)
            )
        self._grid_pane.show_pua(visuals, consonant_label=chr(cons_uni), page_index=page, total_pages=total_pages)
        if self._state.active_pua_code is not None:
            self._grid_pane.set_selected(self._state.active_pua_code)

    def _refresh_footer(self) -> None:
        self._status_bar.set_font(self._state.font_path)
        self._status_bar.set_dirty(self._state.dirty)

    def _qfont_from_path(self, path: str) -> QFont | None:
        """Register the font with `QFontDatabase` and return its first family as a `QFont`."""
        family_id = QFontDatabase.addApplicationFont(path)
        if family_id == -1:
            return None
        families = QFontDatabase.applicationFontFamilies(family_id)
        if not families:
            return None
        return QFont(families[0])

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
