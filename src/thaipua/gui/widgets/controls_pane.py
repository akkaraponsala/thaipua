"""Right pane exposing global/per-glyph mark offsets, base offsets, glyph substitutions, and snap configs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from thaipua.core.fonttools.settings import (
    BASE_OFFSET_ROLES,
    GLYPH_SUBSTITUTION_ROLES,
    ROLE_ABOVE_VOWEL,
    ROLE_BELOW_VOWEL,
    ROLE_TO_MARK_CATEGORY,
    ROLE_TONE_MARK,
    ROLE_TONE_MARK_ON_ABOVE_VOWEL,
    ROLES,
    SNAPS,
    SUB_ABOVE_VOWEL,
    SUB_BELOW_VOWEL,
    SUB_CONSONANT,
    SUB_TONE_MARK,
    Offset,
    PlacementSettings,
)
from thaipua.gui import icons
from thaipua.gui.icons import IconName
from thaipua.gui.state import (
    MARK_CATEGORY_LABELS,
    SNAP_LABELS,
    MarkCategory,
    current_base_offset,
    current_global_mark_offset,
    current_glyph_substitution,
    current_snap,
    glyph_substitution_candidates,
    present_roles_for,
)
from thaipua.gui.widgets.collapsible_section import CollapsibleSection

if TYPE_CHECKING:
    from thaipua.core.fonttools.alternates import GlyphSubstitution
    from thaipua.core.fonttools.specs import CompositeSpec

OFFSET_MIN = -1000
OFFSET_MAX = 1000
OFFSET_DEFAULT = 0
SNAP_GAP_MIN = -1000
SNAP_GAP_MAX = 1000
SNAP_GAP_DEFAULT = 0
NO_OVERRIDE = "(no override)"
GLOBAL_MARK_PLACEHOLDER = "(select mark)"
_CATEGORY_ITER: tuple[MarkCategory, ...] = (MarkCategory.TONE_MARK, MarkCategory.ABOVE_VOWEL, MarkCategory.BELOW_VOWEL)
_SUB_ROLE_LABELS: dict[str, str] = {
    SUB_CONSONANT: "Consonant",
    SUB_TONE_MARK: "Tone Mark",
    SUB_ABOVE_VOWEL: "Above Vowel",
    SUB_BELOW_VOWEL: "Below Vowel",
}
_DEFAULT_ROLE_LABELS: dict[str, str] = {
    ROLE_TONE_MARK: "Tone Mark",
    ROLE_TONE_MARK_ON_ABOVE_VOWEL: "Tone on Vowel",
    ROLE_ABOVE_VOWEL: "Above Vowel",
    ROLE_BELOW_VOWEL: "Below Vowel",
}


class ControlsPane(QWidget):
    """Editable controls bound to the active glyph and consonant."""

    offset_changed = Signal(int, int)
    base_offset_changed = Signal(str, int, int)
    global_mark_offset_changed = Signal(str, int, int, int)
    glyph_substitution_changed = Signal(str, str)
    snap_changed = Signal(str, bool, int)
    category_changed = Signal(object)
    reset_defaults_requested = Signal()
    _sub_combos: dict[str, QComboBox]
    _snap_checks: dict[str, QCheckBox]
    _snap_gaps: dict[str, QSpinBox]
    _base_offset_spins: dict[str, tuple[QSpinBox, QSpinBox]]
    _global_mark_combos: dict[str, QComboBox]
    _global_mark_spins: dict[str, tuple[QSpinBox, QSpinBox]]
    _radios: dict[MarkCategory, QRadioButton]
    _radio_group: QButtonGroup
    _axis_icons: list[tuple[IconName, QLabel]]
    _mark_section: CollapsibleSection
    _global_section: CollapsibleSection
    _base_section: CollapsibleSection
    _sub_section: CollapsibleSection
    _snap_section: CollapsibleSection

    def __init__(self, parent: QWidget | None = None) -> None:
        """Lay out the *Controls* pane; controls start disabled until loaded."""
        super().__init__(parent)
        self._axis_icons = []
        self._x_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._y_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._x_spin = QSpinBox(self)
        self._y_spin = QSpinBox(self)
        for slider in [self._x_slider, self._y_slider]:
            slider.setRange(OFFSET_MIN, OFFSET_MAX)
            slider.setValue(OFFSET_DEFAULT)
        for spin in [self._x_spin, self._y_spin]:
            spin.setRange(OFFSET_MIN, OFFSET_MAX)
            spin.setValue(OFFSET_DEFAULT)
            spin.setMinimumWidth(80)
        self._sub_combos = {}
        self._snap_checks = {}
        self._snap_gaps = {}
        self._base_offset_spins = {}
        self._global_mark_combos = {}
        self._global_mark_spins = {}
        self._font_loaded = False
        self._settings: PlacementSettings | None = None
        self._consonant_active = False
        self._enabled = False
        self._enabled_categories = set(_CATEGORY_ITER)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header_row())
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget(scroll)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(4, 4, 4, 4)
        container_layout.setSpacing(4)
        container_layout.addWidget(self._build_mark_offsets_section())
        container_layout.addWidget(self._build_base_offsets_section())
        container_layout.addWidget(self._build_glyph_substitutions_section())
        container_layout.addWidget(self._build_snap_configs_section())
        container_layout.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(16)
        self._commit_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._commit_timer.timeout.connect(self._emit_offset_commit)
        self._offset_pending = False
        self._x_slider.valueChanged.connect(lambda v: self._mirror(self._x_spin, v))
        self._x_spin.valueChanged.connect(lambda v: self._mirror(self._x_slider, v))
        self._y_slider.valueChanged.connect(lambda v: self._mirror(self._y_spin, v))
        self._y_spin.valueChanged.connect(lambda v: self._mirror(self._y_slider, v))
        self.set_enabled(False)
        self.set_consonant_enabled(False)
        self.set_font_loaded(False)

    def _build_header_row(self) -> QWidget:
        """Build the pane header with the Reset Defaults action pinned top-right."""
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(0)
        title = QLabel("Controls", self)
        title.setObjectName("PaneHeader")
        self._reset_btn = QPushButton(self)
        self._reset_btn.setIcon(icons.icon("rotate-ccw"))
        self._reset_btn.setIconSize(QSize(16, 16))
        self._reset_btn.setFixedSize(26, 26)
        self._reset_btn.setFlat(True)
        self._reset_btn.setToolTip("Reset Placement Defaults")
        self._reset_btn.clicked.connect(self.reset_defaults_requested)
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(self._reset_btn)
        return row

    def _build_mark_offsets_section(self) -> CollapsibleSection:
        """Build the *Mark Offsets* collapsible, nesting the global table inside."""
        section = CollapsibleSection("Mark Offsets", self)
        content = QWidget(section)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(self._build_axis_row("axis-x", self._x_slider, self._x_spin))
        layout.addLayout(self._build_axis_row("axis-y", self._y_slider, self._y_spin))
        layout.addWidget(self._build_category_radios())
        layout.addWidget(self._build_global_mark_section())
        section.set_content(content)
        section.set_expanded(True)
        self._mark_section = section
        return section

    def _build_axis_row(self, icon_name: IconName, slider: QSlider, spin: QSpinBox) -> QHBoxLayout:
        """Build a single *[AxisIcon | Slider | SpinBox]* axis row from existing widgets."""
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._axis_icon_label(icon_name))
        row.addWidget(slider, 1)
        row.addWidget(spin)
        return row

    def _axis_icon_label(self, icon_name: IconName) -> QLabel:
        """Build a 16x16 tinted axis icon label, tracked for theme refreshes."""
        label = QLabel(self)
        label.setObjectName("Label")
        label.setFixedSize(16, 16)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(icons.icon(icon_name).pixmap(QSize(16, 16)))
        self._axis_icons.append((icon_name, label))
        return label

    def _mirror(self, other: QSlider | QSpinBox, value: int) -> None:
        """Mirror `value` into `other` without re-triggering handlers, throttling commits."""
        was_blocked = other.blockSignals(True)
        other.setValue(value)
        other.blockSignals(was_blocked)
        self._offset_pending = True
        if not self._commit_timer.isActive():
            self._commit_timer.start()

    def _emit_offset_commit(self) -> None:
        """Emit the current `(x, y)` offset pair after the throttle window."""
        if not self._offset_pending:
            return
        self._offset_pending = False
        self.offset_changed.emit(self._x_spin.value(), self._y_spin.value())

    def _build_category_radios(self) -> QWidget:
        """Build the four spec-grouped radio buttons as a `QButtonGroup`."""
        holder = QWidget(self)
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        self._radio_group = QButtonGroup(self)
        self._radios: dict[MarkCategory, QRadioButton] = {}
        for category in _CATEGORY_ITER:
            rb = QRadioButton(MARK_CATEGORY_LABELS[category], self)
            self._radios[category] = rb
            self._radio_group.addButton(rb)
            v.addWidget(rb)
            rb.toggled.connect(lambda checked, c=category: self._on_radio_toggled(c, checked))
        return holder

    def _on_radio_toggled(self, category: MarkCategory, checked: bool) -> None:
        """Forward radio state changes when a new category becomes active."""
        if checked:
            self.category_changed.emit(category)

    def _build_global_mark_section(self) -> CollapsibleSection:
        """Build the collapsible global-mark table nested in the Mark Offsets group."""
        section = CollapsibleSection("Global (all consonants)", self)
        content = QWidget(section)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for role in ROLES:
            role_label = QLabel(_DEFAULT_ROLE_LABELS[role], self)
            role_label.setMinimumWidth(90)
            combo = QComboBox(self)
            combo.addItem(GLOBAL_MARK_PLACEHOLDER, None)
            for cp in sorted(ROLE_TO_MARK_CATEGORY[role]):
                combo.addItem(f"{chr(cp)}  U+{cp:04X}", cp)
            x_spin = QSpinBox(self)
            y_spin = QSpinBox(self)
            for spin in [x_spin, y_spin]:
                spin.setRange(OFFSET_MIN, OFFSET_MAX)
                spin.setValue(OFFSET_DEFAULT)
                spin.setMinimumWidth(70)
                spin.setEnabled(False)
            top = QHBoxLayout()
            top.setSpacing(6)
            top.addWidget(role_label)
            top.addWidget(combo, 1)
            bottom = QHBoxLayout()
            bottom.setSpacing(6)
            indent = QWidget(self)
            indent.setFixedWidth(90)
            indent.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            bottom.addWidget(indent)
            bottom.addWidget(self._axis_icon_label("axis-x"))
            bottom.addWidget(x_spin)
            bottom.addSpacing(8)
            bottom.addWidget(self._axis_icon_label("axis-y"))
            bottom.addWidget(y_spin)
            bottom.addStretch(1)
            layout.addLayout(top)
            layout.addLayout(bottom)
            self._global_mark_combos[role] = combo
            self._global_mark_spins[role] = (x_spin, y_spin)
            combo.currentIndexChanged.connect(lambda _i, r=role: self._on_global_mark_selected(r))
            x_spin.valueChanged.connect(lambda _v, r=role: self._on_global_mark_spin(r))
            y_spin.valueChanged.connect(lambda _v, r=role: self._on_global_mark_spin(r))
        section.set_content(content)
        self._global_section = section
        return section

    def _on_global_mark_selected(self, role: str) -> None:
        """Load the newly selected mark's stored offset into its spins without emitting."""
        mark_uni = self._global_mark_combos[role].currentData()
        has_mark = mark_uni is not None
        settings = self._settings if self._settings is not None else PlacementSettings()
        off = current_global_mark_offset(role, mark_uni, settings) if has_mark else Offset()
        x_spin, y_spin = self._global_mark_spins[role]
        for spin in [x_spin, y_spin]:
            spin.blockSignals(True)
        try:
            x_spin.setValue(off.x)
            y_spin.setValue(off.y)
        finally:
            for spin in [x_spin, y_spin]:
                spin.blockSignals(False)
            for spin in [x_spin, y_spin]:
                spin.setEnabled(has_mark and self._font_loaded)

    def _on_global_mark_spin(self, role: str) -> None:
        """Emit the live `(mark_uni, x, y)` global offset for `role`'s selected mark."""
        mark_uni = self._global_mark_combos[role].currentData()
        if mark_uni is None:
            return
        x_spin, y_spin = self._global_mark_spins[role]
        self.global_mark_offset_changed.emit(role, mark_uni, x_spin.value(), y_spin.value())

    def load_global_marks(self, settings: PlacementSettings) -> None:
        """Refresh the global mark spins from `settings` without emitting; cache it for selector switches."""
        self._settings = settings
        if hasattr(self, "_global_section"):
            entry_count = sum(len(group) for group in settings.marks.values())
            self._global_section.set_summary(f"{entry_count} set" if entry_count else None)
        for role, (x_spin, y_spin) in self._global_mark_spins.items():
            mark_uni = self._global_mark_combos[role].currentData()
            if mark_uni is None:
                continue
            off = current_global_mark_offset(role, mark_uni, settings)
            x_spin.blockSignals(True)
            y_spin.blockSignals(True)
            try:
                x_spin.setValue(off.x)
                y_spin.setValue(off.y)
            finally:
                x_spin.blockSignals(False)
                y_spin.blockSignals(False)

    def clear_global_marks(self) -> None:
        """Reset the global mark selectors and spins, collapsing and disabling them."""
        self._settings = None
        if hasattr(self, "_global_section"):
            self._global_section.set_summary(None)
            self._global_section.set_expanded(False)
        for role, combo in self._global_mark_combos.items():
            x_spin, y_spin = self._global_mark_spins[role]
            widgets: list[QComboBox | QSpinBox] = [combo, x_spin, y_spin]
            for widget in widgets:
                widget.blockSignals(True)
            try:
                combo.setCurrentIndex(0)
                x_spin.setValue(OFFSET_DEFAULT)
                y_spin.setValue(OFFSET_DEFAULT)
            finally:
                for widget in widgets:
                    widget.blockSignals(False)
                for spin in [x_spin, y_spin]:
                    spin.setEnabled(False)

    def _build_base_offsets_section(self) -> CollapsibleSection:
        """Build the Base Offsets collapsible: one X/Y spin pair per placement role."""
        section = CollapsibleSection("Base Offsets", self)
        content = QWidget(section)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for role in BASE_OFFSET_ROLES:
            row = QHBoxLayout()
            row.setSpacing(6)
            role_label = QLabel(_DEFAULT_ROLE_LABELS[role], self)
            role_label.setMinimumWidth(90)
            x_spin = QSpinBox(self)
            y_spin = QSpinBox(self)
            for spin in [x_spin, y_spin]:
                spin.setRange(OFFSET_MIN, OFFSET_MAX)
                spin.setValue(OFFSET_DEFAULT)
                spin.setMinimumWidth(70)
            row.addWidget(role_label)
            row.addStretch(1)
            row.addWidget(self._axis_icon_label("axis-x"))
            row.addWidget(x_spin)
            row.addWidget(self._axis_icon_label("axis-y"))
            row.addWidget(y_spin)
            layout.addLayout(row)
            self._base_offset_spins[role] = (x_spin, y_spin)
            x_spin.valueChanged.connect(lambda _v, r=role: self._on_base_spin(r))
            y_spin.valueChanged.connect(lambda _v, r=role: self._on_base_spin(r))
        section.set_content(content)
        section.set_expanded(True)
        self._base_section = section
        return section

    def _on_base_spin(self, role: str) -> None:
        """Emit the live `(x, y)` base-offset pair for `role`."""
        x_spin, y_spin = self._base_offset_spins[role]
        self.base_offset_changed.emit(role, x_spin.value(), y_spin.value())

    def _build_glyph_substitutions_section(self) -> CollapsibleSection:
        """Build the Glyph Substitutions collapsible: one read-only combo per substitution role."""
        section = CollapsibleSection("Glyph Substitutions", self)
        content = QWidget(section)
        form = QFormLayout(content)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)
        for role in GLYPH_SUBSTITUTION_ROLES:
            combo = QComboBox(self)
            combo.addItem(NO_OVERRIDE)
            combo.setMinimumWidth(160)
            combo.setEnabled(False)
            self._sub_combos[role] = combo
            form.addRow(_SUB_ROLE_LABELS[role], combo)
            combo.currentIndexChanged.connect(lambda _i, r=role: self._on_sub_commit(r))
        section.set_content(content)
        section.set_expanded(True)
        self._sub_section = section
        return section

    def _on_sub_commit(self, role: str) -> None:
        """Emit the staged glyph-substitution override for `role` (empty clears)."""
        text = self._sub_combos[role].currentText().strip()
        glyph_name = "" if text == NO_OVERRIDE or not text else text
        self.glyph_substitution_changed.emit(role, glyph_name)

    def _build_snap_configs_section(self) -> CollapsibleSection:
        """Build the Snap Configs collapsible: one checkbox plus gap spin per snap pair."""
        section = CollapsibleSection("Snap Configs", self)
        content = QWidget(section)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for name in SNAPS:
            row = QHBoxLayout()
            row.setSpacing(8)
            chk = QCheckBox(SNAP_LABELS[name], self)
            chk.setMinimumWidth(180)
            spin = QSpinBox(self)
            spin.setRange(SNAP_GAP_MIN, SNAP_GAP_MAX)
            spin.setValue(SNAP_GAP_DEFAULT)
            spin.setEnabled(False)
            spin.setMinimumWidth(70)
            gap_label = QLabel("Gap:", self)
            gap_label.setObjectName("Label")
            row.addWidget(chk)
            row.addStretch(1)
            row.addWidget(gap_label)
            row.addWidget(spin)
            layout.addLayout(row)
            self._snap_checks[name] = chk
            self._snap_gaps[name] = spin
            chk.toggled.connect(lambda _c, n=name: self._on_snap_chk(n))
            spin.valueChanged.connect(lambda _v, n=name: self._on_snap_gap(n))
        section.set_content(content)
        section.set_expanded(True)
        self._snap_section = section
        return section

    def _on_snap_chk(self, name: str) -> None:
        """Re-enable/disable `name`'s gap spin, then emit the live pair."""
        chk = self._snap_checks[name]
        spin = self._snap_gaps[name]
        on = chk.isChecked()
        spin.setEnabled(on)
        self.snap_changed.emit(name, on, spin.value())

    def _on_snap_gap(self, name: str) -> None:
        """Emit the live `(enabled, gap)` for `name` when the gap spin changes."""
        chk = self._snap_checks[name]
        spin = self._snap_gaps[name]
        self.snap_changed.emit(name, chk.isChecked(), spin.value())

    def set_font_loaded(self, loaded: bool) -> None:
        """Toggle the pane-global actions that require a loaded font."""
        self._reset_btn.setEnabled(loaded)
        self._font_loaded = loaded
        for role in ROLES:
            has_mark = self._global_mark_combos[role].currentData() is not None
            for spin in self._global_mark_spins[role]:
                spin.setEnabled(loaded and has_mark)

    def set_enabled(self, enabled: bool, categories: frozenset[MarkCategory] | None = None) -> None:
        """Toggle the mark-offset controls, restricting radios to the enabled categories.

        Disabling resets the category cache so a stale glyph's roles cannot leak into
        the next selection.
        """
        self._enabled = enabled
        if not enabled:
            self._enabled_categories = set(_CATEGORY_ITER)
        elif categories is not None:
            self._enabled_categories = set(categories)
        self._x_slider.setEnabled(enabled)
        self._x_spin.setEnabled(enabled)
        self._y_slider.setEnabled(enabled)
        self._y_spin.setEnabled(enabled)
        for category, rb in self._radios.items():
            rb.setEnabled(enabled and category in self._enabled_categories)

    def set_consonant_enabled(self, enabled: bool) -> None:
        """Toggle the per-consonant Base Offsets, Consonant substitution, and Snap Configs groups.

        Mark-role substitution combos require a selected PUA glyph and are managed by
        `load_spec_mark_substitutions`.
        """
        self._consonant_active = enabled
        self._sub_combos[SUB_CONSONANT].setEnabled(enabled)
        for x_spin, y_spin in self._base_offset_spins.values():
            x_spin.setEnabled(enabled)
            y_spin.setEnabled(enabled)
        for name, chk in self._snap_checks.items():
            chk.setEnabled(enabled)
            self._snap_gaps[name].setEnabled(enabled and chk.isChecked())

    def load_offset(self, x: int, y: int, category: MarkCategory) -> None:
        """Display `(x, y)` and `category` without emitting; cancel any pending throttled commit."""
        self._commit_timer.stop()
        self._offset_pending = False
        for w in self._slider_spin_pairs_flat():
            w.blockSignals(True)
        for rb in self._radios.values():
            rb.blockSignals(True)
        try:
            self._x_slider.setValue(x)
            self._x_spin.setValue(x)
            self._y_slider.setValue(y)
            self._y_spin.setValue(y)
            target = self._radios.get(category)
            if target is not None:
                target.setChecked(True)
        finally:
            for w in self._slider_spin_pairs_flat():
                w.blockSignals(False)
            for rb in self._radios.values():
                rb.blockSignals(False)

    def load_consonant_settings(
        self, cons_uni: int, settings: PlacementSettings, catalog: Mapping[str, Sequence[GlyphSubstitution]]
    ) -> None:
        """Populate Base Offsets, Consonant substitution, and Snap Configs for `cons_uni` without emitting.

        A stored substitution not in the catalog is added to the combo so it round-trips.
        """
        self.load_global_marks(settings)
        for role, (x_spin, y_spin) in self._base_offset_spins.items():
            x_spin.blockSignals(True)
            y_spin.blockSignals(True)
            off = current_base_offset(cons_uni, role, settings)
            x_spin.setValue(off.x)
            y_spin.setValue(off.y)
            x_spin.blockSignals(False)
            y_spin.blockSignals(False)
        self._reload_role_substitution(SUB_CONSONANT, cons_uni, cons_uni, settings, catalog, present_roles=frozenset())
        for role in [SUB_TONE_MARK, SUB_ABOVE_VOWEL, SUB_BELOW_VOWEL]:
            combo = self._sub_combos[role]
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(NO_OVERRIDE)
            combo.blockSignals(False)
            combo.setEnabled(False)
        for name in SNAPS:
            chk = self._snap_checks[name]
            spin = self._snap_gaps[name]
            chk.blockSignals(True)
            spin.blockSignals(True)
            cfg = current_snap(cons_uni, name, settings)
            enabled = cfg.enabled if cfg is not None else False
            gap = cfg.gap if cfg is not None else 0
            chk.setChecked(enabled)
            spin.setValue(gap)
            spin.setEnabled(enabled)
            chk.blockSignals(False)
            spin.blockSignals(False)
        self.set_consonant_enabled(True)

    def load_spec_mark_substitutions(
        self, spec: CompositeSpec, settings: PlacementSettings, catalog: Mapping[str, Sequence[GlyphSubstitution]]
    ) -> None:
        """Populate the mark-role substitution combos from `spec`'s mark codepoints.

        A role absent from the spec is reset and disabled.
        """
        present_roles = present_roles_for(spec)
        role_to_codepoint = (
            (SUB_TONE_MARK, spec.tone_uni),
            (SUB_ABOVE_VOWEL, spec.above_uni),
            (SUB_BELOW_VOWEL, spec.below_uni),
        )
        for role, codepoint in role_to_codepoint:
            combo = self._sub_combos[role]
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(NO_OVERRIDE)
            if codepoint is not None:
                for name in glyph_substitution_candidates(codepoint, role, catalog):
                    combo.addItem(name)
                stored = current_glyph_substitution(codepoint, spec.cons_uni, settings, present_roles=present_roles)
                if stored:
                    self._select_stored_substitution(combo, stored)
                else:
                    combo.setCurrentIndex(0)
            combo.blockSignals(False)
            combo.setEnabled(codepoint is not None and self._consonant_active)

    def load_consonant_sub_for_spec(
        self,
        spec: CompositeSpec,
        settings: PlacementSettings,
        catalog: Mapping[str, Sequence[GlyphSubstitution]],
        cons_uni: int,
    ) -> None:
        """Reload the consonant-role substitution combo using the active spec's context."""
        self._reload_role_substitution(
            SUB_CONSONANT, cons_uni, cons_uni, settings, catalog, present_roles=present_roles_for(spec)
        )

    def _reload_role_substitution(
        self,
        role: str,
        codepoint: int,
        cons_uni: int,
        settings: PlacementSettings,
        catalog: Mapping[str, Sequence[GlyphSubstitution]],
        *,
        present_roles: frozenset[str],
    ) -> None:
        """Reload a single substitution combo from `catalog`/`settings` without emitting.

        `cons_uni` selects the consonant; `codepoint` is the substituted codepoint;
        `present_roles` gates contextual matching.
        """
        combo = self._sub_combos[role]
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem(NO_OVERRIDE)
            for name in glyph_substitution_candidates(codepoint, role, catalog):
                combo.addItem(name)
            stored = current_glyph_substitution(codepoint, cons_uni, settings, present_roles=present_roles)
            if stored:
                self._select_stored_substitution(combo, stored)
            else:
                combo.setCurrentIndex(0)
        finally:
            combo.blockSignals(False)

    def _select_stored_substitution(self, combo: QComboBox, stored: str) -> None:
        """Select `stored` in a read-only combo, appending it when absent from the catalog."""
        index = combo.findText(stored)
        if index < 0:
            combo.addItem(stored)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    def clear_consonant_settings(self) -> None:
        """Reset the per-consonant groups and disable them."""
        self.set_consonant_enabled(False)
        self.clear_global_marks()
        for x_spin, y_spin in self._base_offset_spins.values():
            x_spin.blockSignals(True)
            y_spin.blockSignals(True)
            x_spin.setValue(0)
            y_spin.setValue(0)
            x_spin.blockSignals(False)
            y_spin.blockSignals(False)
        for role in GLYPH_SUBSTITUTION_ROLES:
            combo = self._sub_combos[role]
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(NO_OVERRIDE)
            combo.blockSignals(False)
            combo.setEnabled(False)
        for name in SNAPS:
            chk = self._snap_checks[name]
            spin = self._snap_gaps[name]
            chk.blockSignals(True)
            spin.blockSignals(True)
            chk.setChecked(False)
            spin.setValue(0)
            spin.setEnabled(False)
            chk.blockSignals(False)
            spin.blockSignals(False)

    def refresh_icons(self) -> None:
        """Re-tint the axis icons and the reset button for the active theme palette."""
        for icon_name, label in self._axis_icons:
            label.setPixmap(icons.icon(icon_name).pixmap(QSize(16, 16)))
        self._reset_btn.setIcon(icons.icon("rotate-ccw"))
        for section in (
            getattr(self, "_mark_section", None),
            getattr(self, "_global_section", None),
            getattr(self, "_base_section", None),
            getattr(self, "_sub_section", None),
            getattr(self, "_snap_section", None),
        ):
            if section is not None:
                section.refresh_style()

    def _slider_spin_pairs_flat(self) -> tuple[QSlider | QSpinBox, ...]:
        """Return the slider/spin tuple used to block and restore signals in bulk."""
        return (self._x_slider, self._x_spin, self._y_slider, self._y_spin)
