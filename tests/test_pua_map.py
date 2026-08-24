"""Unit tests for PUA-map persistence and free-codepoint search."""

from __future__ import annotations

from pathlib import Path

import pytest

from thaipua.core.pua_map import load_pua_map_dict, next_free_codepoint, save_pua_map


def test_next_free_codepoint_skips_used_chars() -> None:
    used = {chr(0xE000), chr(0xE001), chr(0xE003)}
    assert next_free_codepoint(0xE000, used) == 0xE002
    assert next_free_codepoint(0xE002, used) == 0xE002


def test_save_pua_map_roundtrips(tmp_path: Path) -> None:
    map_path = tmp_path / "pua.json"
    mapping = {"กั": chr(0xE000)}
    save_pua_map(mapping, map_path)
    assert load_pua_map_dict(map_path) == mapping


def test_next_free_codepoint_raises_when_exhausted() -> None:
    full = {chr(cp) for cp in range(0xE7F0, 0xF900)}
    with pytest.raises(RuntimeError):
        next_free_codepoint(0xE7F0, full)
