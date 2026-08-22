"""Placement, snap, and glyph-substitution settings with JSON load/save support."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, overload

from thaipua.core.fonttools.specs import ABOVE_VOWELS, BELOW_VOWELS, CONSONANT_PROTRUSION, THAI_CONSONANTS, TONE_MARKS

logger = logging.getLogger(__name__)

SETTINGS_VERSION: int = 1
_CODEPOINT_RE: re.Pattern[str] = re.compile("^[Uu]\\+([0-9A-Fa-f]{1,6})$")
_COMBO_CODEPOINT_RE: re.Pattern[str] = re.compile("[Uu]\\+([0-9A-Fa-f]{1,6})")
_COMBO_KEY_RE: re.Pattern[str] = re.compile("^(?:[Uu]\\+[0-9A-Fa-f]{1,6})(?:\\+[Uu]\\+[0-9A-Fa-f]{1,6})*$")
_MAX_CODEPOINT: int = 1114111
ROLE_TONE_MARK: str = "tone_mark"
ROLE_ABOVE_VOWEL: str = "above_vowel"
ROLE_BELOW_VOWEL: str = "below_vowel"
ROLES: tuple[str, ...] = (ROLE_TONE_MARK, ROLE_ABOVE_VOWEL, ROLE_BELOW_VOWEL)
ROLE_TONE_MARK_ON_ABOVE_VOWEL: str = "tone_mark_on_above_vowel"
BASE_OFFSET_ROLES: tuple[str, ...] = (ROLE_TONE_MARK, ROLE_TONE_MARK_ON_ABOVE_VOWEL, ROLE_ABOVE_VOWEL, ROLE_BELOW_VOWEL)
MARK_GROUP_TO_ROLE: dict[str, str] = {
    "tone_marks": ROLE_TONE_MARK,
    "above_vowels": ROLE_ABOVE_VOWEL,
    "below_vowels": ROLE_BELOW_VOWEL,
}
ROLE_TO_MARK_GROUP: dict[str, str] = {v: k for k, v in MARK_GROUP_TO_ROLE.items()}
ROLE_TO_MARK_CATEGORY: dict[str, set[int]] = {
    ROLE_TONE_MARK: TONE_MARKS,
    ROLE_ABOVE_VOWEL: ABOVE_VOWELS,
    ROLE_BELOW_VOWEL: BELOW_VOWELS,
}
SUB_CONSONANT: str = "consonant"
SUB_TONE_MARK: str = "tone_mark"
SUB_ABOVE_VOWEL: str = "above_vowel"
SUB_BELOW_VOWEL: str = "below_vowel"
GLYPH_SUBSTITUTION_ROLES: tuple[str, ...] = (SUB_CONSONANT, SUB_TONE_MARK, SUB_ABOVE_VOWEL, SUB_BELOW_VOWEL)
SUB_CONDITIONS_ROLES: tuple[str, ...] = (SUB_TONE_MARK, SUB_ABOVE_VOWEL, SUB_BELOW_VOWEL)
SNAP_TONE_TO_ABOVE: str = "tone_mark_to_above_vowel"
SNAP_ABOVE_TO_CONS: str = "above_vowel_to_consonant"
SNAP_BELOW_TO_CONS: str = "below_vowel_to_consonant"
SNAPS: tuple[str, ...] = (SNAP_TONE_TO_ABOVE, SNAP_ABOVE_TO_CONS, SNAP_BELOW_TO_CONS)


@dataclass(slots=True, frozen=True)
class Offset:
    """An `(x, y)` placement delta in font design units."""

    x: int = 0
    y: int = 0

    def __add__(self, other: Offset) -> Offset:
        return Offset(self.x + other.x, self.y + other.y)


_ZERO_OFFSET: Offset = Offset()


@dataclass(slots=True, frozen=True)
class SnapConfig:
    """Bounding-box snap configuration; `gap` adds extra spacing beyond the snapped position."""

    enabled: bool
    gap: int = 0


@dataclass(slots=True, frozen=True)
class Metadata:
    """Optional metadata describing the settings' target font."""

    font_name: str | None = None
    family_name: str | None = None
    units_per_em: int | None = None


@dataclass(slots=True, frozen=True)
class SubstitutionRule:
    """Contextual glyph replacement active when its mark-role conditions are present; empty conditions always match."""

    replacement: str
    conditions: frozenset[str] = frozenset()


@dataclass(slots=True, frozen=True)
class ConsonantSettings:
    """Per-consonant overrides for offsets, snaps, and glyph substitutions."""

    base_offsets: dict[str, Offset] = field(default_factory=dict)
    mark_offsets: dict[str, dict[int, Offset]] = field(default_factory=dict)
    combo_offsets: dict[str, dict[str, Offset]] = field(default_factory=dict)
    snap_configs: dict[str, SnapConfig] = field(default_factory=dict)
    glyph_substitutions: dict[int, list[SubstitutionRule]] = field(default_factory=dict)

    def offset_for(
        self, role: str, *, mark_uni: int | None, combo_key: str | None, base_role: str | None = None
    ) -> Offset:
        """Combine the per-glyph override with the base offset for `role`.

        Multi-mark clusters read the combo tier; single-mark clusters read the mark
        tier. `base_role` substitutes the base tier when provided.
        """
        specific = self._per_glyph_offset(role, mark_uni=mark_uni, combo_key=combo_key)
        base_key = base_role if base_role is not None and base_role in self.base_offsets else role
        return specific + self.base_offsets.get(base_key, Offset())

    def _per_glyph_offset(self, role: str, *, mark_uni: int | None, combo_key: str | None) -> Offset:
        """Return the per-glyph tier for `role`: the combo tier for multi-mark clusters, otherwise the mark tier."""
        if combo_key is not None:
            combo = self.combo_offsets.get(combo_key)
            if combo is None:
                return _ZERO_OFFSET
            return combo.get(role) or _ZERO_OFFSET
        if mark_uni is None:
            return _ZERO_OFFSET
        group = self.mark_offsets.get(role)
        if group is None:
            return _ZERO_OFFSET
        return group.get(mark_uni) or _ZERO_OFFSET

    def snap_for(self, snap_name: str) -> SnapConfig | None:
        return self.snap_configs.get(snap_name)

    def substitution_for(self, codepoint: int, *, present_roles: frozenset[str]) -> str | None:
        """Return the replacement glyph of the most specific matching rule for `codepoint`.

        Both sides are canonicalized by the codepoint's category before matching; ties
        are broken by list order. Return `None` when no rule matches.
        """
        rules = self.glyph_substitutions.get(codepoint)
        if not rules:
            return None
        canonicalize = context_canonicalizer(codepoint)
        ctx = canonicalize(present_roles)
        best = None
        best_len = -1
        for rule in rules:
            cond = canonicalize(rule.conditions)
            if cond.issubset(ctx):
                cond_len = len(cond)
                if cond_len > best_len:
                    best = rule
                    best_len = cond_len
        return best.replacement if best is not None else None


@dataclass(slots=True, frozen=True)
class PlacementSettings:
    """Root settings object mapping consonant codepoints to their overrides."""

    version: int = SETTINGS_VERSION
    metadata: Metadata = field(default_factory=Metadata)
    consonants: dict[int, ConsonantSettings] = field(default_factory=dict)

    def for_consonant(self, cons_uni: int) -> ConsonantSettings:
        return self.consonants.get(cons_uni, ConsonantSettings())


def default_placement_settings() -> PlacementSettings:
    return PlacementSettings(version=SETTINGS_VERSION, metadata=Metadata(), consonants={})


def load_placement_settings(path: str | Path) -> PlacementSettings:
    """Load settings from a JSON file, falling back to defaults on unreadable or invalid content."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Cannot read settings file %s: %s; using defaults", p, exc)
        return default_placement_settings()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid JSON in %s: %s; using defaults", p, exc)
        return default_placement_settings()
    if not isinstance(data, dict):
        logger.warning("Top-level settings JSON in %s is not an object; using defaults", p)
        return default_placement_settings()
    return _build_from_dict(data)


def save_placement_settings(settings: PlacementSettings, path: str | Path) -> None:
    """Write `settings` to `path` as JSON, emitting codepoints in `U+XXXX` notation and omitting empty entries."""
    payload = settings_to_dict(settings)
    p = Path(path)
    with p.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=4)
    logger.info("Settings saved: %s", p)


def settings_to_dict(settings: PlacementSettings) -> dict[str, Any]:
    """Serialize `settings` to a JSON-ready dictionary, omitting empty sections."""
    payload: dict[str, Any] = {"version": settings.version}
    md = _metadata_to_dict(settings.metadata)
    if md:
        payload["metadata"] = md
    consonants_json: dict[str, Any] = {}
    for cp, cset in sorted(settings.consonants.items()):
        body = _consonant_settings_to_dict(cset)
        if body:
            consonants_json[_format_codepoint(cp)] = body
    if consonants_json:
        payload["consonants"] = consonants_json
    return payload


def _build_from_dict(data: dict[str, Any]) -> PlacementSettings:
    """Parse a JSON object into settings; return defaults for unsupported schema versions."""
    raw_version = _coerce_int(data.get("version"), SETTINGS_VERSION)
    if raw_version != SETTINGS_VERSION:
        logger.warning("Unsupported settings version %d; using defaults", raw_version)
        return default_placement_settings()
    return PlacementSettings(
        version=SETTINGS_VERSION,
        metadata=_build_metadata(data.get("metadata")),
        consonants=_build_consonants(data.get("consonants")),
    )


def _build_metadata(raw: Any) -> Metadata:
    """Parse optional metadata, ignoring blank names and non-positive `units_per_em` values."""
    if not isinstance(raw, dict):
        if raw is not None:
            logger.warning("metadata is not an object; ignoring metadata")
        return Metadata()
    units_per_em = _coerce_int(raw.get("units_per_em"), None)
    if units_per_em is not None and units_per_em <= 0:
        logger.warning("metadata.units_per_em must be positive; ignoring")
        units_per_em = None
    return Metadata(
        font_name=_coerce_str(raw.get("font_name")) or None,
        family_name=_coerce_str(raw.get("family_name")) or None,
        units_per_em=units_per_em,
    )


def _build_consonants(raw: Any) -> dict[int, ConsonantSettings]:
    """Parse the `consonants` map, skipping invalid keys, non-consonant codepoints, and non-object entries."""
    if not isinstance(raw, dict):
        if raw is not None:
            logger.warning("consonants is not an object; ignoring overrides")
        return {}
    out: dict[int, ConsonantSettings] = {}
    for key, value in raw.items():
        cp = _parse_codepoint(key)
        if cp is None:
            logger.warning("Skipping consonant key %r: not a valid U+XXXX codepoint", key)
            continue
        if cp not in THAI_CONSONANTS:
            logger.warning("consonants[%s] is not a Thai consonant; skipping", key)
            continue
        if not isinstance(value, dict):
            logger.warning("consonants[%s] is not an object; skipping", key)
            continue
        out[cp] = _build_consonant_settings(value)
    return out


def _build_consonant_settings(raw: dict[str, Any]) -> ConsonantSettings:
    return ConsonantSettings(
        base_offsets=_build_base_offsets(raw.get("base_offsets")),
        mark_offsets=_build_mark_offsets(raw.get("mark_offsets")),
        combo_offsets=_build_combo_offsets(raw.get("combo_offsets")),
        snap_configs=_build_snap_configs(raw.get("snap_configs")),
        glyph_substitutions=_build_glyph_substitutions(raw.get("glyph_substitutions")),
    )


def _build_base_offsets(raw: Any) -> dict[str, Offset]:
    out: dict[str, Offset] = {}
    if not isinstance(raw, dict):
        if raw is not None:
            logger.warning("base_offsets is not an object; ignoring")
        return out
    for role, value in raw.items():
        if role not in BASE_OFFSET_ROLES:
            logger.warning("Skipping base_offsets role %r: unknown role", role)
            continue
        off = _parse_offset(value)
        if off is None:
            logger.warning("base_offsets[%s] is not a {x, y} object; skipping", role)
            continue
        out[role] = off
    return out


def _build_mark_offsets(raw: Any) -> dict[str, dict[int, Offset]]:
    """Parse grouped per-mark offsets, validating each mark against its group's category."""
    out: dict[str, dict[int, Offset]] = {}
    if not isinstance(raw, dict):
        if raw is not None:
            logger.warning("mark_offsets is not an object; ignoring")
        return out
    for group, sub_raw in raw.items():
        role = MARK_GROUP_TO_ROLE.get(group)
        if role is None:
            logger.warning("Skipping mark_offsets group %r: unknown group", group)
            continue
        if not isinstance(sub_raw, dict):
            logger.warning("mark_offsets[%s] is not an object; skipping", group)
            continue
        category = ROLE_TO_MARK_CATEGORY[role]
        role_map = {}
        for mark_cp_str, value in sub_raw.items():
            cp = _parse_codepoint(mark_cp_str)
            if cp is None:
                logger.warning("Skipping mark_offsets[%s] key %r: not a valid U+XXXX codepoint", group, mark_cp_str)
                continue
            if cp not in category:
                logger.warning("Skipping mark_offsets[%s] key %r: not in the group's category", group, mark_cp_str)
                continue
            off = _parse_offset(value)
            if off is None:
                logger.warning("mark_offsets[%s][%s] is not a {x, y} object; skipping", group, mark_cp_str)
                continue
            role_map[cp] = off
        if role_map:
            out[role] = role_map
    return out


def _build_combo_offsets(raw: Any) -> dict[str, dict[str, Offset]]:
    """Parse multi-mark combination offsets into canonical ascending-key form."""
    out: dict[str, dict[str, Offset]] = {}
    if not isinstance(raw, dict):
        if raw is not None:
            logger.warning("combo_offsets is not an object; ignoring")
        return out
    for combo_key, value in raw.items():
        canonical = _parse_combo_key(combo_key)
        if canonical is None:
            logger.warning(
                "Skipping combo_offsets key %r: not a U+XXXX(+U+XXXX...) key or repeats a codepoint", combo_key
            )
            continue
        if not isinstance(value, dict):
            logger.warning("combo_offsets[%r] is not an object; skipping", combo_key)
            continue
        role_map = {}
        for role, sub_value in value.items():
            if role not in ROLES:
                logger.warning("Skipping combo_offsets[%r] role %r: unknown role", combo_key, role)
                continue
            off = _parse_offset(sub_value)
            if off is None:
                logger.warning("combo_offsets[%r][%r] is not a {x, y} object; skipping", combo_key, role)
                continue
            role_map[role] = off
        if role_map:
            out[canonical] = role_map
    return out


def _build_glyph_substitutions(raw: Any) -> dict[int, list[SubstitutionRule]]:
    """Parse per-codepoint substitution rules, skipping invalid keys and malformed rules."""
    out: dict[int, list[SubstitutionRule]] = {}
    if not isinstance(raw, dict):
        if raw is not None:
            logger.warning("glyph_substitutions is not an object; ignoring")
        return out
    for cp_str, value in raw.items():
        cp = _parse_codepoint(cp_str)
        if cp is None:
            logger.warning("Skipping glyph_substitutions key %r: not a valid U+XXXX codepoint", cp_str)
            continue
        rules = _build_replacement_rules(value, cp_str, codepoint=cp)
        if rules:
            out[cp] = rules
    return out


def _build_replacement_rules(value: Any, cp_str: str, *, codepoint: int) -> list[SubstitutionRule]:
    """Build a rule list from a single rule object or a list; later rules replace earlier duplicates."""
    if isinstance(value, dict):
        rule = _build_replacement_rule(value, cp_str, codepoint=codepoint)
        return [rule] if rule is not None else []
    if isinstance(value, list):
        rules: dict[frozenset[str], SubstitutionRule] = {}
        for item in value:
            if not isinstance(item, dict):
                logger.warning("glyph_substitutions[%s] list item is not an object; skipping", cp_str)
                continue
            rule = _build_replacement_rule(item, cp_str, codepoint=codepoint)
            if rule is not None:
                if rule.conditions in rules:
                    logger.warning(
                        "glyph_substitutions[%s] rule for conditions %r duplicates an earlier rule; later rule wins",
                        cp_str,
                        sorted(rule.conditions),
                    )
                rules[rule.conditions] = rule
        return list(rules.values())
    logger.warning("glyph_substitutions[%s] is not an object or a list of objects; skipping", cp_str)
    return []


def canonicalize_substitution_context(roles: frozenset[str]) -> frozenset[str]:
    """Drop the tone-mark role within vowel families so related contexts match one rule.

    A rule authored at `consonant + below_vowel` and one at
    `consonant + below_vowel + tone_mark` address the same slot; a tone-only cluster
    keeps `tone_mark` as its own family.
    """
    if SUB_TONE_MARK in roles and (SUB_ABOVE_VOWEL in roles or SUB_BELOW_VOWEL in roles):
        return roles - {SUB_TONE_MARK}
    return roles


def canonicalize_tone_mark_context(roles: frozenset[str]) -> frozenset[str]:
    """Merge below-vowel contexts into tone-only contexts for a tone-mark codepoint.

    A below vowel never moves the tone mark, so tone rules authored with and without
    one are interchangeable; above-vowel contexts stay distinct.
    """
    roles = canonicalize_substitution_context(roles)
    if not roles or SUB_ABOVE_VOWEL in roles:
        return roles
    return (roles - {SUB_BELOW_VOWEL}) | {SUB_TONE_MARK}


def canonicalize_consonant_context(roles: frozenset[str], *, protrusion: str | None) -> frozenset[str]:
    """Canonicalize contexts for a consonant self-substitution according to its protrusion.

    Ascender-protruding consonants (e.g. ฬ) collapse every above-stack context into
    `{above_vowel, tone_mark}`; all others apply the generic vowel-family
    canonicalization.
    """
    if protrusion == "ascender":
        if SUB_ABOVE_VOWEL in roles or SUB_TONE_MARK in roles:
            return frozenset({SUB_ABOVE_VOWEL, SUB_TONE_MARK})
        return roles
    return canonicalize_substitution_context(roles)


def context_canonicalizer(codepoint: int) -> Callable[[frozenset[str]], frozenset[str]]:
    """Select the context canonicalizer matching `codepoint`'s character category."""
    if codepoint in TONE_MARKS:
        return canonicalize_tone_mark_context
    if codepoint in THAI_CONSONANTS:
        protrusion = CONSONANT_PROTRUSION.get(codepoint)
        return lambda roles: canonicalize_consonant_context(roles, protrusion=protrusion)
    return canonicalize_substitution_context


def _build_replacement_rule(item: dict[str, Any], cp_str: str, *, codepoint: int) -> SubstitutionRule | None:
    """Build one rule from a JSON object, dropping unknown condition roles and empty replacements."""
    replacement = _coerce_str(item.get("replacement"))
    if not replacement:
        logger.warning("glyph_substitutions[%s] rule has no non-empty `replacement`; skipping", cp_str)
        return None
    raw_conditions = item.get("conditions")
    condition_roles: set[str] = set()
    if raw_conditions is not None:
        if not isinstance(raw_conditions, list):
            logger.warning("glyph_substitutions[%s] rule has non-list `conditions`; using empty (always)", cp_str)
        else:
            for r in raw_conditions:
                if isinstance(r, str) and r in SUB_CONDITIONS_ROLES:
                    condition_roles.add(r)
                elif isinstance(r, str):
                    logger.warning(
                        "glyph_substitutions[%s] rule has unknown `conditions` role %r; skipping role",
                        cp_str,
                        r,
                    )
    canonical = context_canonicalizer(codepoint)
    return SubstitutionRule(replacement=replacement, conditions=canonical(frozenset(condition_roles)))


def _build_snap_configs(raw: Any) -> dict[str, SnapConfig]:
    out: dict[str, SnapConfig] = {}
    if not isinstance(raw, dict):
        if raw is not None:
            logger.warning("snap_configs is not an object; ignoring")
        return out
    for name, value in raw.items():
        if name not in SNAPS:
            logger.warning("Skipping snap_configs key %r: unknown snap pair", name)
            continue
        snap = _parse_snap(value)
        if snap is None:
            logger.warning("snap_configs[%r] is not a boolean or {enabled, gap} object; skipping", name)
            continue
        out[name] = snap
    return out


def _parse_offset(raw: Any) -> Offset | None:
    if not isinstance(raw, dict):
        return None
    return Offset(x=_coerce_int(raw.get("x"), 0), y=_coerce_int(raw.get("y"), 0))


def _parse_snap(raw: Any) -> SnapConfig | None:
    if isinstance(raw, bool):
        return SnapConfig(enabled=raw)
    if not isinstance(raw, dict):
        return None
    enabled = _coerce_bool(raw.get("enabled"))
    if enabled is None:
        return None
    return SnapConfig(enabled=enabled, gap=_coerce_int(raw.get("gap"), 0))


def _metadata_to_dict(md: Metadata) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if md.font_name is not None:
        out["font_name"] = md.font_name
    if md.family_name is not None:
        out["family_name"] = md.family_name
    if md.units_per_em is not None:
        out["units_per_em"] = md.units_per_em
    return out


def _consonant_settings_to_dict(cset: ConsonantSettings) -> dict[str, Any]:
    """Serialize one consonant entry, omitting empty sections."""
    body: dict[str, Any] = {}
    base_offsets = _base_offsets_to_dict(cset.base_offsets)
    if base_offsets:
        body["base_offsets"] = base_offsets
    mark_offsets = _mark_offsets_to_dict(cset.mark_offsets)
    if mark_offsets:
        body["mark_offsets"] = mark_offsets
    combo_offsets = _combo_offsets_to_dict(cset.combo_offsets)
    if combo_offsets:
        body["combo_offsets"] = combo_offsets
    snap_configs = _snap_configs_to_dict(cset.snap_configs)
    if snap_configs:
        body["snap_configs"] = snap_configs
    subs = _glyph_substitutions_to_dict(cset.glyph_substitutions)
    if subs:
        body["glyph_substitutions"] = subs
    return body


def _base_offsets_to_dict(base_offsets: dict[str, Offset]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for role in BASE_OFFSET_ROLES:
        off = base_offsets.get(role, Offset())
        if off == _ZERO_OFFSET:
            continue
        out[role] = {"x": off.x, "y": off.y}
    return out


def _mark_offsets_to_dict(mark_offsets: dict[str, dict[int, Offset]]) -> dict[str, dict[str, dict[str, int]]]:
    out: dict[str, dict[str, dict[str, int]]] = {}
    for role in ROLES:
        group = mark_offsets.get(role)
        if not group:
            continue
        sub = {}
        for cp in sorted(group):
            off = group[cp]
            if off == _ZERO_OFFSET:
                continue
            sub[_format_codepoint(cp)] = {"x": off.x, "y": off.y}
        if sub:
            out[ROLE_TO_MARK_GROUP[role]] = sub
    return out


def _combo_offsets_to_dict(combo_offsets: dict[str, dict[str, Offset]]) -> dict[str, dict[str, dict[str, int]]]:
    """Serialize combination offsets sorted by key, omitting zero deltas."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for combo_key in sorted(combo_offsets):
        role_map = combo_offsets[combo_key]
        sub = {}
        for role in ROLES:
            off = role_map.get(role)
            if off is None or off == _ZERO_OFFSET:
                continue
            sub[role] = {"x": off.x, "y": off.y}
        if sub:
            out[_format_combo_key(combo_key)] = sub
    return out


def _glyph_substitutions_to_dict(subs: dict[int, list[SubstitutionRule]]) -> dict[str, list[dict[str, Any]]]:
    """Serialize substitutions sorted by codepoint with canonicalized, sorted conditions."""
    out: dict[str, list[dict[str, Any]]] = {}
    for cp in sorted(subs):
        rules = subs[cp]
        if not rules:
            continue
        canonical = context_canonicalizer(cp)
        out[_format_codepoint(cp)] = [_replacement_rule_to_dict(rule, canonical(rule.conditions)) for rule in rules]
    return out


def _replacement_rule_to_dict(rule: SubstitutionRule, conditions: frozenset[str]) -> dict[str, Any]:
    """Serialize one rule, omitting `conditions` when empty."""
    item: dict[str, Any] = {"replacement": rule.replacement}
    if conditions:
        item["conditions"] = sorted(conditions)
    return item


def _snap_configs_to_dict(snap_configs: dict[str, SnapConfig]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in SNAPS:
        snap = snap_configs.get(name)
        if snap is None:
            continue
        if snap.gap == 0:
            out[name] = snap.enabled
        else:
            out[name] = {"enabled": snap.enabled, "gap": snap.gap}
    return out


def _format_codepoint(cp: int) -> str:
    return f"U+{cp:04X}"


def _parse_codepoint(key: Any) -> int | None:
    """Convert a `U+XXXX` string to an integer codepoint; return `None` for any other shape."""
    if not isinstance(key, str):
        return None
    match = _CODEPOINT_RE.match(key)
    if match is None:
        return None
    cp = int(match.group(1), 16)
    if cp < 0 or cp > _MAX_CODEPOINT:
        return None
    return cp


def _format_combo_key(combo_key: str) -> str:
    """Format the in-memory char key as a `U+XXXX+U+YYYY` string."""
    return "+".join(_format_codepoint(ord(ch)) for ch in combo_key)


def combo_key_from_codepoints(cps: Iterable[int]) -> str | None:
    """Join sorted codepoints into the canonical combination key; return `None` when empty."""
    key = "".join(chr(c) for c in sorted(cps))
    return key if key else None


def _parse_combo_key(key: Any) -> str | None:
    """Parse a `U+XXXX+U+YYYY` key into canonical char-key form; reject repeats and stray segments."""
    if not isinstance(key, str):
        return None
    if _COMBO_KEY_RE.fullmatch(key) is None:
        return None
    cps = []
    for match in _COMBO_CODEPOINT_RE.finditer(key):
        cp = int(match.group(1), 16)
        if 0 <= cp <= _MAX_CODEPOINT:
            cps.append(cp)
    if len(set(cps)) != len(cps):
        return None
    return combo_key_from_codepoints(cps)


@overload
def _coerce_int(value: Any, default: int) -> int: ...


@overload
def _coerce_int(value: Any, default: None) -> int | None: ...


def _coerce_int(value: Any, default: int | None) -> int | None:
    """Coerce `value` to `int`, rejecting fractional floats; return `default` when unconvertible."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            return default
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _coerce_str(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return None
