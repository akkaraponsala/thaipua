"""Unit tests for the undoable project session: whole-document snapshots, coalescing, and bounds."""

from __future__ import annotations

from pathlib import Path

from thaipua.core.commands import DocumentCommand, DocumentSnapshot
from thaipua.core.domain.settings import Offset, default_placement_settings
from thaipua.core.layout import LayoutState, load_layout_state
from thaipua.core.session import ProjectSession
from thaipua.gui.font_service import FontService


def _nudge_settings(session: ProjectSession, cons_uni: int = 0x0E01) -> None:
    """Replace the live settings through the `with_*` copy API, the way the `apply_*` helpers do."""
    session.replace_settings(session.settings.with_base_offset(cons_uni, "tone_mark", Offset(1, 2)))


def test_execute_undo_redo_roundtrips_layout_and_settings() -> None:
    session = ProjectSession()
    assert session.execute("Set base", lambda: session.layout.set_base(0xE100)) is True
    assert session.execute("Nudge offset", lambda: _nudge_settings(session)) is True
    assert session.undo_depth == 2
    assert session.undo() == "Nudge offset"
    assert session.settings == default_placement_settings()
    assert session.layout.base == 0xE100
    assert session.undo() == "Set base"
    assert session.layout.base == 0xE000
    assert session.redo() == "Set base"
    assert session.redo() == "Nudge offset"
    assert session.settings.consonants[0x0E01].base_offsets["tone_mark"] == Offset(1, 2)


def test_noop_execute_pushes_nothing() -> None:
    session = ProjectSession()
    assert session.execute("No-op", lambda: None) is False
    assert session.undo_depth == 0
    assert session.undo() is None
    assert session.redo() is None
    assert session.undo_label is None
    assert session.redo_label is None
    assert not session.can_undo
    assert not session.can_redo


def test_coalescing_merges_one_knob_into_one_step() -> None:
    session = ProjectSession()
    for x in (1, 2, 3):

        def mutate(x: int = x) -> None:
            session.layout.pin_relocations({"ก่": chr(0xE900 + x)})

        session.execute(f"Offset {x}", mutate, coalesce_key="offset:ก่")
    assert session.undo_depth == 1
    assert session.undo_label == "Offset 3"
    assert session.undo() == "Offset 3"
    assert "ก่" not in session.layout.relocations
    assert session.redo() == "Offset 3"
    assert session.layout.effective_map()["ก่"] == chr(0xE903)


def test_distinct_keys_push_distinct_steps_and_new_work_clears_redo() -> None:
    session = ProjectSession()
    session.execute("Pin A", lambda: session.layout.pin_relocations({"ก่": chr(0xE900)}), coalesce_key="a")
    session.execute("Pin B", lambda: session.layout.pin_relocations({"ข่": chr(0xE901)}), coalesce_key="b")
    assert session.undo_depth == 2
    assert session.undo() == "Pin B"
    assert session.redo() == "Pin B"
    session.execute("Pin C", lambda: session.layout.pin_relocations({"ค": chr(0xE902)}), coalesce_key="c")
    assert session.redo() is None
    assert not session.can_redo


def test_history_is_capped() -> None:
    session = ProjectSession()
    for i in range(105):

        def pin(i: int = i) -> None:
            session.layout.pin_relocations({"ก่": chr(0xE900 + i)})

        session.execute(f"Pin {i}", pin)
    assert session.undo_depth == 100
    for _ in range(100):
        assert session.undo() is not None
    assert session.layout.relocations["ก่"] == chr(0xE904)
    assert session.undo() is None


def test_open_document_adopts_and_clears() -> None:
    session = ProjectSession()
    session.execute("Pin", lambda: session.layout.pin_relocations({"ก่": chr(0xE900)}))
    fresh_layout = LayoutState(base=0xE100)
    fresh_settings = default_placement_settings()
    session.open_document(fresh_layout, fresh_settings)
    assert session.layout is fresh_layout
    assert session.settings is fresh_settings
    assert session.undo_depth == 0
    assert not session.can_undo


def test_restore_replaces_settings_object_with_equal_content() -> None:
    session = ProjectSession()
    before_settings = session.settings
    snapshot = session.snapshot()
    _nudge_settings(session)
    assert session.settings != before_settings
    assert before_settings == default_placement_settings()
    session.restore(snapshot)
    assert session.settings is not before_settings
    assert session.settings == default_placement_settings()


def test_merged_with_rejects_other_keys() -> None:
    def command(label: str, key: str | None) -> DocumentCommand:
        snapshot = ProjectSession().snapshot()
        return DocumentCommand(label=label, before=snapshot, after=snapshot, coalesce_key=key)

    assert command("a", "x").merged_with(command("b", "y")) is None
    assert command("a", None).merged_with(command("b", None)) is None
    merged = command("a", "x").merged_with(command("b", "x"))
    assert merged is not None
    assert merged.label == "b"


def _service_with_layout(tmp_path: Path) -> FontService:
    service = FontService()
    service.set_layout_path(str(tmp_path / "layout.json"))
    service.set_pua_map_path(str(tmp_path / "pua.json"))
    service.load_layout()
    return service


def test_service_override_undo_restores_approvals_and_persists(tmp_path: Path) -> None:
    service = _service_with_layout(tmp_path)
    assert service.override_slots([0xE001]) == 1
    assert service.allowed_locked() == frozenset({0xE001})
    assert service.can_undo
    assert service.undo() == "Override slots"
    assert service.allowed_locked() == frozenset()
    assert not service.can_undo
    assert service.redo() == "Override slots"
    assert service.allowed_locked() == frozenset({0xE001})
    reloaded = load_layout_state(tmp_path / "layout.json")
    assert reloaded is not None
    assert reloaded.approvals == service._session.layout.approvals


def test_service_relocate_undo_restores_map(tmp_path: Path) -> None:
    service = _service_with_layout(tmp_path)
    canonical = service.pua_map["ก่"]
    moved = service.relocate_keys(["ก่"])
    assert service.pua_map["ก่"] == chr(moved["ก่"]) != canonical
    assert service.undo() == "Relocate 1 key(s)"
    assert service.pua_map["ก่"] == canonical
    assert service.redo() == "Relocate 1 key(s)"
    assert service.pua_map["ก่"] == chr(moved["ก่"])


def test_snapshot_never_aliases_live_state() -> None:
    session = ProjectSession()
    snapshot: DocumentSnapshot = session.snapshot()
    session.layout.pin_relocations({"ก่": chr(0xE900)})
    _nudge_settings(session)
    assert snapshot.relocations == {}
    assert snapshot.settings == default_placement_settings()
