"""Integration tests for the file encode/decode pipeline over text and string tables."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from thaipua.core.text.file_codec import decode_files, encode_files
from thaipua.core.text.string_table import StringEntry, parse_string_table, write_string_table


def _write_map(tmp_path: Path, mapping: dict[str, str]) -> Path:
    map_path = tmp_path / "pua.json"
    map_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    return map_path


def test_encode_then_decode_text_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "story.txt"
    source.write_text("กากา", encoding="utf-8")
    map_path = _write_map(tmp_path, {"กา": "\ue000"})
    encode_files(map_path, [source])
    encoded = tmp_path / "story_encoded.txt"
    assert encoded.read_text(encoding="utf-8") == "\ue000\ue000"
    decode_files(map_path, [encoded])
    decoded = tmp_path / "story_encoded_decoded.txt"
    assert decoded.read_text(encoding="utf-8") == "กากา"


def test_encode_routes_string_table_by_extension(tmp_path: Path) -> None:
    source = tmp_path / "mod.dlstrings"
    write_string_table([StringEntry(id=1, offset=0, string="กา")], source)
    encode_files(_write_map(tmp_path, {"กา": "\ue000"}), [source])
    parsed = parse_string_table(tmp_path / "mod_encoded.dlstrings")
    assert [entry.string for entry in parsed.entries] == ["\ue000"]


def test_text_output_falls_back_to_utf8_for_cp1252_source(tmp_path: Path) -> None:
    source = tmp_path / "menu.txt"
    source.write_bytes(b"caf\xe9")
    encode_files(_write_map(tmp_path, {"é": "\ue000"}), [source])
    output = tmp_path / "menu_encoded.txt"
    assert output.exists()
    assert output.read_text(encoding="utf-8") == "caf\ue000"


def test_string_table_output_falls_back_to_utf8_for_cp1252_source(tmp_path: Path) -> None:
    source = tmp_path / "mod.strings"
    directory = struct.pack("<II", 1, 5) + struct.pack("<II", 1, 0)
    source.write_bytes(directory + b"caf\xe9\x00")
    encode_files(_write_map(tmp_path, {"é": "\ue000"}), [source])
    parsed = parse_string_table(tmp_path / "mod_encoded.strings")
    assert [entry.string for entry in parsed.entries] == ["caf\ue000"]
    assert parsed.encoding == "utf-8"


def test_missing_target_is_skipped(tmp_path: Path) -> None:
    encode_files(_write_map(tmp_path, {"กา": "\ue000"}), [tmp_path / "ghost.txt"])
    assert not any(tmp_path.glob("*_encoded*"))


def test_unloadable_map_writes_nothing(tmp_path: Path) -> None:
    target = tmp_path / "story.txt"
    target.write_text("กากา", encoding="utf-8")
    missing_map = tmp_path / "missing.json"
    encode_files(missing_map, [target])
    decode_files(missing_map, [target])
    assert not any(tmp_path.glob("*_encoded*"))
    assert not any(tmp_path.glob("*_decoded*"))


def test_corrupted_string_table_is_swallowed(tmp_path: Path) -> None:
    source = tmp_path / "broken.strings"
    source.write_bytes(b"abc")
    encode_files(_write_map(tmp_path, {"กา": "\ue000"}), [source])
    assert not any(tmp_path.glob("*_encoded*"))
