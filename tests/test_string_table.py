"""Unit tests for Bethesda string-table parsing, building, and corruption handling."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import cast

import pytest

from thaipua.core.string_table import (
    CorruptedStringTableError,
    FileType,
    StringEntry,
    UnsupportedFormatError,
    parse_string_table,
    write_string_table,
)


def _pack_raw_table(directory: list[tuple[int, int]], data_block: bytes) -> bytes:
    header = struct.pack("<II", len(directory), len(data_block))
    dir_bytes = b"".join(struct.pack("<II", string_id, offset) for string_id, offset in directory)
    return header + dir_bytes + data_block


def test_roundtrip_zstring(tmp_path: Path) -> None:
    path = tmp_path / "mod.strings"
    entries = [StringEntry(id=1, offset=0, string="hello"), StringEntry(id=2, offset=0, string="world")]
    write_string_table(entries, path)
    parsed = parse_string_table(path)
    assert [(entry.id, entry.string) for entry in parsed.entries] == [(1, "hello"), (2, "world")]
    assert parsed.encoding == "utf-8"


def test_roundtrip_length_prefixed(tmp_path: Path) -> None:
    path = tmp_path / "mod.dlstrings"
    entries = [StringEntry(id=1, offset=0, string="hello"), StringEntry(id=2, offset=0, string="world")]
    write_string_table(entries, path)
    parsed = parse_string_table(path)
    assert [(entry.id, entry.string) for entry in parsed.entries] == [(1, "hello"), (2, "world")]
    assert parsed.encoding == "utf-8"


def test_explicit_file_type_overrides_extension(tmp_path: Path) -> None:
    path = tmp_path / "table.bin"
    entries = [StringEntry(id=7, offset=0, string="abc")]
    write_string_table(entries, path, file_type="length_prefixed")
    parsed = parse_string_table(path, file_type="length_prefixed")
    assert parsed.entries[0].string == "abc"
    with pytest.raises(UnsupportedFormatError):
        parse_string_table(path)


def test_unknown_extension_raises(tmp_path: Path) -> None:
    path = tmp_path / "table.txt"
    path.write_bytes(b"")
    with pytest.raises(UnsupportedFormatError):
        parse_string_table(path)


def test_invalid_explicit_type_raises(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedFormatError):
        parse_string_table(tmp_path / "mod.strings", file_type=cast("FileType", "bogus"))


def test_shared_offset_yields_same_value(tmp_path: Path) -> None:
    path = tmp_path / "mod.strings"
    path.write_bytes(_pack_raw_table([(10, 0), (20, 0)], b"hi\x00"))
    parsed = parse_string_table(path)
    assert [entry.string for entry in parsed.entries] == ["hi", "hi"]


def test_write_dedupes_identical_strings(tmp_path: Path) -> None:
    path = tmp_path / "mod.dlstrings"
    entries = [StringEntry(id=1, offset=0, string="dup"), StringEntry(id=2, offset=0, string="dup")]
    write_string_table(entries, path)
    parsed = parse_string_table(path)
    assert parsed.entries[0].offset == parsed.entries[1].offset


def test_cp1252_fallback_reports_used_codec(tmp_path: Path) -> None:
    path = tmp_path / "mod.strings"
    path.write_bytes(_pack_raw_table([(1, 0)], b"caf\xe9\x00"))
    parsed = parse_string_table(path)
    assert parsed.entries[0].string == "café"
    assert parsed.encoding == "cp1252"


def test_too_small_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "mod.strings"
    path.write_bytes(b"abc")
    with pytest.raises(CorruptedStringTableError):
        parse_string_table(path)


def test_entry_count_exceeding_file_size_raises(tmp_path: Path) -> None:
    path = tmp_path / "mod.strings"
    path.write_bytes(struct.pack("<II", 10, 0))
    with pytest.raises(CorruptedStringTableError):
        parse_string_table(path)


def test_unterminated_zstring_raises(tmp_path: Path) -> None:
    path = tmp_path / "mod.strings"
    path.write_bytes(_pack_raw_table([(1, 0)], b"abc"))
    with pytest.raises(CorruptedStringTableError):
        parse_string_table(path)


def test_zero_length_prefix_raises(tmp_path: Path) -> None:
    path = tmp_path / "mod.dlstrings"
    path.write_bytes(_pack_raw_table([(1, 0)], struct.pack("<I", 0)))
    with pytest.raises(CorruptedStringTableError):
        parse_string_table(path)


def test_length_running_past_data_block_raises(tmp_path: Path) -> None:
    path = tmp_path / "mod.dlstrings"
    path.write_bytes(_pack_raw_table([(1, 0)], struct.pack("<I", 9) + b"ab"))
    with pytest.raises(CorruptedStringTableError):
        parse_string_table(path)
