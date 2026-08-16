"""Unit tests for PUA codepoint allocation and collision reallocation."""

from __future__ import annotations

from pathlib import Path

import pytest

from thaipua.core.constants import PUA_RANGE_END, PUA_RANGE_START
from thaipua.core.encoding import load_pua_map_dict
from thaipua.core.pua_allocator import (
    THAI_CONSONANTS,
    THAI_SUFFIXES,
    extend_pua_mapping,
    reallocate_colliding_entries,
)


def test_reallocate_colliding_entries_returns_a_copy_when_nothing_occupied() -> None:
    mapping = {"ก": chr(0xE000), "ข": chr(0xE001)}
    result = reallocate_colliding_entries(mapping, set())
    assert result == mapping
    assert result is not mapping


def test_reallocate_colliding_entries_reassigns_only_colliding_values() -> None:
    mapping = {"ก": chr(0xE000), "ข": chr(0xE001), "ค": chr(0xE002)}
    result = reallocate_colliding_entries(mapping, {chr(0xE001)}, start_pua=0xE000)
    assert result == {"ก": chr(0xE000), "ข": chr(0xE003), "ค": chr(0xE002)}


def test_reallocate_colliding_entries_reassigns_full_overlap() -> None:
    mapping = {"ก": chr(0xE000), "ข": chr(0xE001)}
    result = reallocate_colliding_entries(mapping, {chr(0xE000), chr(0xE001)}, start_pua=0xE000)
    assert set(result.values()) == {chr(0xE002), chr(0xE003)}


def test_reallocate_colliding_entries_skips_surviving_values() -> None:
    mapping = {"ก": chr(0xE000), "ข": chr(0xE003)}
    result = reallocate_colliding_entries(mapping, {chr(0xE000)}, start_pua=0xE000)
    assert result["ข"] == chr(0xE003)
    assert result["ก"] == chr(0xE001)


def test_reallocate_colliding_entries_raises_when_range_exhausted() -> None:
    mapping = {"ก": chr(0xE000), "ข": chr(0xE001)}
    all_pua = {chr(cp) for cp in range(PUA_RANGE_START, PUA_RANGE_END + 1)}
    with pytest.raises(RuntimeError):
        reallocate_colliding_entries(mapping, all_pua, start_pua=0xE000)


def test_extend_pua_mapping_reserves_reserved_codepoints(tmp_path: Path) -> None:
    map_path = tmp_path / "pua.json"
    reserved = {chr(0xE000), chr(0xE001), chr(0xE0FF)}
    extend_pua_mapping(THAI_SUFFIXES, filename=str(map_path), reserved_pua_chars=reserved)
    mapping = load_pua_map_dict(map_path)
    assert len(mapping) == len(THAI_CONSONANTS) * len(THAI_SUFFIXES)
    assert set(mapping.values()).isdisjoint(reserved)
    assert mapping["กั"] == chr(0xE002)
