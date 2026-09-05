"""Undoable project document binding layout state, placement settings, and history."""

from collections.abc import Callable

from thaipua.core.commands import DocumentCommand, DocumentSnapshot
from thaipua.core.domain.settings import PlacementSettings, default_placement_settings
from thaipua.core.layout import LayoutState

_MAX_HISTORY = 100
"""Cap on undo depth; one snapshot holds relocation-dict copies plus a shared settings reference."""


class ProjectSession:
    """Own the undoable document: layout state, placement settings, and the undo/redo stacks.

    Undo covers the project document only. The in-memory font binary is a derived
    artifact (previews install into it on every render); undo restores document
    state and callers re-render, with Save rebuilding every composite from scratch.
    """

    def __init__(self) -> None:
        """Start with a canonical layout, default settings, and empty history."""
        self._layout = LayoutState()
        self._settings = default_placement_settings()
        self._undo: list[DocumentCommand] = []
        self._redo: list[DocumentCommand] = []

    @property
    def layout(self) -> LayoutState:
        """Return the live layout state, mutated only through `execute` or boundary methods."""
        return self._layout

    @property
    def settings(self) -> PlacementSettings:
        """Return the live placement settings object; replaced wholesale on restore."""
        return self._settings

    @property
    def can_undo(self) -> bool:
        """Return whether an undo step is available."""
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        """Return whether a redo step is available."""
        return bool(self._redo)

    @property
    def undo_label(self) -> str | None:
        """Return the top undo step's label, or `None` when empty."""
        return self._undo[-1].label if self._undo else None

    @property
    def redo_label(self) -> str | None:
        """Return the top redo step's label, or `None` when empty."""
        return self._redo[-1].label if self._redo else None

    @property
    def undo_depth(self) -> int:
        """Return the number of available undo steps."""
        return len(self._undo)

    def open_document(self, layout: LayoutState, settings: PlacementSettings) -> None:
        """Adopt `layout`/`settings` as the live document, clearing history.

        Session boundaries (font open, layout reload from disk) replace the whole
        document, so prior steps can no longer replay onto it.
        """
        self._layout = layout
        self._settings = settings
        self.clear_history()

    def replace_settings(self, settings: PlacementSettings) -> None:
        """Adopt `settings` without touching history; wrap in `execute` for an undoable replace."""
        self._settings = settings

    def clear_history(self) -> None:
        """Drop every undo/redo step."""
        self._undo.clear()
        self._redo.clear()

    def snapshot(self) -> DocumentSnapshot:
        """Capture the document; layout dicts are copied, settings are shared by reference.

        Sharing is safe because placement settings are frozen: every mutation path
        replaces the object wholesale (`replace_settings`), so a snapshotted
        reference can never observe later edits.
        """
        layout = self._layout
        return DocumentSnapshot(
            base=layout.base,
            relocations=dict(layout.relocations),
            approvals=dict(layout.approvals),
            settings=self._settings,
        )

    def restore(self, snapshot: DocumentSnapshot) -> None:
        """Replace the document from `snapshot`, revalidating the layout once."""
        self._layout.restore(snapshot.base, dict(snapshot.relocations), dict(snapshot.approvals))
        self._settings = snapshot.settings

    def execute(self, label: str, mutate: Callable[[], None], *, coalesce_key: str | None = None) -> bool:
        """Run `mutate`, pushing one undo step when the document changed.

        Return `True` when `mutate` changed anything; no-ops push nothing and
        leave the redo stack alone. A new step always clears the redo stack.
        """
        before = self.snapshot()
        mutate()
        after = self.snapshot()
        if after == before:
            return False
        command = DocumentCommand(label=label, before=before, after=after, coalesce_key=coalesce_key)
        if coalesce_key is not None and self._undo:
            merged = self._undo[-1].merged_with(command)
            if merged is not None:
                self._undo[-1] = merged
                self._redo.clear()
                return True
        self._undo.append(command)
        del self._undo[:-_MAX_HISTORY]
        self._redo.clear()
        return True

    def undo(self) -> str | None:
        """Restore the state before the latest step; return its label, or `None` when empty."""
        if not self._undo:
            return None
        command = self._undo.pop()
        self.restore(command.before)
        self._redo.append(command)
        return command.label

    def redo(self) -> str | None:
        """Re-apply the latest undone step; return its label, or `None` when empty."""
        if not self._redo:
            return None
        command = self._redo.pop()
        self.restore(command.after)
        self._undo.append(command)
        return command.label
