"""Validate PUA mappings structurally and against live font slots without mutating anything."""

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
    """Severity of one validation issue; `ERROR` blocks a usable install."""

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
    """Snapshot of a font's cmap and glyf facts for slot classification."""

    cmap: dict[int, str]
    glyf: Any | None


def slot_context_from_font(font: TTFont) -> PuaSlotContext:
    """Snapshot `font`'s `cmap` and `glyf` table into a classification context."""
    return PuaSlotContext(cmap=font.getBestCmap(), glyf=font.get("glyf"))


def validate_pua_map(mapping: Mapping[str, str], context: PuaSlotContext | None) -> list[PuaMapIssue]:
    """Validate every mapping entry and return issues only; a clean map yields an empty list.

    Duplicate-value errors are reported once per involved key in a second pass.
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
    """Interpret editor input as a single-character value, accepting literal characters, bare hex, or `U+XXXX`.

    Out-of-range codepoints pass through; the validator flags them instead.
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
