"""Unit tests for the deterministic Thai-cluster-to-PUA layout model."""

import logging
from pathlib import Path

import pytest
from _pytest.logging import LogCaptureFixture

from thaipua.core.constants import PUA_RANGE_END, PUA_RANGE_START
from thaipua.core.domain.cluster import try_key
from thaipua.core.domain.errors import LayoutError
from thaipua.core.domain.resolution import OverrideApproval, OverrideRevocation, RelocatePin
from thaipua.core.font.occupancy import PuaOccupant
from thaipua.core.font.ownership import SlotOwnership
from thaipua.core.layout import (
    DEFAULT_BASE_CODEPOINT,
    LayoutState,
    canonical_codepoint,
    canonical_layout,
    canonical_tail_start,
    cluster_count,
    cluster_ordinal,
    effective_layout,
    find_conflicts,
    find_relocation_target,
    is_valid_base,
    key_at_ordinal,
    load_layout_state,
    max_base_codepoint,
    save_layout_state,
)
from thaipua.core.pua_map import THAI_SUFFIXES


def test_cluster_ordinal_roundtrips_over_every_cluster() -> None:
    for ordinal in range(cluster_count()):
        assert cluster_ordinal(key_at_ordinal(ordinal)) == ordinal
    assert cluster_ordinal("x") is None
    assert cluster_ordinal("") is None


def test_canonical_layout_is_sparse_and_deterministic() -> None:
    layout = canonical_layout(0xE000)
    assert len(layout) == 2016
    assert cluster_count() == 2520
    assert layout["ก่"] == chr(0xE001)
    assert layout["กั"] == chr(0xE006)
    assert layout["ข่"] == chr(0xE000 + 60 + 1)
    assert "ก" not in layout
    codes = sorted(ord(c) for c in layout.values())
    assert len(set(codes)) == 2016
    assert codes[0] == 0xE001
    assert codes[-1] == 0xE000 + 2518  # the final block slot stays a reserved hole
    again = canonical_layout(0xE000)
    assert layout == again
    assert canonical_tail_start(0xE000) == PUA_RANGE_START + 2520


def test_materialized_suffixes_match_the_legacy_set() -> None:
    layout = canonical_layout(0xE000)
    assert {key[1:] for key in layout} == set(THAI_SUFFIXES)


def test_holes_have_ordinals_but_hold_no_slots() -> None:
    assert cluster_ordinal("ก") == 0
    assert key_at_ordinal(0) == "ก"
    assert canonical_codepoint("ก", DEFAULT_BASE_CODEPOINT) == DEFAULT_BASE_CODEPOINT
    assert "ก" not in canonical_layout(DEFAULT_BASE_CODEPOINT)
    assert cluster_ordinal("ก" + chr(0x0E47) + chr(0x0E4C)) is not None


def test_canonical_codepoint_matches_first_consonant_block() -> None:
    assert canonical_codepoint("ก่", DEFAULT_BASE_CODEPOINT) == DEFAULT_BASE_CODEPOINT + 1


def test_effective_layout_applies_relocations_and_ignores_malformed() -> None:
    mapping = effective_layout(0xE000, {"ก่": chr(0xE900), "bogus": chr(0xE901), "กุิ": chr(0xE902)})
    assert mapping["ก่"] == chr(0xE900)
    assert "bogus" not in mapping
    assert "กุิ" not in mapping


def test_find_conflicts_reports_locked_and_replaceable_only() -> None:
    state = LayoutState()
    mapping = state.effective_map()
    conflicted_cp = ord(mapping["กั"])
    occupants = [
        PuaOccupant(conflicted_cp, "logo", SlotOwnership.LOCKED, "simple glyph"),
        PuaOccupant(0xF800, "thaipua_F800", SlotOwnership.OWNED, "composite of x"),
    ]
    conflicts = find_conflicts(mapping, occupants)
    assert [c.thai_key for c in conflicts] == ["กั"]
    assert conflicts[0].codepoint == conflicted_cp
    assert conflicts[0].occupant.detail == "simple glyph"


def test_find_conflicts_skips_approved_codepoints() -> None:
    state = LayoutState()
    mapping = state.effective_map()
    resolved_cp = ord(mapping["กั"])
    other_cp = ord(mapping["ขั"])
    occupants = [
        PuaOccupant(resolved_cp, "logo", SlotOwnership.LOCKED, "simple glyph"),
        PuaOccupant(other_cp, "mark", SlotOwnership.LOCKED, "simple glyph"),
    ]
    conflicts = find_conflicts(mapping, occupants, approved=frozenset({resolved_cp}))
    assert [c.thai_key for c in conflicts] == ["ขั"]


def test_find_relocation_target_skips_used_and_font_occupied() -> None:
    tail = canonical_tail_start(0xE000)
    used = {chr(tail), chr(tail + 1)}
    font_cps = {tail + 2}
    target = find_relocation_target(tail, used, font_cps)
    assert target == tail + 3

    full_zone = set(range(PUA_RANGE_END - 1, PUA_RANGE_END + 1))
    try:
        find_relocation_target(PUA_RANGE_END - 1, set(), full_zone)
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError")


def test_layout_state_roundtrips_through_disk(tmp_path: Path) -> None:
    path = tmp_path / "layout.json"
    state = LayoutState(
        base=0xE100,
        relocations={"ก่": chr(0xE900)},
        approvals={"font-A": frozenset({0xE600, 0xE601})},
    )
    save_layout_state(state, path)
    loaded = load_layout_state(path)
    assert loaded == state


def test_load_layout_state_drops_legacy_global_overrides(tmp_path: Path) -> None:
    path = tmp_path / "layout.json"
    path.write_text(
        '{"version": 1, "base": "E000", "relocations": {}, "overrides": ["E600"], "approvals": {"font-A": ["E601"]}}',
        encoding="utf-8",
    )
    loaded = load_layout_state(path)
    assert loaded is not None
    assert loaded.approvals == {"font-A": frozenset({0xE601})}


def test_load_layout_state_defaults(tmp_path: Path) -> None:
    assert load_layout_state(tmp_path / "missing.json") is None
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_layout_state(path) is None


def test_is_valid_base_bounds_the_canonical_block_inside_pua() -> None:
    assert is_valid_base(PUA_RANGE_START)
    assert is_valid_base(max_base_codepoint())
    assert canonical_tail_start(max_base_codepoint()) - 1 <= PUA_RANGE_END
    assert not is_valid_base(max_base_codepoint() + 1)
    assert not is_valid_base(PUA_RANGE_START - 1)
    assert not is_valid_base(0)


def test_load_layout_state_falls_back_when_base_outside_pua(tmp_path: Path) -> None:
    path = tmp_path / "layout.json"
    path.write_text('{"version": 1, "base": "0040", "relocations": {}, "overrides": []}', encoding="utf-8")
    loaded = load_layout_state(path)
    assert loaded is not None
    assert loaded.base == DEFAULT_BASE_CODEPOINT


def test_load_layout_state_rejects_unknown_version(tmp_path: Path) -> None:
    path = tmp_path / "layout.json"
    path.write_text('{"version": 99, "base": "E000", "relocations": {}}', encoding="utf-8")
    with pytest.raises(LayoutError, match="unsupported layout version 99"):
        load_layout_state(path)


def test_load_layout_state_accepts_versions_1_and_2(tmp_path: Path) -> None:
    import json

    for version in (1, 2):
        path = tmp_path / f"layout_{version}.json"
        payload = {"version": version, "base": "E000", "relocations": {"ก่": chr(0xE900)}}
        path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_layout_state(path)
        assert loaded is not None
        assert loaded.base == 0xE000
        assert loaded.relocations == {"ก่": chr(0xE900)}


def test_gc_approvals_keeps_only_live_nonempty_sessions() -> None:
    state = LayoutState(
        base=0xE000,
        approvals={"live": frozenset({0xE600}), "closed": frozenset({0xE601}), "empty": frozenset()},
    )
    state.gc_approvals(frozenset({"live", "empty"}))
    assert state.approvals == {"live": frozenset({0xE600})}


def test_set_base_carries_malformed_entries_verbatim() -> None:
    state = LayoutState(base=0xE000, relocations={"ก่": chr(0xE900), "bogus": "XY"})
    state.set_base(0xE100)
    assert state.relocations["ก่"] == chr(0xE900 + 0x100)
    assert state.relocations["bogus"] == "XY"


def test_relocations_validate_once_at_the_boundary(caplog: LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="thaipua.core.layout"):
        state = LayoutState(base=0xE000, relocations={"bogus": chr(0xE901), "ก่": chr(0xE900)})
    assert state.effective_map()["ก่"] == chr(0xE900)
    assert "bogus" not in state.effective_map()
    assert "bogus" in caplog.text
    caplog.clear()
    assert state.effective_map() == state.effective_map()
    assert caplog.text == ""


def test_effective_map_returns_an_independent_copy() -> None:
    state = LayoutState()
    first = state.effective_map()
    first["ก่"] = "X"
    assert state.effective_map()["ก่"] == chr(0xE001)


def test_mutations_refresh_the_held_engine() -> None:
    state = LayoutState()
    state.pin_relocations({"ก่": chr(0xE900)})
    assert state.relocations["ก่"] == chr(0xE900)
    assert state.effective_map()["ก่"] == chr(0xE900)
    assert state.engine.base == state.base
    state.set_base(0xE100)
    assert state.engine.base == 0xE100
    assert state.effective_map()["ก่"] == chr(0xE900 + 0x100)
    assert state.relocations["ก่"] == chr(0xE900 + 0x100)
    state.apply_edits({"ก่": chr(0xEA01), "bogus": chr(0xEA02)})
    assert state.effective_map()["ก่"] == chr(0xEA01)
    assert "bogus" not in state.effective_map()
    assert "bogus" not in state.relocations


def test_apply_resolution_pins_through_the_domain_engine() -> None:
    cluster = try_key("ก่")
    assert cluster is not None
    state = LayoutState()
    state.apply_resolution(RelocatePin(cluster=cluster, codepoint=0xE900))
    assert state.relocations == {"ก่": chr(0xE900)}
    assert state.effective_map()["ก่"] == chr(0xE900)
    state.apply_resolution(OverrideApproval(font_id="font-A", codepoint=0xE900))
    assert state.approvals == {"font-A": frozenset({0xE900})}
    assert state.relocations == {"ก่": chr(0xE900)}
    state.apply_resolution(OverrideRevocation(font_id="font-A", codepoint=0xE900))
    assert state.approvals == {}
    assert state.relocations == {"ก่": chr(0xE900)}


def test_apply_resolution_keeps_out_of_range_pins_raw_and_drops_them_when_repinned() -> None:
    cluster = try_key("ก่")
    assert cluster is not None
    state = LayoutState(relocations={"ก่": chr(0x1000)})
    assert state.effective_map()["ก่"] == chr(0x1000)
    state.apply_resolution(RelocatePin(cluster=cluster, codepoint=0x1000))
    assert state.relocations == {"ก่": chr(0x1000)}
    state.apply_resolution(RelocatePin(cluster=cluster, codepoint=0xE900))
    assert state.relocations == {"ก่": chr(0xE900)}
    assert state.effective_map()["ก่"] == chr(0xE900)


def test_apply_resolution_carries_malformed_raw_entries_over() -> None:
    cluster = try_key("ข่")
    assert cluster is not None
    state = LayoutState(relocations={"bogus": chr(0xE901)})
    state.apply_resolution(RelocatePin(cluster=cluster, codepoint=0xE902))
    assert state.relocations == {"bogus": chr(0xE901), "ข่": chr(0xE902)}
    assert state.effective_map()["ข่"] == chr(0xE902)
    assert "bogus" not in state.effective_map()
