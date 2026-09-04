"""Replayable project-document commands over whole-document snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from thaipua.core.domain.settings import PlacementSettings


@dataclass(frozen=True, slots=True)
class DocumentSnapshot:
    """One undoable document state; constructed from copies and never mutated afterwards."""

    base: int
    relocations: dict[str, str]
    approvals: dict[str, frozenset[int]]
    settings: PlacementSettings


@dataclass(frozen=True, slots=True)
class DocumentCommand:
    """One undo step carrying its before/after snapshots plus an optional coalescing key."""

    label: str
    before: DocumentSnapshot
    after: DocumentSnapshot
    coalesce_key: str | None = None

    def merged_with(self, newer: DocumentCommand) -> DocumentCommand | None:
        """Fold `newer` into this command when both share a coalescing key, else `None`.

        Consecutive tweaks of one knob (slider ticks) collapse into a single undo
        step spanning the first before-state to the latest after-state.
        """
        if self.coalesce_key is None or self.coalesce_key != newer.coalesce_key:
            return None
        return DocumentCommand(label=newer.label, before=self.before, after=newer.after, coalesce_key=self.coalesce_key)
