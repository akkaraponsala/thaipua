"""Layout engine: the single source of truth for base, pins, and approvals."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from thaipua.core.domain.cluster import ThaiCluster, ThaiKey, render_key
from thaipua.core.domain.errors import LayoutError
from thaipua.core.domain.grid import GRID_VERSION, LEGAL_COMBOS, MATERIALIZED, PER_CONSONANT, SlotGrid
from thaipua.core.domain.pua_map import PuaCodepoint
from thaipua.core.domain.thai import CONSONANTS

CURRENT_LAYOUT_VERSION: Literal[2] = 2
PUA_START: int = 0xE000
PUA_END: int = 0xF8FF

_MATERIALIZED_COMBOS: tuple[tuple[str, int], ...] = tuple(
    (suffix, index) for index, suffix in enumerate(LEGAL_COMBOS) if suffix in MATERIALIZED
)
"""Materialized suffixes paired with their stride-60 combo indices, resolved once at import."""


class LayoutDocument(BaseModel):
    """Persisted layout state: canonical base plus explicit relocation pins."""

    model_config = ConfigDict(frozen=True)

    version: int = CURRENT_LAYOUT_VERSION
    base: int = Field(ge=PUA_START, le=PUA_END)
    relocations: dict[ThaiKey, PuaCodepoint] = Field(default_factory=dict)


def layout_from_dict(data: dict[str, Any]) -> LayoutDocument:
    """Parse a layout document, rejecting unknown versions instead of defaulting silently."""
    version = data.get("version", CURRENT_LAYOUT_VERSION)
    if version != CURRENT_LAYOUT_VERSION:
        raise LayoutError(f"unsupported layout version {version}; expected {CURRENT_LAYOUT_VERSION}")
    try:
        return LayoutDocument.model_validate(data)
    except ValueError as exc:
        raise LayoutError(str(exc)) from exc


class LayoutEngine(BaseModel):
    """Immutable layout state; every change returns a new engine, never mutates in place."""

    model_config = ConfigDict(frozen=True)

    document: LayoutDocument
    approvals: dict[str, frozenset[int]] = Field(default_factory=dict)
    grid: SlotGrid = Field(default_factory=SlotGrid)

    @property
    def base(self) -> int:
        """Return the canonical origin."""
        return self.document.base

    @property
    def map(self) -> dict[str, int]:
        """Compute the effective canonical-key-to-codepoint map on demand, without validating keys."""
        out: dict[str, int] = {}
        for cons_index, cons in enumerate(CONSONANTS):
            lead = chr(cons.value)
            for suffix, combo in _MATERIALIZED_COMBOS:
                out[lead + suffix] = self.grid.codepoint(self.document.base, cons_index, combo)
        for key, pin in self.document.relocations.items():
            cluster = key if isinstance(key, ThaiCluster) else ThaiCluster.from_key(str(key))
            out[render_key(cluster)] = int(pin)
        return out

    def full_table(self) -> dict[str, int]:
        """Compute all 2,520 v2 ordinals, keyed by canonical stored-form key."""
        out: dict[str, int] = {}
        for cons_index, cons in enumerate(CONSONANTS):
            lead = chr(cons.value)
            for combo_index, suffix in enumerate(LEGAL_COMBOS):
                out[lead + suffix] = self.grid.codepoint(self.document.base, cons_index, combo_index)
        return out

    def with_base(self, base: int) -> LayoutEngine:
        """Shift every relocation pin by the base delta; drop pins leaving the PUA range."""
        if not PUA_START <= base <= PUA_END:
            raise LayoutError(f"base U+{base:04X} outside the PUA range")
        if base + len(CONSONANTS) * PER_CONSONANT - 1 > PUA_END:
            raise LayoutError(f"base U+{base:04X} pushes the canonical block outside the PUA range")
        delta = base - self.document.base
        shifted: dict[ThaiCluster, int] = {}
        for key, pin in self.document.relocations.items():
            cluster = key if isinstance(key, ThaiCluster) else ThaiCluster.from_key(str(key))
            moved = int(pin) + delta
            if PUA_START <= moved <= PUA_END:
                shifted[cluster] = moved
        document = LayoutDocument(version=self.document.version, base=base, relocations=shifted)
        return LayoutEngine(document=document, approvals=self.approvals, grid=self.grid)

    def with_relocation(self, cluster: ThaiCluster, codepoint: int) -> LayoutEngine:
        """Pin `cluster` to an absolute codepoint, keeping the record even when canonical."""
        if not PUA_START <= codepoint <= PUA_END:
            raise LayoutError(f"pin U+{codepoint:04X} outside the PUA range")
        relocations = dict(self.document.relocations)
        relocations[cluster] = codepoint  # never pop: intent survives rebases
        document = LayoutDocument(version=self.document.version, base=self.document.base, relocations=relocations)
        return LayoutEngine(document=document, approvals=self.approvals, grid=self.grid)

    def with_override(self, font_id: str, codepoint: int) -> LayoutEngine:
        """Approve overwriting `codepoint` for one font session only."""
        approved = set(self.approvals.get(font_id, frozenset()))
        approved.add(codepoint)
        approvals = dict(self.approvals)
        approvals[font_id] = frozenset(approved)
        return LayoutEngine(document=self.document, approvals=approvals, grid=self.grid)

    def without_override(self, font_id: str, codepoint: int) -> LayoutEngine:
        """Revoke one session's overwrite approval, dropping sessions left with none.

        Empty sessions are dropped so a revoke-all restores the exact pre-approve
        state — snapshot equality (and the undo no-op guard) depends on it.
        """
        approvals = dict(self.approvals)
        remaining = set(approvals.get(font_id, frozenset()))
        remaining.discard(codepoint)
        if remaining:
            approvals[font_id] = frozenset(remaining)
        else:
            approvals.pop(font_id, None)
        return LayoutEngine(document=self.document, approvals=approvals, grid=self.grid)

    def allowed_locked(self, font_id: str) -> frozenset[int]:
        """Return the codepoints approved for overwrite in one font session."""
        return self.approvals.get(font_id, frozenset())

    def gc_overrides(self, live_font_ids: frozenset[str]) -> LayoutEngine:
        """Drop approvals for closed font sessions."""
        return LayoutEngine(
            document=self.document,
            approvals={fid: pins for fid, pins in self.approvals.items() if fid in live_font_ids},
            grid=self.grid,
        )


def fresh_engine(base: int = PUA_START) -> LayoutEngine:
    """Build an engine with no relocations and no approvals."""
    return LayoutEngine(document=LayoutDocument(version=GRID_VERSION, base=base))
