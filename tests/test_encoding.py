"""Unit tests for encoding-map loading, SARA AM normalization, and encode transforms."""

from __future__ import annotations

import json
from pathlib import Path

from thaipua.core.text.encoding import (
    build_encode_transform,
    load_decode_table,
    load_encoding_map,
    normalize_sara_am,
)


def _write_map(tmp_path: Path, mapping: dict[str, str], name: str = "pua.json") -> Path:
    map_path = tmp_path / name
    map_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    return map_path


def test_longest_match_wins_over_prefix(tmp_path: Path) -> None:
    encoding_map = load_encoding_map(_write_map(tmp_path, {"ก": "\ue001", "กั": "\ue000"}))
    assert encoding_map is not None
    transform = build_encode_transform(encoding_map)
    assert transform("กัก") == "\ue000\ue001"


def test_load_decode_table_inverts_mapping(tmp_path: Path) -> None:
    decode_table = load_decode_table(_write_map(tmp_path, {"กั": "\ue000"}))
    assert decode_table == {0xE000: "กั"}


def test_unusable_map_files_return_none(tmp_path: Path) -> None:
    empty_map = _write_map(tmp_path, {})
    broken_json = tmp_path / "broken.json"
    broken_json.write_text("{oops", encoding="utf-8")
    assert load_encoding_map(tmp_path / "missing.json") is None
    assert load_encoding_map(empty_map) is None
    assert load_encoding_map(broken_json) is None
    assert load_decode_table(empty_map) is None


def test_malformed_entries_are_skipped(tmp_path: Path) -> None:
    raw: dict[str, object] = {"": "\ue000", "กา": "XY", "ขา": 5, "คา": "\ue002"}
    map_path = tmp_path / "mixed.json"
    map_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    encoding_map = load_encoding_map(map_path)
    assert encoding_map is not None
    assert encoding_map.table == {"คา": "\ue002"}


def test_normalize_sara_am_base_and_tone_variants() -> None:
    assert normalize_sara_am("กำ") == "กํา"
    for tone in "่้๊๋":
        assert normalize_sara_am(f"ก{tone}ำ") == f"กํ{tone}า"


def test_encode_transform_normalizes_before_substituting(tmp_path: Path) -> None:
    mapping = {"ก": "\ue000", "ํ": "\ue001", "่": "\ue002", "า": "\ue003"}
    encoding_map = load_encoding_map(_write_map(tmp_path, mapping))
    assert encoding_map is not None
    transform = build_encode_transform(encoding_map)
    assert transform("ก่ำ") == "\ue000\ue001\ue002\ue003"
