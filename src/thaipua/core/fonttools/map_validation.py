"""Static PUA-map validation: structural and font-aware slot checks, never mutating.

`validate_pua_map` is the single source of truth for the mapping editor's per-entry
status badges. It never rewrites the map — collisions surface as issues for the user
to resolve by editing entries (or picking a different codepoint range), matching the
static-map philosophy where allocation is a user decision.

Two check tiers:

- structural (font-free): value must be one character inside the PUA range, the Thai
  key must decompose into consonant + known marks (`decompose_thai_cluster`, which also
  rejects SARA AM U+0E33), and no two keys may share a PUA value;
- slot-aware (needs a `PuaSlotContext` snapshot): the occupant of the target codepoint
  is classified via `classify_pua_slot` — LOCKED occupants are an ERROR (the install
  would skip and the glyph would be missing at runtime), foreign composites a WARNING.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from thaipua.core.constants import PUA_RANGE_END, PUA_RANGE_START
from thaipua.core.fonttools.ownership import SlotOwnership, classify_pua_slot
from thaipua.core.fonttools.specs import decompose_thai_cluster

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from fontTools.ttLib import TTFont


class IssueSeverity(Enum):
    """Severity of one validation issue; ERROR blocks a usable install."""

    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True, frozen=True)
class PuaMapIssue:
    """One problem found in a mapping entry, reported to the editor UI."""

    thai_key: str
    severity: IssueSeverity
    message: str


@dataclass(slots=True)
class PuaSlotContext:
    """Plain-data snapshot of a font's cmap/glyf facts for slot classification.

    Built once per editor session from the live font so repeated revalidation while
    the user edits entries never re-walks `getBestCmap`. `glyf` is the raw glyf table
    (or `None` for CFF fonts); it satisfies `classify_pua_slot`'s structural protocol
    directly.
    """

    cmap: dict[int, str]
    glyf: Any | None


def slot_context_from_font(font: TTFont) -> PuaSlotContext:
    """Snapshot `font`'s cmap and glyf table into a classification context."""
    return PuaSlotContext(cmap=font.getBestCmap(), glyf=font.get("glyf"))


def validate_pua_map(mapping: Mapping[str, str], context: PuaSlotContext | None) -> list[PuaMapIssue]:
    """Validate every entry of `mapping`; returns issues only (a clean map yields `[]`).

    Entries are checked in mapping order; duplicate-value errors are appended in a
    second pass so every involved key receives one.
    """
    issues: list[PuaMapIssue] = []
    value_owners: dict[str, list[str]] = {}
    for thai_key, pua_char in mapping.items():
        if len(pua_char) != 1:
            issues.append(
                PuaMapIssue(thai_key, IssueSeverity.ERROR, f"PUA value {pua_char!r} is not a single character")
            )
            continue
        if not (PUA_RANGE_START <= ord(pua_char) <= PUA_RANGE_END):
            issues.append(PuaMapIssue(thai_key, IssueSeverity.ERROR, f"U+{ord(pua_char):04X} is outside the PUA range"))
            continue
        value_owners.setdefault(pua_char, []).append(thai_key)
        if decompose_thai_cluster(thai_key) is None:
            issues.append(
                PuaMapIssue(
                    thai_key,
                    IssueSeverity.ERROR,
                    "key does not decompose into consonant + vowel/tone marks",
                )
            )
        _slot_issues(thai_key, pua_char, context, issues)
    for pua_char, keys in value_owners.items():
        if len(keys) < 2:
            continue
        others = ", ".join(sorted(key for key in keys))
        for key in keys:
            issues.append(
                PuaMapIssue(key, IssueSeverity.ERROR, f"U+{ord(pua_char):04X} shared by multiple keys ({others})")
            )
    return issues


def parse_codepoint(text: str) -> str | None:
    """Parse editor input into a single-character value, or `None` when unparseable.

    Accepts a literal character (a PUA char pasted directly), bare hex (`E0A3`), or
    prefixed hex (`U+E0A3`, `0xE0A3`). Out-of-range codepoints are returned as-is; the
    validator flags them with an ERROR rather than rejecting the entry outright.
    """
    stripped = text.strip()
    if not stripped:
        return None
    if len(stripped) == 1:
        return stripped
    hex_part = stripped.lower().removeprefix("u+").removeprefix("0x")
    try:
        codepoint = int(hex_part, 16)
    except ValueError:
        return None
    return chr(codepoint)


def _slot_issues(thai_key: str, pua_char: str, context: PuaSlotContext | None, out: list[PuaMapIssue]) -> None:
    """Append the font-aware slot verdict for one entry when a context is available."""
    if context is None:
        return
    ownership = classify_pua_slot(context.cmap.get(ord(pua_char)), context.glyf)
    if ownership is SlotOwnership.LOCKED:
        out.append(
            PuaMapIssue(
                thai_key,
                IssueSeverity.ERROR,
                f"U+{ord(pua_char):04X} maps to a locked glyph; installing here would be skipped",
            )
        )
    elif ownership is SlotOwnership.REPLACEABLE:
        out.append(
            PuaMapIssue(
                thai_key,
                IssueSeverity.WARNING,
                f"U+{ord(pua_char):04X} maps to a foreign composite that would be replaced",
            )
        )


__all__ = [
    "IssueSeverity",
    "PuaMapIssue",
    "PuaSlotContext",
    "parse_codepoint",
    "slot_context_from_font",
    "validate_pua_map",
]
