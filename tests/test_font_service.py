"""Unit tests for `FontService`'s PUA map loading, slot-context snapshotting, and overrides."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from conftest import FakeGlyf, make_glyf

from thaipua.core.constants import PUA_RANGE_END
from thaipua.core.fonttools.composer import ThaiPuaFontGenerator
from thaipua.core.fonttools.map_validation import IssueSeverity
from thaipua.core.fonttools.specs import CompositeSpec
from thaipua.core.layout import (
    canonical_codepoint,
    canonical_tail_start,
    max_base_codepoint,
    save_layout_state,
)
from thaipua.gui.font_service import FontService


class _FakeFont:
    """Duck-typed `TTFont` exposing only `getBestCmap` and `get`."""

    def __init__(self, cmap: dict[int, str], glyf: FakeGlyf | None = None) -> None:
        self._cmap = cmap
        self._glyf = glyf

    def getBestCmap(self) -> dict[int, str]:
        return self._cmap

    def get(self, key: str) -> Any:
        return self._glyf if key == "glyf" else None


def _service_with_font(cmap: dict[int, str], glyf: FakeGlyf | None = None) -> FontService:
    service = FontService()
    service._gen = cast(ThaiPuaFontGenerator, SimpleNamespace(font=_FakeFont(cmap, glyf)))
    return service


def test_pua_slot_context_is_none_without_a_font() -> None:
    assert FontService().pua_slot_context() is None


def test_pua_slot_context_snapshots_cmap_and_glyf() -> None:
    cmap = {0xE000: "logo", 0x0E01: "ko_kai"}
    glyf = make_glyf(logo=False, ko_kai=False)
    context = _service_with_font(cmap, glyf).pua_slot_context()
    assert context is not None
    assert context.cmap == cmap
    assert context.glyf is glyf


def test_component_boxes_are_empty_without_a_glyf_table() -> None:
    spec = CompositeSpec(pua_code=0xE000, cons_uni=0x0E01)
    service = _service_with_font({0xE000: "foreign_glyph"}, glyf=None)
    assert service._component_boxes("foreign_glyph", spec) == []


def test_validation_issues_is_empty_for_a_clean_map() -> None:
    cmap = {0x0E01: "ko_kai"}
    glyf = make_glyf(ko_kai=False)
    mapping = {"ก": chr(0xE000)}
    assert _service_with_font(cmap, glyf).validation_issues(mapping) == []


def test_validation_issues_flags_locked_slots_and_duplicates() -> None:
    cmap = {0xE000: "logo", 0x0E01: "ko_kai"}
    glyf = make_glyf(logo=False, ko_kai=False)
    mapping = {"ก": chr(0xE000), "ข": chr(0xE000), "ค": chr(0xE005)}
    issues = _service_with_font(cmap, glyf).validation_issues(mapping)

    locked = {issue.thai_key for issue in issues if "locked" in issue.message}
    duplicated = {issue.thai_key for issue in issues if "shared by multiple keys" in issue.message}
    assert all(issue.severity is IssueSeverity.ERROR for issue in issues)
    assert locked == {"ก", "ข"}
    assert duplicated == {"ก", "ข"}


def test_validation_issues_still_checks_structure_without_a_font() -> None:
    mapping = {"ก": chr(0xE000), "ข": chr(0xE000)}
    issues = FontService().validation_issues(mapping)
    assert issues
    assert all(issue.severity is IssueSeverity.ERROR for issue in issues)


def test_override_roundtrip_persists_across_services(tmp_path: Path) -> None:
    service = FontService()
    service.set_layout_path(str(tmp_path / "layout.json"))
    service.set_pua_map_path(str(tmp_path / "pua.json"))
    service.load_layout()
    assert service.allowed_locked() == frozenset()

    service.override_slot(0xE600)
    service.override_slot(0xE601)
    service.clear_override(0xE600)

    assert service.allowed_locked() == frozenset({0xE601})
    fresh = FontService()
    fresh.set_layout_path(str(tmp_path / "layout.json"))
    fresh.set_pua_map_path(str(tmp_path / "pua.json"))
    fresh.load_layout()
    assert fresh.allowed_locked() == frozenset({0xE601})


def test_validation_issues_respects_user_overrides(tmp_path: Path) -> None:
    service = _service_with_font({0xE000: "logo"}, make_glyf(logo=False))
    service.set_layout_path(str(tmp_path / "layout.json"))
    service.set_pua_map_path(str(tmp_path / "pua.json"))
    service.load_layout()
    mapping = {"ก": chr(0xE000)}

    before = service.validation_issues(mapping)
    assert all(issue.severity is IssueSeverity.ERROR for issue in before)

    service.override_slot(0xE000)

    after = service.validation_issues(mapping)
    assert all(issue.severity is IssueSeverity.WARNING for issue in after)


def test_pua_occupants_are_empty_without_a_font() -> None:
    assert FontService().pua_occupants() == []


def test_load_layout_bootstraps_canonical_map_and_cache(tmp_path: Path) -> None:
    service = FontService()
    service.set_layout_path(str(tmp_path / "layout.json"))
    service.set_pua_map_path(str(tmp_path / "pua.json"))

    mapping = service.load_layout()

    assert len(mapping) == 2016
    assert mapping["กั"] == chr(0xE000)
    assert mapping == service.pua_map
    assert (tmp_path / "pua.json").is_file()
    reloaded = FontService()
    reloaded.set_layout_path(str(tmp_path / "layout.json"))
    reloaded.set_pua_map_path(str(tmp_path / "pua.json"))
    assert reloaded.load_layout() == mapping


def test_manual_edits_become_relocations_and_revert_to_canonical(tmp_path: Path) -> None:
    service = FontService()
    service.set_layout_path(str(tmp_path / "layout.json"))
    service.set_pua_map_path(str(tmp_path / "pua.json"))
    service.load_layout()

    moved = service.apply_manual_edits({**service.pua_map, "ก่": chr(0xE900)})
    assert moved["ก่"] == chr(0xE900)
    canonical_char = canonical_codepoint("ก่", 0xE000)
    assert canonical_char is not None
    reverted = service.apply_manual_edits({**moved, "ก่": chr(canonical_char)})
    assert reverted["ก่"] == chr(canonical_char)
    assert service._layout is not None
    assert service._layout.relocations == {}


def test_set_base_codepoint_shifts_the_whole_layout(tmp_path: Path) -> None:
    service = FontService()
    service.set_layout_path(str(tmp_path / "layout.json"))
    service.set_pua_map_path(str(tmp_path / "pua.json"))
    service.load_layout()

    shifted = service.set_base_codepoint(0xE100)

    assert shifted["กั"] == chr(0xE100)
    assert service.layout_base() == 0xE100
    assert service.layout_tail_start() == 0xE100 + 2016


def test_set_base_codepoint_rejects_bases_outside_the_pua_range(tmp_path: Path) -> None:
    service = FontService()
    service.set_layout_path(str(tmp_path / "layout.json"))
    service.set_pua_map_path(str(tmp_path / "pua.json"))
    service.load_layout()

    with pytest.raises(ValueError, match="outside the PUA range"):
        service.set_base_codepoint(0x0040)
    with pytest.raises(ValueError, match="outside the PUA range"):
        service.set_base_codepoint(max_base_codepoint() + 1)

    assert service.set_base_codepoint(max_base_codepoint()) == service.pua_map
    assert canonical_tail_start(service.layout_base()) - 1 <= PUA_RANGE_END


def test_state_version_bumps_on_layout_and_install_mutations(tmp_path: Path) -> None:
    from conftest import FakeGlyf, FakeGlyph

    cmap = {0xE000: "logo", 0x0E01: "ko_kai"}
    glyf = FakeGlyf({"logo": FakeGlyph(composite=False), "ko_kai": FakeGlyph(composite=False)})
    service = _service_with_font(cmap, glyf)
    service.set_layout_path(str(tmp_path / "layout.json"))
    service.set_pua_map_path(str(tmp_path / "pua.json"))

    before = service.state_version
    service.load_layout()
    after_load = service.state_version
    assert after_load > before

    service.override_slot(0xE600)
    assert service.state_version > after_load


def test_override_clears_conflicts_and_relocate_key_moves_keys(tmp_path: Path) -> None:
    from conftest import FakeGlyf, FakeGlyph

    conflict_cp = 0xE000
    cmap = {conflict_cp: "logo", 0x0E01: "ko_kai"}
    glyf = FakeGlyf({"logo": FakeGlyph(composite=False), "ko_kai": FakeGlyph(composite=False)})
    service = _service_with_font(cmap, glyf)
    service.set_layout_path(str(tmp_path / "layout.json"))
    service.set_pua_map_path(str(tmp_path / "pua.json"))
    mapping = service.load_layout()
    conflicted_key = next(key for key, char in mapping.items() if ord(char) == conflict_cp)
    assert len(service.layout_conflicts()) == 1

    service.override_slot(conflict_cp)
    assert conflict_cp in service.allowed_locked()
    assert service.layout_conflicts() == []
    assert service.pua_map[conflicted_key] == chr(conflict_cp)

    other_key = next(
        key
        for key, char in mapping.items()
        if ord(char) != conflict_cp and canonical_codepoint(key, 0xE000) == ord(char)
    )
    new_cp = service.relocate_key(other_key)
    assert new_cp is not None
    assert new_cp >= 0xE000 + 2016
    assert service.pua_map[other_key] == chr(new_cp)
    assert service.layout_conflicts() == []


def test_bulk_override_and_relocate_each_persist_the_layout_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conftest import FakeGlyf, FakeGlyph

    conflict_cps = [0xE000, 0xE001, 0xE002]
    cmap: dict[int, str] = {cp: f"logo{cp}" for cp in conflict_cps} | {0x0E01: "ko_kai"}
    glyf = FakeGlyf(
        {**{f"logo{cp}": FakeGlyph(composite=False) for cp in conflict_cps}, "ko_kai": FakeGlyph(composite=False)}
    )
    service = _service_with_font(cmap, glyf)
    service.set_layout_path(str(tmp_path / "layout.json"))
    service.set_pua_map_path(str(tmp_path / "pua.json"))
    mapping = service.load_layout()
    keys = sorted(
        (key for key, char in mapping.items() if ord(char) in (0xE000, 0xE001)), key=lambda k: ord(mapping[k])
    )

    persist_calls = 0
    real_save = save_layout_state

    def counting_save(state: Any, path: Any) -> None:
        nonlocal persist_calls
        persist_calls += 1
        real_save(state, path)

    monkeypatch.setattr("thaipua.gui.font_service.save_layout_state", counting_save)

    added = service.override_slots(conflict_cps)
    assert added == 3
    assert service.allowed_locked() == frozenset(conflict_cps)
    assert persist_calls == 1

    moved = service.relocate_keys(keys)
    assert len(moved) == len(keys)
    assert len(set(moved.values())) == len(keys)
    assert all(codepoint >= 0xE000 + 2016 for codepoint in moved.values())
    assert persist_calls == 2
