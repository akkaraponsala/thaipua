"""Deterministic Thai-cluster-to-PUA layout: canonical assignment, deltas, storage, and conflict detection."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thaipua.core.constants import PUA_RANGE_END, PUA_RANGE_START, THAI_CONSONANT_CHARS
from thaipua.core.font.occupancy import PuaOccupant
from thaipua.core.font.ownership import SlotOwnership
from thaipua.core.pua_map import THAI_SUFFIXES

logger = logging.getLogger(__name__)

DEFAULT_BASE_CODEPOINT = 0xE000
"""Canonical layout origin; configurable per install via `layout.json`."""

_SCHEMA_VERSION = 1


def cluster_ordinal(thai_key: str) -> int | None:
    """Return the cluster's position in the fixed consonant-x-suffix order, or `None` when malformed."""
    if len(thai_key) < 1:
        return None
    consonant, suffix = thai_key[0], thai_key[1:]
    if consonant not in THAI_CONSONANT_CHARS or suffix not in THAI_SUFFIXES:
        return None
    return THAI_CONSONANT_CHARS.index(consonant) * len(THAI_SUFFIXES) + THAI_SUFFIXES.index(suffix)


def key_at_ordinal(ordinal: int) -> str:
    """Return the Thai key sitting at `ordinal` in the fixed consonant-x-suffix order."""
    consonant = THAI_CONSONANT_CHARS[ordinal // len(THAI_SUFFIXES)]
    suffix = THAI_SUFFIXES[ordinal % len(THAI_SUFFIXES)]
    return f"{consonant}{suffix}"


def canonical_codepoint(thai_key: str, base: int) -> int | None:
    """Return the deterministic codepoint `base + ordinal` for `thai_key`, or `None` when malformed."""
    ordinal = cluster_ordinal(thai_key)
    return None if ordinal is None else base + ordinal


def cluster_count() -> int:
    """Return the total number of clusters in the fixed layout grid."""
    return len(THAI_CONSONANT_CHARS) * len(THAI_SUFFIXES)


def canonical_tail_start(base: int) -> int:
    """Return the first codepoint after the canonical block — the relocation zone."""
    return base + cluster_count()


def max_base_codepoint() -> int:
    """Return the highest base that keeps the whole canonical block inside the PUA range."""
    return PUA_RANGE_END - cluster_count() + 1


def is_valid_base(base: int) -> bool:
    """Return whether `base` starts a canonical block fully inside the PUA range."""
    return PUA_RANGE_START <= base <= max_base_codepoint()


def canonical_layout(base: int) -> dict[str, str]:
    """Build the full deterministic key→PUA-char map under `base`."""
    return {key_at_ordinal(ordinal): chr(base + ordinal) for ordinal in range(cluster_count())}


def effective_layout(base: int, relocations: dict[str, str]) -> dict[str, str]:
    """Merge `relocations` over the canonical layout; malformed keys are ignored with a warning."""
    mapping = canonical_layout(base)
    for thai_key, pua_char in relocations.items():
        if cluster_ordinal(thai_key) is None or len(pua_char) != 1:
            logger.warning("Ignoring malformed relocation %r -> %r", thai_key, pua_char)
            continue
        mapping[thai_key] = pua_char
    return mapping


@dataclass(slots=True)
class LayoutState:
    """Persisted layout configuration: canonical base, relocation deltas, and approved overrides."""

    base: int = DEFAULT_BASE_CODEPOINT
    relocations: dict[str, str] = field(default_factory=dict)
    overrides: frozenset[int] = frozenset()
    """PUA codepoints whose locked slots the user approved for overwrite."""

    def effective_map(self) -> dict[str, str]:
        """Materialize the full key→PUA-char map this state describes."""
        return effective_layout(self.base, self.relocations)


@dataclass(frozen=True, slots=True)
class LayoutConflict:
    """One effective-map entry whose target slot holds foreign content."""

    thai_key: str
    codepoint: int
    occupant: PuaOccupant


def find_conflicts(
    mapping: dict[str, str],
    occupants: list[PuaOccupant],
    resolved: frozenset[int] = frozenset(),
) -> list[LayoutConflict]:
    """Return entries whose slots are LOCKED or REPLACEABLE, sorted by codepoint ascending.

    Codepoints in `resolved` (user-approved overrides) are not reported.
    """
    by_codepoint = {o.codepoint: o for o in occupants}
    conflicts = []
    for thai_key, pua_char in mapping.items():
        if len(pua_char) != 1:
            continue
        codepoint = ord(pua_char)
        occupant = by_codepoint.get(codepoint)
        if codepoint in resolved:
            continue
        if occupant is not None and occupant.ownership is not SlotOwnership.OWNED:
            conflicts.append(LayoutConflict(thai_key, codepoint, occupant))
    conflicts.sort(key=lambda c: c.codepoint)
    return conflicts


def find_relocation_target(
    start: int,
    used_pua_chars: set[str],
    font_cmap_codepoints: set[int] | None = None,
) -> int:
    """Return the lowest free PUA codepoint at or above `start`, skipping map and font occupancy."""
    reserved = set(used_pua_chars)
    if font_cmap_codepoints:
        reserved.update(chr(cp) for cp in font_cmap_codepoints if PUA_RANGE_START <= cp <= PUA_RANGE_END)
    codepoint = max(start, PUA_RANGE_START)
    while codepoint <= PUA_RANGE_END and chr(codepoint) in reserved:
        codepoint += 1
    if codepoint > PUA_RANGE_END:
        raise RuntimeError(f"No free PUA codepoint between U+{start:04X} and U+{PUA_RANGE_END:04X}")
    return codepoint


def load_layout_state(path: str | Path) -> LayoutState | None:
    """Read layout configuration from `path`; `None` when missing or unreadable."""
    try:
        with Path(path).open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read layout file: %s", path, exc_info=True)
        return None
    if not isinstance(payload, dict):
        logger.warning("Layout file has an unexpected shape; ignoring: %s", path)
        return None
    base = _parse_hex(payload.get("base"), DEFAULT_BASE_CODEPOINT)
    if not is_valid_base(base):
        logger.warning("Layout base U+%04X is outside the PUA range; using the default", base)
        base = DEFAULT_BASE_CODEPOINT
    raw_relocations = payload.get("relocations")
    relocations = {str(k): v for k, v in raw_relocations.items()} if isinstance(raw_relocations, dict) else {}
    overrides = _parse_overrides(payload.get("overrides"))
    return LayoutState(base=base, relocations=relocations, overrides=overrides)


def save_layout_state(state: LayoutState, path: str | Path) -> None:
    """Write layout configuration to `path`; failures are logged rather than raised."""
    payload = {
        "version": _SCHEMA_VERSION,
        "base": f"{state.base:04X}",
        "relocations": state.relocations,
        "overrides": sorted(f"{code:04X}" for code in state.overrides),
    }
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with Path(path).open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=4)
        logger.info(
            "Saved layout (base U+%04X, %d relocation(s), %d override(s)) to %s",
            state.base,
            len(state.relocations),
            len(state.overrides),
            path,
        )
    except OSError:
        logger.exception("Failed to write layout file: %s", path)


def _parse_overrides(value: Any) -> frozenset[int]:
    """Interpret a JSON field as a set of hex codepoints; malformed entries are skipped."""
    if not isinstance(value, list):
        return frozenset()
    codes: set[int] = set()
    for entry in value:
        try:
            codes.add(int(str(entry), 16))
        except ValueError:
            logger.warning("Skipping malformed override entry %r", entry)
    return frozenset(codes)


def _parse_hex(value: Any, fallback: int) -> int:
    """Interpret a JSON field as a hex codepoint, falling back on malformed input."""
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return fallback
