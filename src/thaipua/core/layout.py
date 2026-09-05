"""Deterministic Thai-cluster-to-PUA layout over the domain engine: assignment, deltas, storage, conflicts."""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thaipua.core.constants import PUA_RANGE_END, PUA_RANGE_START, THAI_CONSONANT_CHARS
from thaipua.core.domain.cluster import ThaiCluster, canonical_cluster_key, canonical_suffix, render_key, try_key
from thaipua.core.domain.errors import LayoutError
from thaipua.core.domain.grid import LEGAL_COMBOS, STRIDE
from thaipua.core.domain.layout import LayoutDocument, LayoutEngine
from thaipua.core.domain.resolution import RelocatePin, ResolveCommand, resolve
from thaipua.core.domain.slots import is_conflict
from thaipua.core.domain.thai import CONSONANT_INDEX
from thaipua.core.font.occupancy import PuaOccupant
from thaipua.core.store.json_store import DiskJsonStore
from thaipua.core.store.ports import JsonStore

logger = logging.getLogger(__name__)

DEFAULT_BASE_CODEPOINT = 0xE000
"""Canonical layout origin; configurable per install via `layout.json`."""

_SCHEMA_VERSION = 2
"""Wire-schema version written on save; versions 1 and 2 share the shape, so both load."""


def cluster_ordinal(thai_key: str) -> int | None:
    """Return the cluster's stride-60 ordinal, or `None` when malformed or outside the legal grid.

    Marks in any input order canonicalize to construction order before lookup, so
    reordered-but-valid keys resolve to the same ordinal as their stored form.
    Consonant order comes from the domain index — the single home shared with
    the grid — rather than rescanning the character string.
    """
    if len(thai_key) < 1:
        return None
    cons_index = CONSONANT_INDEX.get(ord(thai_key[0]))
    if cons_index is None:
        return None
    suffix = canonical_suffix(thai_key[1:])
    if suffix is None:
        return None
    try:
        return cons_index * STRIDE + LEGAL_COMBOS.index(suffix)
    except ValueError:
        return None


def key_at_ordinal(ordinal: int) -> str:
    """Return the Thai key sitting at `ordinal` in the stride-60 grid."""
    consonant = THAI_CONSONANT_CHARS[ordinal // STRIDE]
    suffix = LEGAL_COMBOS[ordinal % STRIDE]
    return f"{consonant}{suffix}"


def canonical_codepoint(thai_key: str, base: int) -> int | None:
    """Return the deterministic codepoint `base + ordinal` for `thai_key`, or `None` when malformed."""
    ordinal = cluster_ordinal(thai_key)
    return None if ordinal is None else base + ordinal


def cluster_count() -> int:
    """Return the codepoints spanned by one canonical block (42 consonants, stride 60)."""
    return len(THAI_CONSONANT_CHARS) * STRIDE


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
    """Build the materialized key→PUA-char map under `base`, sparse within the 2,520 block."""
    return effective_layout(base, {})


def _engine_for(base: int, relocations: dict[str, str]) -> tuple[LayoutEngine, dict[str, str]]:
    """Build the domain engine for the in-range pins, plus the out-of-range overlay.

    Malformed entries are skipped with a warning exactly as before; pins outside
    the PUA range stay in the overlay so the validator still sees and flags them.
    """
    pins: dict[ThaiCluster, int] = {}
    overlay: dict[str, str] = {}
    for raw_key, pua_char in relocations.items():
        cluster = try_key(raw_key) if isinstance(raw_key, str) else None
        if cluster is None or not isinstance(pua_char, str) or len(pua_char) != 1:
            logger.warning("Ignoring malformed relocation %r -> %r", raw_key, pua_char)
            continue
        canonical = render_key(cluster)
        if not PUA_RANGE_START <= ord(pua_char) <= PUA_RANGE_END:
            overlay[canonical] = pua_char
            continue
        pins[cluster] = ord(pua_char)
    return LayoutEngine(document=LayoutDocument(base=base, relocations=pins)), overlay


def effective_layout(base: int, relocations: dict[str, str]) -> dict[str, str]:
    """Merge `relocations` over the canonical layout; malformed keys are ignored with a warning.

    Ordinal math comes from the domain `LayoutEngine`, rendered back in stored
    construction order; out-of-range pins overlay afterwards so the validator
    still sees (and flags) them.
    """
    engine, overlay = _engine_for(base, relocations)
    return _render_effective(engine, overlay)


def _render_effective(engine: LayoutEngine, overlay: dict[str, str]) -> dict[str, str]:
    """Copy the engine map to PUA chars, then apply the out-of-range overlay."""
    mapping = {key: chr(codepoint) for key, codepoint in engine.map.items()}
    mapping.update(overlay)
    return mapping


@dataclass(slots=True)
class LayoutState:
    """Persisted layout configuration: canonical base, relocation deltas, and per-font approvals."""

    base: int = DEFAULT_BASE_CODEPOINT
    relocations: dict[str, str] = field(default_factory=dict)
    approvals: dict[str, frozenset[int]] = field(default_factory=dict)
    """Overwrite approvals per font session, keyed by session id; closed sessions are garbage-collected."""
    _engine: LayoutEngine = field(init=False, repr=False, compare=False)
    _overlay: dict[str, str] = field(init=False, repr=False, compare=False)
    _rendered: dict[str, str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate the raw relocations once, so later reads never re-parse."""
        self._rebuild()

    def effective_map(self) -> dict[str, str]:
        """Return a copy of the cached key→PUA-char map without revalidating."""
        return dict(self._rendered)

    @property
    def engine(self) -> LayoutEngine:
        """Return the held engine deriving the cached map."""
        return self._engine

    def set_base(self, base: int) -> None:
        """Shift every relocation pin by the base delta, dropping out-of-range pins, then revalidate once."""
        pins: dict[ThaiCluster, int] = {}
        for thai_key, pua_char in self.relocations.items():
            cluster = try_key(thai_key) if isinstance(thai_key, str) else None
            if (
                cluster is not None
                and isinstance(pua_char, str)
                and len(pua_char) == 1
                and PUA_RANGE_START <= ord(pua_char) <= PUA_RANGE_END
            ):
                pins[cluster] = ord(pua_char)
        engine = LayoutEngine(document=LayoutDocument(base=self.base, relocations=pins))
        absolute = {cluster: code for cluster, code in engine.with_base(base).document.relocations.items()}
        delta = base - self.base
        rebuilt: dict[str, str] = {}
        for thai_key, pua_char in self.relocations.items():
            cluster = try_key(thai_key) if isinstance(thai_key, str) else None
            if not isinstance(pua_char, str) or len(pua_char) != 1:
                rebuilt[thai_key] = pua_char
                continue
            if cluster is not None and cluster in absolute:
                rebuilt[thai_key] = chr(absolute[cluster])
                continue
            moved = ord(pua_char) + delta
            if PUA_RANGE_START <= moved <= PUA_RANGE_END:
                rebuilt[thai_key] = chr(moved)
            else:
                logger.warning("Dropping relocation %r: U+%04X falls outside the PUA range", thai_key, moved)
        self.relocations = rebuilt
        self.base = base
        logger.info("Layout base moved to U+%04X", base)
        self._rebuild()

    def pin_relocations(self, moves: Mapping[str, str]) -> None:
        """Record relocation pins, then revalidate once for the whole batch."""
        self.relocations.update(moves)
        self._rebuild()

    def apply_edits(self, new_map: Mapping[str, str]) -> None:
        """Fold hand-edited mapping values into relocation deltas, then revalidate once.

        Only values differing from the current effective map are recorded; anything
        else is untouched input, not intent. An explicit placement is always kept —
        even when it equals the canonical codepoint — so the record of intent
        survives later rebases instead of being popped.
        """
        pins: list[RelocatePin] = []
        for thai_key, pua_char in new_map.items():
            canonical = canonical_cluster_key(thai_key)
            if canonical is None:
                logger.warning("Ignoring manual edit with an illegal key %r", thai_key)
                continue
            if self._rendered.get(canonical) == pua_char:
                continue
            cluster = try_key(canonical)
            if cluster is None or len(pua_char) != 1:
                self.relocations[canonical] = pua_char
                continue
            pins.append(RelocatePin(cluster=cluster, codepoint=ord(pua_char)))
        if pins:
            self.apply_resolutions(pins)
        else:
            self._rebuild()
        logger.info("Applied %d relocation(s) after manual edit", len(self.relocations))

    def apply_resolution(self, command: ResolveCommand) -> None:
        """Fold one domain slot decision into the raw state, then revalidate once."""
        self.apply_resolutions([command])

    def apply_resolutions(self, commands: Iterable[ResolveCommand]) -> None:
        """Fold several domain slot decisions, revalidating once for the whole batch.

        In-range pins and approvals flow through `domain.resolve`; an out-of-range
        pin is not representable in the engine and stays raw so the validator
        flags it. Raw entries the engine cannot hold (illegal keys, malformed
        values, out-of-range pins) carry over untouched.
        """
        pending = list(commands)
        if not pending:
            return
        raw_extras: dict[str, str] = {}
        engine = self._engine.model_copy(update={"approvals": dict(self.approvals)})
        for command in pending:
            if isinstance(command, RelocatePin) and not PUA_RANGE_START <= command.codepoint <= PUA_RANGE_END:
                raw_extras[render_key(command.cluster)] = chr(command.codepoint)
            else:
                engine = resolve(engine, command)
        rendered: dict[str, str] = {}
        for key, pin in engine.document.relocations.items():
            cluster = key if isinstance(key, ThaiCluster) else ThaiCluster.from_key(str(key))
            rendered[render_key(cluster)] = chr(pin)
        rendered.update(raw_extras)
        rendered.update({key: value for key, value in self._overlay.items() if key not in rendered})
        rendered.update(
            {key: value for key, value in self.relocations.items() if key not in rendered and key not in self._overlay}
        )
        self.relocations = rendered
        self.approvals = dict(engine.approvals)
        self._rebuild()

    def gc_approvals(self, live_font_ids: frozenset[str]) -> None:
        """Drop approvals for closed font sessions through the domain engine.

        Empty sessions are dropped as well, matching revocation semantics so
        snapshot equality keeps working; approvals never affect the rendered
        map, so no revalidation is needed.
        """
        engine = self._engine.model_copy(update={"approvals": dict(self.approvals)})
        self.approvals = {
            font_id: pins for font_id, pins in engine.gc_overrides(live_font_ids).approvals.items() if pins
        }

    def _rebuild(self) -> None:
        """Revalidate the raw relocations into the held engine, overlay, and rendered map."""
        self._engine, self._overlay = _engine_for(self.base, self.relocations)
        self._rendered = _render_effective(self._engine, self._overlay)

    def restore(self, base: int, relocations: dict[str, str], approvals: dict[str, frozenset[int]]) -> None:
        """Replace the raw state, taking ownership of the dicts, then revalidate once."""
        self.base = base
        self.relocations = relocations
        self.approvals = approvals
        self._rebuild()


@dataclass(frozen=True, slots=True)
class LayoutConflict:
    """One effective-map entry whose target slot holds foreign content."""

    thai_key: str
    codepoint: int
    occupant: PuaOccupant


def find_conflicts(
    mapping: dict[str, str],
    occupants: list[PuaOccupant],
    approved: frozenset[int] = frozenset(),
) -> list[LayoutConflict]:
    """Return entries whose slots conflict per the single policy table, sorted by codepoint ascending.

    Approval is not a side-channel skip: every occupied slot is judged by
    `is_conflict()`, and approved slots simply stop conflicting.
    """
    by_codepoint = {o.codepoint: o for o in occupants}
    conflicts = []
    for thai_key, pua_char in mapping.items():
        if len(pua_char) != 1:
            continue
        codepoint = ord(pua_char)
        occupant = by_codepoint.get(codepoint)
        if occupant is None:
            continue
        if is_conflict(occupant.ownership, approved=codepoint in approved):
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


def parse_layout_state(payload: Any) -> LayoutState | None:
    """Validate a decoded JSON document into layout state; `None` when malformed.

    Raise `LayoutError` on an unrecognized schema version instead of loading it
    silently. Versions 1 and 2 share the wire shape — stored relocations are
    absolute pins, valid under either stride — so both load.
    """
    if not isinstance(payload, dict):
        logger.warning("Layout file has an unexpected shape; ignoring")
        return None
    version = payload.get("version", _SCHEMA_VERSION)
    if version not in (1, _SCHEMA_VERSION):
        raise LayoutError(f"unsupported layout version {version}; expected {_SCHEMA_VERSION}")
    base = _parse_hex(payload.get("base"), DEFAULT_BASE_CODEPOINT)
    if not is_valid_base(base):
        logger.warning("Layout base U+%04X is outside the PUA range; using the default", base)
        base = DEFAULT_BASE_CODEPOINT
    raw_relocations = payload.get("relocations")
    relocations: dict[str, str] = {}
    if isinstance(raw_relocations, dict):
        for raw_key, value in raw_relocations.items():
            canonical = canonical_cluster_key(str(raw_key))
            if canonical is None:
                logger.warning("Ignoring relocation with an illegal key %r", raw_key)
                continue
            if canonical in relocations:
                logger.warning(
                    "Relocation %r duplicates an earlier pin after canonicalization; keeping the latter", raw_key
                )
            relocations[canonical] = value
    raw_overrides = payload.get("overrides")
    if isinstance(raw_overrides, list) and raw_overrides:
        logger.warning("Ignoring %d global override(s): approvals are now scoped per font session", len(raw_overrides))
    return LayoutState(base=base, relocations=relocations, approvals=_parse_approvals(payload.get("approvals")))


def layout_state_to_dict(state: LayoutState) -> dict[str, Any]:
    """Serialize layout state to a JSON-ready document."""
    return {
        "version": _SCHEMA_VERSION,
        "base": f"{state.base:04X}",
        "relocations": state.relocations,
        "approvals": {
            session: sorted(f"{code:04X}" for code in codes) for session, codes in state.approvals.items() if codes
        },
    }


def load_layout_state(path: str | Path, *, store: JsonStore | None = None) -> LayoutState | None:
    """Read layout configuration from `path`; `None` when missing or unreadable.

    Raise `LayoutError` on an unrecognized schema version; callers fall back to
    the canonical bootstrap the same way they do for a missing file.
    """
    source = store if store is not None else DiskJsonStore()
    try:
        payload = source.load(path)
    except FileNotFoundError:
        return None
    except OSError, ValueError:
        logger.warning("Failed to read layout file: %s", path, exc_info=True)
        return None
    return parse_layout_state(payload)


def save_layout_state(state: LayoutState, path: str | Path, *, store: JsonStore | None = None) -> None:
    """Write layout configuration to `path`; failures are logged rather than raised."""
    source = store if store is not None else DiskJsonStore()
    payload = layout_state_to_dict(state)
    try:
        source.save(path, payload)
        logger.info(
            "Saved layout (base U+%04X, %d relocation(s), %d approval session(s)) to %s",
            state.base,
            len(state.relocations),
            len(payload["approvals"]),
            path,
        )
    except OSError:
        logger.exception("Failed to write layout file: %s", path)


def _parse_approvals(value: Any) -> dict[str, frozenset[int]]:
    """Interpret a JSON field as per-session hex-codepoint sets; malformed entries are skipped."""
    if not isinstance(value, dict):
        return {}
    approvals: dict[str, frozenset[int]] = {}
    for session, entries in value.items():
        codes = _parse_overrides(entries)
        if codes:
            approvals[str(session)] = codes
    return approvals


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
    except TypeError, ValueError:
        return fallback
