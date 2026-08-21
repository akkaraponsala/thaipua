"""In-memory application state and offset bookkeeping for the desktop GUI.

`AppState` is the single mutable object the main window swaps across panes. All
functions here operate on `AppState`, `PlacementSettings`, or `CompositeSpec` and are
deliberately PySide6-free so they stay unit-testable without a `QApplication`. Widgets
read through the main window and never mutate state directly.

Mark Offset and Base Offset are independent surfaces here, mirroring
`ConsonantSettings`: the Mark Offset functions read/write only the per-glyph
`mark_offsets`/`combo_offsets` tiers, the Base Offset functions only `base_offsets` —
never the two together. Tier resolution lives in `ConsonantSettings.offset_for`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from thaipua.core.fonttools.settings import (
    ROLE_ABOVE_VOWEL,
    ROLE_BELOW_VOWEL,
    ROLE_TONE_MARK,
    SNAP_ABOVE_TO_CONS,
    SNAP_BELOW_TO_CONS,
    SNAP_TONE_TO_ABOVE,
    SUB_ABOVE_VOWEL,
    SUB_BELOW_VOWEL,
    SUB_CONSONANT,
    SUB_TONE_MARK,
    ConsonantSettings,
    Offset,
    PlacementSettings,
    SnapConfig,
    SubstitutionRule,
    combo_key_from_codepoints,
    context_canonicalizer,
    default_placement_settings,
)
from thaipua.core.fonttools.specs import THAI_CONSONANTS, CompositeSpec, iter_composite_specs

if TYPE_CHECKING:
    from thaipua.core.fonttools.alternates import GlyphSubstitution
GRID_COLUMNS = 6
GRID_ROWS = 6
GRID_PAGE_SIZE = GRID_COLUMNS * GRID_ROWS


class MarkCategory(Enum):
    """The right-pane radio category a selected PUA glyph maps to.

    - `TONE_MARK` — consonant + tone only, or consonant + above vowel + tone; the user
      can switch to `ABOVE_VOWEL` for the same spec to edit the vowel's own offset.
    - `ABOVE_VOWEL` — consonant + above vowel only.
    - `BELOW_VOWEL` — consonant + below vowel only.
    """

    TONE_MARK = "tone_mark"
    ABOVE_VOWEL = "above_vowel"
    BELOW_VOWEL = "below_vowel"


MARK_CATEGORY_LABELS: dict[MarkCategory, str] = {
    MarkCategory.TONE_MARK: "Tone Mark",
    MarkCategory.ABOVE_VOWEL: "Above Vowel",
    MarkCategory.BELOW_VOWEL: "Below Vowel",
}
SUB_ROLE_TO_CATALOG_KEY: dict[str, str] = {
    SUB_CONSONANT: "consonants",
    SUB_TONE_MARK: "tone_marks",
    SUB_ABOVE_VOWEL: "above_vowels",
    SUB_BELOW_VOWEL: "below_vowels",
}
SNAP_LABELS: dict[str, str] = {
    SNAP_TONE_TO_ABOVE: "Tone Mark -> Above Vowel",
    SNAP_ABOVE_TO_CONS: "Above Vowel -> Consonant",
    SNAP_BELOW_TO_CONS: "Below Vowel -> Consonant",
}


@dataclass(slots=True)
class AppState:
    """Mutable GUI state: loaded font, settings being edited, PUA map, selection.

    The PUA map's file path is owned by `FontService.pua_map_path`, not this dataclass.
    `settings` uses defaults until a font is loaded. `dirty` covers pending
    `settings`/`pua_map`/composite edits.
    """

    font_path: str | None = None
    pua_map: dict[str, str] = field(default_factory=dict)
    settings: PlacementSettings = field(default_factory=default_placement_settings)
    active_consonant_uni: int | None = None
    active_pua_code: int | None = None
    consonants_page: int = 0
    pua_page: int = 0
    dirty: bool = False


def inferable_consonants() -> list[int]:
    """Return the 42 modern Thai consonant codepoints in canonical order.

    `THAI_CONSONANTS` is a `set`; this helper exposes the ordered list used to drive the
    consonant-index page grid.
    """
    return sorted(THAI_CONSONANTS)


def infer_category(spec: CompositeSpec) -> MarkCategory | None:
    """Return the radio category implied by `spec`'s mark composition.

    A spec carrying both an above vowel and a tone mark defaults to `TONE_MARK` (the
    visible topmost mark in the stack); the user can switch to `ABOVE_VOWEL` via the
    radio group to edit the vowel's own offset independently. Returns `None` for a base
    consonant with no vowel/tone suffix; such specs are not editable from the controls
    pane.
    """
    has_above = spec.above_uni is not None
    has_below = spec.below_uni is not None
    has_tone = spec.tone_uni is not None
    if has_tone:
        return MarkCategory.TONE_MARK
    if has_above:
        return MarkCategory.ABOVE_VOWEL
    if has_below:
        return MarkCategory.BELOW_VOWEL
    return None


def combo_key_for(spec: CompositeSpec) -> str | None:
    """Return the canonical combination key for `spec`'s marks.

    Marks are sorted ascending by codepoint and concatenated; `None` is returned for
    consonant-only specs so callers can short-circuit combination lookups (matching
    `ThaiPuaFontGenerator._combo_key` exactly).
    """
    cps = [c for c in [spec.below_uni, spec.above_uni, spec.tone_uni] if c]
    return combo_key_from_codepoints(cps)


def categories_for(spec: CompositeSpec) -> frozenset[MarkCategory]:
    """Return the Mark Offset radio categories enabled by `spec`'s marks.

    A category is enabled only when the spec carries the mark role that category edits:
    `TONE_MARK` needs a tone codepoint, `ABOVE_VOWEL` an above vowel, `BELOW_VOWEL` a
    below vowel. Combined specs (e.g. above-plus-tone) enable one category per present
    mark. Returns an empty frozenset for a consonant-only spec.
    """
    cats: set[MarkCategory] = set()
    if spec.tone_uni:
        cats.add(MarkCategory.TONE_MARK)
    if spec.above_uni:
        cats.add(MarkCategory.ABOVE_VOWEL)
    if spec.below_uni:
        cats.add(MarkCategory.BELOW_VOWEL)
    return frozenset(cats)


def _role_for_category(category: MarkCategory) -> str:
    """Return the placement role the offset slider binds to for `category`."""
    if category is MarkCategory.TONE_MARK:
        return ROLE_TONE_MARK
    if category is MarkCategory.ABOVE_VOWEL:
        return ROLE_ABOVE_VOWEL
    return ROLE_BELOW_VOWEL


def _mark_uni_for_role(spec: CompositeSpec, role: str) -> int | None:
    """Return the spec's mark codepoint matching `role`."""
    if role == ROLE_TONE_MARK:
        return spec.tone_uni
    if role == ROLE_ABOVE_VOWEL:
        return spec.above_uni
    if role == ROLE_BELOW_VOWEL:
        return spec.below_uni
    return None


def _mark_count(spec: CompositeSpec) -> int:
    """Return how many distinct mark codepoints `spec` carries (0, 1, or 2+)."""
    return sum(1 for c in (spec.below_uni, spec.above_uni, spec.tone_uni) if c)


def current_mark_offset(spec: CompositeSpec, settings: PlacementSettings, *, category: MarkCategory | None) -> Offset:
    """Resolve the per-glyph Mark Offset override for `spec`, *ignoring* `base_offsets`.

    Single-mark glyphs return the generic `mark_offsets[role][mark]`; multi-mark glyphs
    return the combo-specific `combo_offsets[combo_key][role]` additive delta. The
    composer sums the tiers so the final position is generic + combo + base.
    """
    resolved = category if category is not None else infer_category(spec)
    if resolved is None:
        return Offset()
    cs = settings.for_consonant(spec.cons_uni)
    combo_key = combo_key_for(spec)
    role = _role_for_category(resolved)
    mark_uni = _mark_uni_for_role(spec, role)
    if _mark_count(spec) > 1:
        if combo_key is not None:
            combo = cs.combo_offsets.get(combo_key)
            if combo is not None:
                off = combo.get(role)
                if off is not None:
                    return off
        return Offset()
    if mark_uni is not None:
        group = cs.mark_offsets.get(role)
        if group is not None:
            off = group.get(mark_uni)
            if off is not None:
                return off
    return Offset()


def apply_offset(
    spec: CompositeSpec, settings: PlacementSettings, x: int, y: int, *, category: MarkCategory | None
) -> None:
    """Commit an `(x, y)` offset for `spec` into `settings` (mutates in place).

    Single-mark glyphs write the generic `mark_offsets[role][mark_uni]`; multi-mark glyphs
    write the additive delta `combo_offsets[combo_key][role]`. The final position is
    generic + combo + base. A zero delta clears the combo entry to restore pure
    inheritance. `settings.consonants` is auto-seeded when absent.
    """
    resolved = category if category is not None else infer_category(spec)
    if resolved is None:
        return
    cs = settings.consonants.setdefault(spec.cons_uni, ConsonantSettings())
    combo_key = combo_key_for(spec)
    role = _role_for_category(resolved)
    mark_uni = _mark_uni_for_role(spec, role)
    if mark_uni is None:
        return
    if _mark_count(spec) > 1:
        if x == 0 and y == 0:
            combo_map = cs.combo_offsets.get(combo_key or "")
            if combo_map is not None:
                combo_map.pop(role, None)
                if not combo_map:
                    cs.combo_offsets.pop(combo_key or "", None)
        else:
            combo_role_map = cs.combo_offsets.setdefault(combo_key or "", {})
            combo_role_map[role] = Offset(x, y)
    else:
        mark_role_map = cs.mark_offsets.setdefault(role, {})
        if x == 0 and y == 0:
            mark_role_map.pop(mark_uni, None)
            if not mark_role_map:
                cs.mark_offsets.pop(role, None)
        else:
            mark_role_map[mark_uni] = Offset(x, y)


def glyph_substitution_candidates(
    codepoint: int | None, role: str, catalog: Mapping[str, Sequence[GlyphSubstitution]]
) -> list[str]:
    """Return the ordered, deduped glyph names offered for `role`'s substitution combo.

    `codepoint=None` yields an empty list. The list excludes the leading "(no override)"
    UI sentinel — that entry is appended by the controls pane.
    """
    cat_key = SUB_ROLE_TO_CATALOG_KEY.get(role)
    if cat_key is None or codepoint is None:
        return []
    out: list[str] = []

    def add(name: str | None) -> None:
        if name and name not in out:
            out.append(name)

    for entry in catalog.get(cat_key, []):
        if entry.codepoint != codepoint:
            continue
        add(entry.base_glyph_name)
        for alt in entry.alternate_glyph_names:
            add(alt)
        return out
    return []


def present_roles_for(spec: CompositeSpec) -> frozenset[str]:
    """Return the raw mark-role set present in `spec` for substitution context.

    This is the literal set — the vowel-family canonicalization (dropping `tone_mark`
    when a vowel is present) is applied downstream by `apply_glyph_substitution` and
    `ConsonantSettings.substitution_for`, so callers should pass this value through
    unchanged.
    """
    roles: set[str] = set()
    if spec.tone_uni:
        roles.add(SUB_TONE_MARK)
    if spec.above_uni:
        roles.add(SUB_ABOVE_VOWEL)
    if spec.below_uni:
        roles.add(SUB_BELOW_VOWEL)
    return frozenset(roles)


def current_glyph_substitution(
    codepoint: int, cons_uni: int, settings: PlacementSettings, *, present_roles: frozenset[str]
) -> str | None:
    """Return the best-matching rule's replacement glyph for `codepoint` at `cons_uni`.

    Returns `None` when `cons_uni` has no entry in `settings.consonants` or no matching
    rule exists. Passes `present_roles` so contextual rules match.
    """
    return settings.for_consonant(cons_uni).substitution_for(codepoint, present_roles=present_roles)


def apply_glyph_substitution(
    codepoint: int, cons_uni: int, glyph_name: str | None, settings: PlacementSettings, *, conditions: frozenset[str]
) -> None:
    """Set or clear the `codepoint` substitution rule for `cons_uni` in `settings`.

    A non-empty `glyph_name` installs/replaces the rule whose `conditions` equals the
    supplied `conditions`; an empty/`None` removes it. Other rules for the same
    codepoint are preserved, accumulating one per context. Mutates
    `consonants[cons_uni].glyph_substitutions[codepoint]` in place (seeding on first
    install, clearing the codepoint list when it empties).

    `conditions` is canonicalized before storage by `context_canonicalizer(codepoint)`,
    so writes from contexts sharing one substitution slot address it and the latest
    write wins: a tone-mark codepoint collapses the below-vowel family into the
    tone-only family; an ascender-protruding consonant (e.g. ฬ) collapses every
    above-stack context into `{above_vowel, tone_mark}`; every other consonant and
    vowel codepoint drops `tone_mark` within any vowel family.
    """
    conditions = context_canonicalizer(codepoint)(conditions)
    cs = settings.consonants.setdefault(cons_uni, ConsonantSettings())
    rules = cs.glyph_substitutions.get(codepoint, [])
    for i, existing in enumerate(list(rules)):
        if existing.conditions == conditions:
            if glyph_name:
                rules[i] = SubstitutionRule(replacement=glyph_name, conditions=conditions)
                return
            rules.pop(i)
            if not rules:
                cs.glyph_substitutions.pop(codepoint, None)
            return
    if glyph_name:
        rules.append(SubstitutionRule(replacement=glyph_name, conditions=conditions))
        cs.glyph_substitutions[codepoint] = rules


def current_snap(cons_uni: int, snap_name: str, settings: PlacementSettings) -> SnapConfig | None:
    """Return the snap config for `snap_name` on `cons_uni`, or `None` when unset."""
    return settings.for_consonant(cons_uni).snap_for(snap_name)


def apply_snap(cons_uni: int, snap_name: str, enabled: bool, gap: int, settings: PlacementSettings) -> None:
    """Set or clear the `snap_name` snap for `cons_uni` in `settings`.

    A disabled snap is cleared entirely (the composer treats an absent snap and an
    explicitly disabled snap identically), keeping the in-memory map free of no-op
    entries. Enabling records a `SnapConfig(enabled=True, gap)`.
    """
    cs = settings.consonants.setdefault(cons_uni, ConsonantSettings())
    if not enabled:
        cs.snap_configs.pop(snap_name, None)
    else:
        cs.snap_configs[snap_name] = SnapConfig(enabled=True, gap=gap)


def current_base_offset(cons_uni: int, role: str, settings: PlacementSettings) -> Offset:
    """Return the base-offset delta for `role` on `cons_uni`, or `Offset(0, 0)`."""
    return settings.for_consonant(cons_uni).base_offsets.get(role, Offset())


def apply_base_offset(cons_uni: int, role: str, x: int, y: int, settings: PlacementSettings) -> None:
    """Set or clear the `role` base offset for `cons_uni` in `settings`.

    A `(0, 0)` delta is cleared (the composer's `offset_for` returns `Offset(0, 0)` when
    a role is absent from `base_offsets`, and `_base_offsets_to_dict` omits zero
    entries), keeping the in-memory map free of no-op overrides.
    """
    cs = settings.consonants.setdefault(cons_uni, ConsonantSettings())
    if x == 0 and y == 0:
        cs.base_offsets.pop(role, None)
    else:
        cs.base_offsets[role] = Offset(x, y)


def group_composites_by_consonant(pua_map: dict[str, str]) -> dict[int, list[CompositeSpec]]:
    """Return a `cons_uni -> [CompositeSpec, ...]` index over `pua_map`.

    Specs per consonant are sorted ascending by `pua_code` so the PUA page grid stays
    deterministic across mapping reloads.
    """
    out: defaultdict[int, list[CompositeSpec]] = defaultdict(list)
    for spec in iter_composite_specs(pua_map):
        out[spec.cons_uni].append(spec)
    for specs in out.values():
        specs.sort(key=lambda s: s.pua_code)
    return dict(out)


def pua_specs_for_consonant(pua_map: dict[str, str], cons_uni: int) -> list[CompositeSpec]:
    """Return the ascending-`pua_code` sorted specs for `cons_uni` in `pua_map`."""
    return group_composites_by_consonant(pua_map).get(cons_uni, [])


__all__ = [
    "GRID_COLUMNS",
    "GRID_PAGE_SIZE",
    "GRID_ROWS",
    "MARK_CATEGORY_LABELS",
    "SNAP_LABELS",
    "SUB_ROLE_TO_CATALOG_KEY",
    "AppState",
    "MarkCategory",
    "apply_base_offset",
    "apply_glyph_substitution",
    "apply_offset",
    "apply_snap",
    "categories_for",
    "combo_key_for",
    "current_base_offset",
    "current_glyph_substitution",
    "current_mark_offset",
    "current_snap",
    "glyph_substitution_candidates",
    "group_composites_by_consonant",
    "infer_category",
    "inferable_consonants",
    "present_roles_for",
    "pua_specs_for_consonant",
]
