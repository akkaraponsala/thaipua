"""Placement settings: Pydantic schema with strict wire codec and explicit version errors."""

import re
from collections.abc import Callable, Container, Iterable
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    model_validator,
)

from thaipua.core.domain.errors import SettingsError
from thaipua.core.domain.thai import (
    ABOVE_VOWELS,
    BELOW_VOWELS,
    CONSONANT_PROTRUSION,
    THAI_CONSONANTS,
    TONE_MARKS,
)

SETTINGS_VERSION: int = 1
_CODEPOINT_RE: re.Pattern[str] = re.compile("^[Uu]\\+([0-9A-Fa-f]{1,6})$")
_COMBO_KEY_RE: re.Pattern[str] = re.compile("^(?:[Uu]\\+[0-9A-Fa-f]{1,6})(?:\\+[Uu]\\+[0-9A-Fa-f]{1,6})*$")
_COMBO_CODEPOINT_RE: re.Pattern[str] = re.compile("[Uu]\\+([0-9A-Fa-f]{1,6})")
_MAX_CODEPOINT: int = 0x10FFFF
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
ROLE_TO_MARK_CATEGORY: dict[str, frozenset[int]] = {
    ROLE_TONE_MARK: TONE_MARKS,
    ROLE_ABOVE_VOWEL: ABOVE_VOWELS,
    ROLE_BELOW_VOWEL: BELOW_VOWELS,
}
_MARK_CATEGORIES: frozenset[int] = TONE_MARKS | ABOVE_VOWELS | BELOW_VOWELS
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


class Offset(BaseModel):
    """An `(x, y)` placement delta in font design units."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    x: StrictInt = 0
    y: StrictInt = 0

    def __init__(self, x: int = 0, y: int = 0, **data: Any) -> None:
        """Build an offset positionally or by keyword, validating both ways."""
        super().__init__(x=x, y=y, **data)

    def __add__(self, other: Offset) -> Offset:
        """Sum two offsets component-wise."""
        return Offset(x=self.x + other.x, y=self.y + other.y)


_ZERO_OFFSET: Offset = Offset()


class SnapConfig(BaseModel):
    """Bounding-box snap configuration; `gap` adds extra spacing beyond the snapped position."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: StrictBool = False
    gap: StrictInt = 0


class Metadata(BaseModel):
    """Optional metadata describing the settings' target font."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    font_name: str | None = None
    family_name: str | None = None
    units_per_em: Annotated[StrictInt, Field(gt=0)] | None = None

    def _reject_blank_names(self) -> Metadata:
        """Reject blank names; an absent name is `None`, never an empty string."""
        for field in ("font_name", "family_name"):
            value = getattr(self, field)
            if value is not None and not value.strip():
                raise ValueError(f"metadata.{field} must be a non-empty string")
        return self

    @model_validator(mode="after")
    def _check_names(self) -> Metadata:
        """Validate metadata names after parsing."""
        return self._reject_blank_names()


def _parse_codepoint_key(key: Any) -> int:
    """Convert a `U+XXXX` string or plain integer to a codepoint; reject anything else."""
    if isinstance(key, bool):
        raise ValueError(f"not a codepoint: {key!r}")
    if isinstance(key, int):
        if 0 <= key <= _MAX_CODEPOINT:
            return key
        raise ValueError(f"codepoint out of range: {key!r}")
    if isinstance(key, str):
        match = _CODEPOINT_RE.match(key)
        if match is not None:
            cp = int(match.group(1), 16)
            if 0 <= cp <= _MAX_CODEPOINT:
                return cp
    raise ValueError(f"not a U+XXXX codepoint: {key!r}")


def _require_consonant(key: Any) -> int:
    """Parse a codepoint key, rejecting anything outside the Thai consonant set."""
    cp = _parse_codepoint_key(key)
    if cp not in THAI_CONSONANTS:
        raise ValueError(f"not a Thai consonant: U+{cp:04X}")
    return cp


_AnyCodepoint = Annotated[int, BeforeValidator(_parse_codepoint_key)]
_ConsonantCodepoint = Annotated[int, BeforeValidator(_require_consonant)]


def _check_roles(value: Any, *, allowed: Container[str], field: str) -> Any:
    """Reject mappings keyed by unknown roles; pass everything else through for value validation."""
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    for role in value:
        if role not in allowed:
            raise ValueError(f"unknown {field} role {role!r}")
    return value


def _validate_base_offsets(value: Any) -> Any:
    """Reject `base_offsets` objects keyed by unknown roles."""
    return _check_roles(value, allowed=BASE_OFFSET_ROLES, field="base_offsets")


def _validate_mark_groups(value: Any) -> Any:
    """Translate wire mark groups to roles, resolving every mark key strictly against its category."""
    if not isinstance(value, dict):
        raise ValueError("mark offsets must be an object")
    out: dict[str, Any] = {}
    for group, entries in value.items():
        role = MARK_GROUP_TO_ROLE.get(group)
        if role is None:
            if group not in ROLES:
                raise ValueError(f"unknown mark group {group!r}")
            role = group
        if not isinstance(entries, dict):
            raise ValueError(f"mark offsets[{group!r}] must be an object")
        category = ROLE_TO_MARK_CATEGORY[role]
        translated = {}
        for mark_key, offset in entries.items():
            cp = _parse_codepoint_key(mark_key)
            if cp not in category:
                raise ValueError(f"mark U+{cp:04X} is not in the {group!r} category")
            translated[cp] = offset
        out[role] = translated
    return out


def _parse_combo_key(key: Any) -> str:
    """Parse a wire `U+XXXX+U+YYYY` key or a Thai-mark char key into canonical char-key form."""
    cps: list[int] | None = None
    if isinstance(key, str):
        if _COMBO_KEY_RE.fullmatch(key) is not None:
            cps = [int(match.group(1), 16) for match in _COMBO_CODEPOINT_RE.finditer(key)]
        elif key and len(set(key)) == len(key):
            cps = [ord(ch) for ch in key]
    if cps is None:
        raise ValueError(f"not a U+XXXX(+U+XXXX...) combo key: {key!r}")
    if len(set(cps)) != len(cps):
        raise ValueError(f"combo key repeats a codepoint: {key!r}")
    if len(cps) < 2:
        raise ValueError(f"combo key needs at least two marks: {key!r}")
    for cp in cps:
        if cp not in _MARK_CATEGORIES:
            raise ValueError(f"combo member U+{cp:04X} is not a Thai mark")
    return "".join(chr(c) for c in sorted(cps))


def _validate_combo_offsets(value: Any) -> Any:
    """Normalize every combo key to canonical form, rejecting malformed keys and unknown roles."""
    if not isinstance(value, dict):
        raise ValueError("combo_offsets must be an object")
    out: dict[str, Any] = {}
    for combo_key, role_map in value.items():
        canonical = _parse_combo_key(combo_key)
        if not isinstance(role_map, dict):
            raise ValueError(f"combo_offsets[{combo_key!r}] must be an object")
        for role in role_map:
            if role not in ROLES:
                raise ValueError(f"unknown combo_offsets[{combo_key!r}] role {role!r}")
        out[canonical] = role_map
    return out


def _expand_snap(value: Any) -> Any:
    """Expand a boolean snap shorthand to its object form; pass models and objects through."""
    if isinstance(value, SnapConfig):
        return value
    if isinstance(value, bool):
        return {"enabled": value}
    return value


_SnapField = Annotated[SnapConfig, BeforeValidator(_expand_snap)]


def _validate_snap_configs(value: Any) -> Any:
    """Reject `snap_configs` objects keyed by unknown snap pairs."""
    return _check_roles(value, allowed=SNAPS, field="snap_configs")


def _validate_conditions(value: Any) -> Any:
    """Coerce a condition list to a frozenset, rejecting unknown roles and non-list shapes."""
    if isinstance(value, (frozenset, set, tuple, list)):
        roles = frozenset(value)
        for role in roles:
            if role not in SUB_CONDITIONS_ROLES:
                raise ValueError(f"unknown substitution condition role {role!r}")
        return roles
    raise ValueError(f"substitution conditions must be a list of roles, got {value!r}")


_ConditionsField = Annotated[frozenset[str], BeforeValidator(_validate_conditions)]


class SubstitutionRule(BaseModel):
    """Contextual glyph replacement active when its mark-role conditions are present; empty conditions always match."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    replacement: str = Field(min_length=1)
    conditions: _ConditionsField = frozenset()


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


class ConsonantSettings(BaseModel):
    """Per-consonant overrides for offsets, snaps, and glyph substitutions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_offsets: Annotated[dict[str, Offset], BeforeValidator(_validate_base_offsets)] = Field(default_factory=dict)
    mark_offsets: Annotated[dict[str, dict[int, Offset]], BeforeValidator(_validate_mark_groups)] = Field(
        default_factory=dict
    )
    combo_offsets: Annotated[dict[str, dict[str, Offset]], BeforeValidator(_validate_combo_offsets)] = Field(
        default_factory=dict
    )
    snap_configs: Annotated[dict[str, _SnapField], BeforeValidator(_validate_snap_configs)] = Field(
        default_factory=dict
    )
    glyph_substitutions: dict[_AnyCodepoint, list[SubstitutionRule]] = Field(default_factory=dict)

    def _canonical_substitutions(self) -> dict[int, list[SubstitutionRule]]:
        """Canonicalize every rule's conditions by its codepoint category, letting later duplicates win."""
        merged: dict[int, list[SubstitutionRule]] = {}
        for codepoint, rules in self.glyph_substitutions.items():
            canonicalize = context_canonicalizer(codepoint)
            by_conditions: dict[frozenset[str], SubstitutionRule] = {}
            for rule in rules:
                canonical = canonicalize(rule.conditions)
                by_conditions[canonical] = SubstitutionRule(replacement=rule.replacement, conditions=canonical)
            merged[codepoint] = list(by_conditions.values())
        return merged

    @model_validator(mode="after")
    def _check_rules(self) -> ConsonantSettings:
        """Canonicalize substitution conditions after parsing, assigning in place (validators must return `self`)."""
        object.__setattr__(self, "glyph_substitutions", self._canonical_substitutions())
        return self

    def snap_for(self, snap_name: str) -> SnapConfig | None:
        """Return the snap config for `snap_name`, or `None` when unset."""
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

    def with_base_offset(self, role: str, offset: Offset | None) -> ConsonantSettings:
        """Return a copy with `role`'s base offset set, removing the entry for zero deltas."""
        return self._with_section("base_offsets", role, offset if offset != _ZERO_OFFSET else None)

    def with_mark_offset(self, role: str, mark: int, offset: Offset | None) -> ConsonantSettings:
        """Return a copy with one per-mark offset set, pruning the role group when emptied."""
        return self._with_grouped("mark_offsets", role, mark, offset if offset != _ZERO_OFFSET else None)

    def with_combo_offset(self, combo_key: str, role: str, offset: Offset | None) -> ConsonantSettings:
        """Return a copy with one combo offset set, pruning the combo entry when emptied."""
        return self._with_grouped("combo_offsets", combo_key, role, offset if offset != _ZERO_OFFSET else None)

    def with_snap(self, name: str, snap: SnapConfig | None) -> ConsonantSettings:
        """Return a copy with `name`'s snap set; a missing or disabled snap removes the entry."""
        stored = snap if snap is not None and snap.enabled else None
        return self._with_section("snap_configs", name, stored)

    def with_rule(self, codepoint: int, conditions: frozenset[str], replacement: str | None) -> ConsonantSettings:
        """Return a copy with the rule for canonicalized `conditions` upserted or removed.

        An empty `replacement` removes the matching rule and prunes the codepoint entry
        when its last rule goes; sibling rules are kept.
        """
        canonical = context_canonicalizer(codepoint)(frozenset(conditions))
        rules = [rule for rule in self.glyph_substitutions.get(codepoint, []) if rule.conditions != canonical]
        if replacement:
            rules.append(SubstitutionRule(replacement=replacement, conditions=canonical))
        subs = dict(self.glyph_substitutions)
        if rules:
            subs[codepoint] = rules
        else:
            subs.pop(codepoint, None)
        return self.model_copy(update={"glyph_substitutions": subs})

    def _with_section(self, section: str, key: str, value: Offset | SnapConfig | None) -> ConsonantSettings:
        """Return a copy with `section[key]` set or removed."""
        current: dict[str, Any] = dict(getattr(self, section))
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
        return self.model_copy(update={section: current})

    def _with_grouped(self, section: str, outer: str, inner: Any, value: Offset | None) -> ConsonantSettings:
        """Return a copy with `section[outer][inner]` set, pruning `outer` when emptied."""
        grouped: dict[str, Any] = {key: dict(group) for key, group in getattr(self, section).items()}
        if value is None:
            group = grouped.get(outer)
            if group is not None:
                group.pop(inner, None)
                if group:
                    grouped[outer] = group
                else:
                    grouped.pop(outer, None)
        else:
            group = grouped.get(outer, {})
            group[inner] = value
            grouped[outer] = group
        return self.model_copy(update={section: grouped})


class ResolvedOffset(BaseModel):
    """Offset breakdown: per-glyph, font-global, and base tiers plus their total."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    per_glyph: Offset = Field(default_factory=Offset)
    global_offset: Offset = Field(default_factory=Offset)
    base: Offset = Field(default_factory=Offset)

    @property
    def total(self) -> Offset:
        """Return the summed vector actually applied to the component."""
        return self.per_glyph + self.global_offset + self.base


class PlacementSettings(BaseModel):
    """Root settings object holding font-global mark offsets and per-consonant overrides."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    metadata: Metadata = Field(default_factory=Metadata)
    marks: Annotated[dict[str, dict[int, Offset]], BeforeValidator(_validate_mark_groups)] = Field(default_factory=dict)
    consonants: dict[_ConsonantCodepoint, ConsonantSettings] = Field(default_factory=dict)

    def for_consonant(self, cons_uni: int) -> ConsonantSettings:
        """Return the per-consonant entry, or an empty default when unset."""
        return self.consonants.get(cons_uni, ConsonantSettings())

    def resolve(
        self,
        cons_uni: int,
        role: str,
        *,
        combo_key: str | None,
        mark_uni: int | None,
        base_role: str | None = None,
    ) -> ResolvedOffset:
        """Resolve one offset, keeping each tier inspectable instead of pre-summed."""
        entry = self.for_consonant(cons_uni)
        per_glyph = _per_glyph_tier(entry, role, mark_uni=mark_uni, combo_key=combo_key)
        global_offset = _ZERO_OFFSET
        if mark_uni is not None:
            global_offset = self.marks.get(role, {}).get(mark_uni, _ZERO_OFFSET)
        base_key = base_role if base_role is not None and base_role in entry.base_offsets else role
        return ResolvedOffset(
            per_glyph=per_glyph, global_offset=global_offset, base=entry.base_offsets.get(base_key, _ZERO_OFFSET)
        )

    def mark_offset_for(
        self, cons_uni: int, role: str, *, mark_uni: int | None, combo_key: str | None, base_role: str | None = None
    ) -> Offset:
        """Combine the per-consonant tier with the font-global mark offset and the base tier.

        The global `marks` entry applies to every composite carrying `mark_uni`,
        including multi-mark clusters resolved through the combo tier; the base tier
        falls back to `role` when `base_role` is unset.
        """
        return self.resolve(cons_uni, role, mark_uni=mark_uni, combo_key=combo_key, base_role=base_role).total

    def with_metadata(self, metadata: Metadata) -> PlacementSettings:
        """Return a copy stamped with `metadata`, leaving every other tier untouched."""
        return self.model_copy(update={"metadata": metadata})

    def with_global_mark(self, role: str, mark: int, offset: Offset | None) -> PlacementSettings:
        """Return a copy with one font-global mark offset set, pruning the role group when emptied."""
        grouped = {key: dict(group) for key, group in self.marks.items()}
        if offset is None or offset == _ZERO_OFFSET:
            group = grouped.get(role)
            if group is not None:
                group.pop(mark, None)
                if group:
                    grouped[role] = group
                else:
                    grouped.pop(role, None)
        else:
            group = grouped.get(role, {})
            group[mark] = offset
            grouped[role] = group
        return self.model_copy(update={"marks": grouped})

    def with_base_offset(self, cons_uni: int, role: str, offset: Offset | None) -> PlacementSettings:
        """Return a copy with one consonant base offset set."""
        return self._with_consonant(cons_uni, self.for_consonant(cons_uni).with_base_offset(role, offset))

    def with_mark_offset(self, cons_uni: int, role: str, mark: int, offset: Offset | None) -> PlacementSettings:
        """Return a copy with one consonant per-mark offset set."""
        return self._with_consonant(cons_uni, self.for_consonant(cons_uni).with_mark_offset(role, mark, offset))

    def with_combo_offset(self, cons_uni: int, combo_key: str, role: str, offset: Offset | None) -> PlacementSettings:
        """Return a copy with one consonant combo offset set."""
        return self._with_consonant(cons_uni, self.for_consonant(cons_uni).with_combo_offset(combo_key, role, offset))

    def with_snap(self, cons_uni: int, name: str, snap: SnapConfig | None) -> PlacementSettings:
        """Return a copy with one consonant snap set or removed."""
        return self._with_consonant(cons_uni, self.for_consonant(cons_uni).with_snap(name, snap))

    def with_rule(
        self, cons_uni: int, codepoint: int, conditions: frozenset[str], replacement: str | None
    ) -> PlacementSettings:
        """Return a copy with one consonant substitution rule upserted or removed."""
        return self._with_consonant(
            cons_uni, self.for_consonant(cons_uni).with_rule(codepoint, conditions, replacement)
        )

    def _with_consonant(self, cons_uni: int, entry: ConsonantSettings) -> PlacementSettings:
        """Return a copy with `cons_uni`'s entry replaced, keeping empty entries like direct mutation does."""
        consonants = dict(self.consonants)
        consonants[cons_uni] = entry
        return self.model_copy(update={"consonants": consonants})


def _per_glyph_tier(entry: ConsonantSettings, role: str, *, mark_uni: int | None, combo_key: str | None) -> Offset:
    """Apply the single tier rule: multi-mark clusters use `combo_offsets`, else `mark_offsets`."""
    if combo_key is not None:
        return entry.combo_offsets.get(combo_key, {}).get(role, _ZERO_OFFSET)
    if mark_uni is None:
        return _ZERO_OFFSET
    return entry.mark_offsets.get(role, {}).get(mark_uni, _ZERO_OFFSET)


def default_placement_settings() -> PlacementSettings:
    """Return fresh default settings at the current schema version."""
    return PlacementSettings()


def settings_from_dict(data: dict[str, Any]) -> PlacementSettings:
    """Parse a settings document, rejecting unsupported versions and malformed entries loudly."""
    if not isinstance(data, dict):
        raise SettingsError(f"settings document must be an object, got {type(data).__name__}")
    version = data.get("version", SETTINGS_VERSION)
    if version != SETTINGS_VERSION:
        raise SettingsError(f"unsupported settings version {version}; expected {SETTINGS_VERSION}")
    try:
        return PlacementSettings.model_validate(data)
    except ValidationError as exc:
        raise SettingsError(f"invalid settings document: {exc}") from exc


def settings_to_dict(settings: PlacementSettings) -> dict[str, Any]:
    """Serialize `settings` to a JSON-ready dictionary, omitting empty sections."""
    payload: dict[str, Any] = {"version": settings.version}
    md = _metadata_to_dict(settings.metadata)
    if md:
        payload["metadata"] = md
    marks_json = _mark_offsets_to_dict(settings.marks)
    if marks_json:
        payload["marks"] = marks_json
    consonants_json: dict[str, Any] = {}
    for cp, cset in sorted(settings.consonants.items()):
        body = _consonant_settings_to_dict(cset)
        if body:
            consonants_json[_format_codepoint(cp)] = body
    if consonants_json:
        payload["consonants"] = consonants_json
    return payload


def combo_key_from_codepoints(cps: Iterable[int]) -> str | None:
    """Join sorted codepoints into the canonical combination key; return `None` when empty."""
    key = "".join(chr(c) for c in sorted(cps))
    return key if key else None


def combo_key_for_marks(below_uni: int | None, above_uni: int | None, tone_uni: int | None) -> str | None:
    """Return the canonical combination key for a multi-mark cluster, else `None`.

    This is the single home of the tier rule: one mark resolves through
    `mark_offsets`, while two or more resolve through `combo_offsets`.
    """
    cps = [c for c in [below_uni, above_uni, tone_uni] if c]
    if len(cps) < 2:
        return None
    return combo_key_from_codepoints(cps)


def _format_codepoint(cp: int) -> str:
    """Format a codepoint in canonical `U+XXXX` notation."""
    return f"U+{cp:04X}"


def _format_combo_key(combo_key: str) -> str:
    """Format the in-memory char key as a `U+XXXX+U+YYYY` string."""
    return "+".join(_format_codepoint(ord(ch)) for ch in combo_key)


def _metadata_to_dict(md: Metadata) -> dict[str, Any]:
    """Serialize metadata, omitting unset names."""
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
    """Serialize base offsets in canonical role order, omitting zero deltas."""
    out: dict[str, dict[str, int]] = {}
    for role in BASE_OFFSET_ROLES:
        off = base_offsets.get(role, Offset())
        if off == _ZERO_OFFSET:
            continue
        out[role] = {"x": off.x, "y": off.y}
    return out


def _mark_offsets_to_dict(mark_offsets: dict[str, dict[int, Offset]]) -> dict[str, dict[str, dict[str, int]]]:
    """Serialize per-mark offsets under wire group names, omitting zero deltas."""
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
    """Serialize snaps in canonical order, collapsing zero-gap configs to booleans."""
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
