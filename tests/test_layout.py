"""Unit tests for the deterministic Thai-cluster-to-PUA layout model."""

from __future__ import annotations

from pathlib import Path

from thaipua.core.constants import PUA_RANGE_END, PUA_RANGE_START
from thaipua.core.fonttools.occupancy import PuaOccupant
from thaipua.core.fonttools.ownership import SlotOwnership
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
from thaipua.core.pua_map import THAI_CONSONANTS, THAI_SUFFIXES


def test_cluster_ordinal_roundtrips_over_every_cluster() -> None:
    for ordinal in range(cluster_count()):
        assert cluster_ordinal(key_at_ordinal(ordinal)) == ordinal
    assert cluster_ordinal("x") is None
    assert cluster_ordinal("") is None


def test_canonical_layout_is_dense_and_deterministic() -> None:
    layout = canonical_layout(0xE000)
    assert len(layout) == cluster_count() == 2016
    assert sorted(ord(c) for c in layout.values()) == list(range(PUA_RANGE_START, PUA_RANGE_START + 2016))
    assert layout["กั"] == chr(0xE000)
    assert layout["ขั"] == chr(0xE000 + len(THAI_SUFFIXES))
    again = canonical_layout(0xE000)
    assert layout == again
    assert canonical_tail_start(0xE000) == PUA_RANGE_START + 2016


def test_canonical_codepoint_matches_first_consonant_block() -> None:
    first_key = f"{THAI_CONSONANTS[0]}{THAI_SUFFIXES[0]}"
    assert canonical_codepoint(first_key, DEFAULT_BASE_CODEPOINT) == DEFAULT_BASE_CODEPOINT


def test_effective_layout_applies_relocations_and_ignores_malformed() -> None:
    mapping = effective_layout(0xE000, {"ก่": chr(0xE900), "bogus": chr(0xE901)})
    assert mapping["ก่"] == chr(0xE900)
    assert "bogus" not in mapping


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


def test_find_conflicts_skips_resolved_codepoints() -> None:
    state = LayoutState()
    mapping = state.effective_map()
    resolved_cp = ord(mapping["กั"])
    other_cp = ord(mapping["ขั"])
    occupants = [
        PuaOccupant(resolved_cp, "logo", SlotOwnership.LOCKED, "simple glyph"),
        PuaOccupant(other_cp, "mark", SlotOwnership.LOCKED, "simple glyph"),
    ]
    conflicts = find_conflicts(mapping, occupants, resolved=frozenset({resolved_cp}))
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
    state = LayoutState(base=0xE100, relocations={"ก่": chr(0xE900)}, overrides=frozenset({0xE600, 0xE601}))
    save_layout_state(state, path)
    loaded = load_layout_state(path)
    assert loaded == state


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
