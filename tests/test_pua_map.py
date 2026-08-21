"""Unit tests for PUA codepoint allocation."""

from __future__ import annotations

from pathlib import Path

from thaipua.core.encoding import load_pua_map_dict
from thaipua.core.pua_map import THAI_CONSONANTS, THAI_SUFFIXES, ensure_pua_map


def test_ensure_pua_map_reserves_reserved_codepoints(tmp_path: Path) -> None:
    map_path = tmp_path / "pua.json"
    reserved = {chr(0xE000), chr(0xE001), chr(0xE0FF)}
    ensure_pua_map(THAI_SUFFIXES, path=map_path, reserved_pua_chars=reserved)
    mapping = load_pua_map_dict(map_path)
    assert len(mapping) == len(THAI_CONSONANTS) * len(THAI_SUFFIXES)
    assert set(mapping.values()).isdisjoint(reserved)
    assert mapping["กั"] == chr(0xE002)
