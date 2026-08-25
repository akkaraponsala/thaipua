"""Mutable application state plus helpers reading and writing placement-settings tiers."""

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
    """Mark role selected in the controls pane for offset editing."""

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
    SNAP_TONE_TO_ABOVE: "Tone Mark → Above Vowel",
    SNAP_ABOVE_TO_CONS: "Above Vowel → Consonant",
    SNAP_BELOW_TO_CONS: "Below Vowel → Consonant",
}


@dataclass(slots=True)
class AppState:
    """Central mutable GUI state shared across panes."""

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

    `THAI_CONSONANTS` is a `set`; this helper exposes the ordered list driving the
    consonant-index page grid.
    """
    return sorted(THAI_CONSONANTS)


def infer_category(spec: CompositeSpec) -> MarkCategory | None:
    """Return the controls category implied by a spec's marks, or `None` for plain consonants."""
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
    """Return the spec's canonical combination key, or `None` for fewer than two marks."""
    cps = [c for c in [spec.below_uni, spec.above_uni, spec.tone_uni] if c]
    if len(cps) < 2:
        return None
    return combo_key_from_codepoints(cps)


def categories_for(spec: CompositeSpec) -> frozenset[MarkCategory]:
    """Return the offset-editing categories enabled by a spec's marks."""
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
    """Return the per-glyph offset override for the selected category, excluding base offsets."""
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
    """Commit an `(x, y)` offset override for `spec` under the selected category.

    Writes the mark tier for single-mark glyphs and the combo tier for multi-mark
    glyphs; a zero delta clears the entry.
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
    """List candidate glyph names for a role's substitution combo, deduplicated in catalog order."""
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
    """Return the literal mark-role set carried by a spec, prior to canonicalization."""
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

    Return `None` when `cons_uni` has no entry in `settings.consonants` or no matching
    rule exists. Pass `present_roles` so contextual rules match.
    """
    return settings.for_consonant(cons_uni).substitution_for(codepoint, present_roles=present_roles)


def apply_glyph_substitution(
    codepoint: int, cons_uni: int, glyph_name: str | None, settings: PlacementSettings, *, conditions: frozenset[str]
) -> None:
    """Set or clear the substitution rule matching the canonicalized conditions.

    An empty `glyph_name` removes the matching rule and keeps sibling rules. Conditions
    are canonicalized by the codepoint's category, so writes from contexts sharing one
    substitution slot address the same rule.
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
    """Enable a snap with its gap, or clear it entirely when disabled."""
    cs = settings.consonants.setdefault(cons_uni, ConsonantSettings())
    if not enabled:
        cs.snap_configs.pop(snap_name, None)
    else:
        cs.snap_configs[snap_name] = SnapConfig(enabled=True, gap=gap)


def current_base_offset(cons_uni: int, role: str, settings: PlacementSettings) -> Offset:
    """Return the base-offset delta for `role` on `cons_uni`, or `Offset(0, 0)`."""
    return settings.for_consonant(cons_uni).base_offsets.get(role, Offset())


def apply_base_offset(cons_uni: int, role: str, x: int, y: int, settings: PlacementSettings) -> None:
    """Commit a base-offset delta for `role`, clearing zero deltas."""
    cs = settings.consonants.setdefault(cons_uni, ConsonantSettings())
    if x == 0 and y == 0:
        cs.base_offsets.pop(role, None)
    else:
        cs.base_offsets[role] = Offset(x, y)


def group_composites_by_consonant(pua_map: dict[str, str]) -> dict[int, list[CompositeSpec]]:
    """Index composite specs by consonant, each list sorted ascending by PUA codepoint."""
    out: defaultdict[int, list[CompositeSpec]] = defaultdict(list)
    for spec in iter_composite_specs(pua_map):
        out[spec.cons_uni].append(spec)
    for specs in out.values():
        specs.sort(key=lambda s: s.pua_code)
    return dict(out)


def pua_specs_for_consonant(pua_map: dict[str, str], cons_uni: int) -> list[CompositeSpec]:
    """Return the ascending-`pua_code` sorted specs for `cons_uni` in `pua_map`."""
    return group_composites_by_consonant(pua_map).get(cons_uni, [])
