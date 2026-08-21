"""Right pane: *Controls* — Mark Offsets, Base Offsets, Glyph Substitutions, Snap Configs.

The pane owns no `AppState`; it exposes high-level setters and emits low-level signals
so the main window stays the single mutator of state:

- `offset_changed(x, y)` — live per-glyph *Mark Offset* edits.
- `base_offset_changed(role, x, y)` — live per-consonant *Base Offsets* edits.
- `glyph_substitution_changed(role, glyph_name)` — commits a per-consonant *Glyph
  Substitution* override from the GSUB catalog (an empty name clears).
- `snap_changed(name, enabled, gap)` — commits a per-consonant *Snap Config*.
- `category_changed(category)` — notifies that the X/Y inputs must be reloaded for the
  newly picked role.

Every group commits live through the main window's signal handlers. Per-consonant groups
are gated on an active consonant; the Mark Offset group on a selected PUA glyph. Base and
Mark Offsets read/write disjoint `ConsonantSettings` tiers (see `gui.state`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
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
    ROLE_TONE_MARK,
    ROLE_TONE_MARK_ON_ABOVE_VOWEL,
    SNAPS,
    SUB_ABOVE_VOWEL,
    SUB_BELOW_VOWEL,
    SUB_CONSONANT,
    SUB_TONE_MARK,
    PlacementSettings,
)
from thaipua.gui import icons
from thaipua.gui.icons import IconName
from thaipua.gui.state import (
    MARK_CATEGORY_LABELS,
    SNAP_LABELS,
    MarkCategory,
    current_base_offset,
    current_glyph_substitution,
    current_snap,
    glyph_substitution_candidates,
    present_roles_for,
)

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
    """Right-pane *Controls*: offset + per-consonant settings for one glyph.

    The Mark Offset group binds to the active PUA glyph (offset sliders per selected
    role radio) and previews live. The Base Offsets, Glyph Substitutions, and Snap
    Configs groups bind to the active consonant and commit live so each control mirrors
    the composer's settings directly.
    """

    offset_changed = Signal(int, int)
    base_offset_changed = Signal(str, int, int)
    glyph_substitution_changed = Signal(str, str)
    snap_changed = Signal(str, bool, int)
    category_changed = Signal(object)
    _sub_combos: dict[str, QComboBox]
    _snap_checks: dict[str, QCheckBox]
    _snap_gaps: dict[str, QSpinBox]
    _base_offset_spins: dict[str, tuple[QSpinBox, QSpinBox]]
    _radios: dict[MarkCategory, QRadioButton]
    _radio_group: QButtonGroup
    _axis_icons: list[tuple[IconName, QLabel]]

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
        self._consonant_active = False
        self._enabled = False
        self._enabled_categories = set(_CATEGORY_ITER)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QLabel("Controls", self)
        header.setObjectName("PaneHeader")
        outer.addWidget(header)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget(scroll)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)
        container_layout.addWidget(self._build_offset_group())
        container_layout.addWidget(self._build_base_offsets_group())
        container_layout.addWidget(self._build_glyph_substitutions_group())
        container_layout.addWidget(self._build_snap_configs_group())
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

    def _build_offset_group(self) -> QGroupBox:
        """Build the *Mark Offsets* group: X/Y sliders + category radios."""
        group = QGroupBox("Mark Offsets", self)
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(10, 16, 10, 10)
        group_layout.setSpacing(10)
        group_layout.addLayout(self._build_axis_row("axis-x", self._x_slider, self._x_spin))
        group_layout.addLayout(self._build_axis_row("axis-y", self._y_slider, self._y_spin))
        group_layout.addSpacing(4)
        group_layout.addWidget(self._build_category_radios())
        return group

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
        """Set `other` to `value` without re-entering its change handler.

        The `offset_changed` emission is throttled to one commit per interval by
        starting the single-shot timer only while idle, so fast drags keep emitting
        intermediate commits instead of starving until they pause. `_emit_offset_commit`
        reads live spin values at fire time, so the newest position (incl. the drag's
        final tick) is never dropped.
        """
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

    def _build_base_offsets_group(self) -> QGroupBox:
        """Build the *Base Offsets* group: one X/Y spin pair per placement role.

        Both spins of each role emit `base_offset_changed` with the live pair on every
        edit — the main window writes the `base_offsets` tier directly.
        """
        group = QGroupBox("Base Offsets", self)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 16, 10, 10)
        layout.setSpacing(6)
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
            axis_icons: list[tuple[IconName, QSpinBox]] = [("axis-x", x_spin), ("axis-y", y_spin)]
            for icon_name, spin in axis_icons:
                row.addWidget(self._axis_icon_label(icon_name))
                row.addWidget(spin)
            layout.addLayout(row)
            self._base_offset_spins[role] = (x_spin, y_spin)
            x_spin.valueChanged.connect(lambda _v, r=role: self._on_base_spin(r))
            y_spin.valueChanged.connect(lambda _v, r=role: self._on_base_spin(r))
        return group

    def _on_base_spin(self, role: str) -> None:
        """Emit the live `(x, y)` base-offset pair for `role`."""
        x_spin, y_spin = self._base_offset_spins[role]
        self.base_offset_changed.emit(role, x_spin.value(), y_spin.value())

    def _build_glyph_substitutions_group(self) -> QGroupBox:
        """Build the *Glyph Substitutions* group: one read-only combo per substitution role.

        Committing live means a dropdown selection fires immediately through
        `currentIndexChanged`; there is no free-text input, so a substitution is
        always one of the catalog candidates (or "(no override)").
        """
        group = QGroupBox("Glyph Substitutions", self)
        form = QFormLayout(group)
        form.setContentsMargins(10, 16, 10, 10)
        form.setSpacing(6)
        for role in GLYPH_SUBSTITUTION_ROLES:
            combo = QComboBox(self)
            combo.addItem(NO_OVERRIDE)
            combo.setMinimumWidth(160)
            combo.setEnabled(False)
            self._sub_combos[role] = combo
            form.addRow(_SUB_ROLE_LABELS[role], combo)
            combo.currentIndexChanged.connect(lambda _i, r=role: self._on_sub_commit(r))
        return group

    def _on_sub_commit(self, role: str) -> None:
        """Emit the staged glyph-substitution override for `role` (empty clears)."""
        text = self._sub_combos[role].currentText().strip()
        glyph_name = "" if text == NO_OVERRIDE or not text else text
        self.glyph_substitution_changed.emit(role, glyph_name)

    def _build_snap_configs_group(self) -> QGroupBox:
        """Build the *Snap Configs* group: one checkbox + gap spin per snap pair.

        Toggling a checkbox re-enables its gap spin and emits `snap_changed` for the
        (now on/off) pair; editing the gap emits the live `(enabled, gap)` so the main
        window commits both fields together.
        """
        group = QGroupBox("Snap Configs", self)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 16, 10, 10)
        layout.setSpacing(6)
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
        return group

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

    def set_enabled(self, enabled: bool, categories: frozenset[MarkCategory] | None = None) -> None:
        """Toggle the per-glyph Mark Offset controls' disabled state.

        A radio stays disabled when its category is absent from the spec's mark
        composition. Disabling resets the cached set to all categories so a stale
        partial glyph's roles cannot leak into the next selection; re-enabling without
        `categories` re-uses the current set (for an unchanged spec).
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
        """Toggle the per-consonant Base Offsets / Consonant substitution / Snap Configs groups.

        The consonant-role substitution combo follows this enabled state; the mark-role
        combos are NOT toggled here — they require both an active consonant and a
        selected PUA glyph, so they're managed by `load_spec_mark_substitutions` and
        reset to disabled otherwise. Snap gap spins additionally track their own
        checkbox.
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
        """Set sliders/spinboxes/radio to `(x, y)` and `category` without emitting.

        Used by the main window when a new glyph is selected so the controls reflect the
        glyph's stored offset without triggering a live preview pass. Any commit
        throttled from the previous glyph is cancelled first so a stale emission cannot
        re-render the newly selected glyph.

        All radios are blocked for the duration of the update — when one radio is
        checked, Qt internally un-checks the previously active radio and would otherwise
        emit a stray `toggled(False)` event.
        """
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
        """Populate Base Offsets / Consonant Substitution / Snap Configs for `cons_uni`.

        The Consonant-role combo is populated now (its codepoint is `cons_uni`); the
        mark-role combos are reset to "(no override)" and disabled until
        `load_spec_mark_substitutions` (which knows the specific mark codepoint). All
        widgets are signal-blocked during the reload to prevent live commits. A stored
        substitution not in the catalog is added to the combo so it round-trips.
        """
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
        """Populate the mark-role substitution combos for `spec`'s mark codepoints.

        Each combo is reseeded from the catalog for its spec-provided codepoint and
        switches to the stored contextual override matching the spec's present mark-role
        set. A role absent from the spec is reset and disabled. Scoped to
        `spec.cons_uni`. Signal-blocked during reload; a stored substitution not in the
        catalog is added so it round-trips.
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
        """Reload the consonant-role substitution combo with the active spec's context.

        Uses `present_roles_for(spec)` so the combo surfaces the contextual rule's
        stored glyph instead of the always-on fallback. `load_consonant_settings`
        continues to use the always-on context for the same combo (no PUA spec
        selected).
        """
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

        `cons_uni` selects the consonant; `codepoint` is the substituted codepoint. The
        `present_roles` set gates contextual matching (empty matches only always-on
        rules). canonicalization is per-codepoint category (`context_canonicalizer`):
        a tone-mark rule's below-vowel family surfaces for the tone-only cluster; an
        ascender-protruding consonant rule (e.g. ฬ) surfaces for every above-stack
        context; every other consonant and vowel rule uses the generic
        tone-within-vowel-family canonicalization.
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
        """Select `stored` in a read-only combo, adding the item if absent.

        A stored substitution not among the catalog candidates is appended so it round-
        trips instead of silently showing "(no override)".
        """
        index = combo.findText(stored)
        if index < 0:
            combo.addItem(stored)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    def clear_consonant_settings(self) -> None:
        """Reset the per-consonant groups and disable them.

        Used when the active consonant is left (Back to index) or the font is reopened,
        so live edits do not outlive the consonant selection.
        """
        self.set_consonant_enabled(False)
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
        """Re-tint the Mark/Base offset axis icons for the active theme palette.

        Called by the main window after a theme switch (which follows
        `icons.clear_cache`) so the axis icons do not keep a stale tint from the
        previous palette.
        """
        for icon_name, label in self._axis_icons:
            label.setPixmap(icons.icon(icon_name).pixmap(QSize(16, 16)))

    def _slider_spin_pairs_flat(self) -> tuple[QSlider | QSpinBox, ...]:
        """Return the slider/spin tuple used to block + restore signals in bulk."""
        return (self._x_slider, self._x_spin, self._y_slider, self._y_spin)
