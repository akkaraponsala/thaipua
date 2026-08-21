"""Parsing and building of Bethesda Creation Engine string table files.

Each table (.STRINGS, .DLSTRINGS, .ILSTRINGS) is a binary id -> string container
consisting of a fixed header, an (id, offset) directory, and a packed data block of
null-terminated or length-prefixed strings.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)
FileType = Literal["zstring", "length_prefixed"]
_LENGTH_PREFIXED_EXTS = {".DLSTRINGS", ".ILSTRINGS"}
_ZSTRING_EXTS = {".STRINGS"}
_HEADER_STRUCT = struct.Struct("<II")
_DIRECTORY_STRUCT = struct.Struct("<II")
_LENGTH_STRUCT = struct.Struct("<I")


class StringTableError(Exception):
    """Base error for string table parsing and building failures."""


class UnsupportedFormatError(StringTableError):
    """Raised when the string table format cannot be determined or is invalid."""


class CorruptedStringTableError(StringTableError):
    """Raised when a string table file's contents are malformed."""


@dataclass(slots=True)
class StringEntry:
    """One record from a Creation Engine string table.

    Attributes:
        id: The record identifier.
        offset: The byte offset of the string within the data block.
        string: The decoded string value.
    """

    id: int
    offset: int
    string: str


@dataclass(slots=True)
class ParsedStringTable:
    """A parsed string table and the codec used to decode its strings.

    Attributes:
        encoding: The codec that produced `entries` — utf-8 when every string decoded
            cleanly, otherwise the fallback codec that was used for the file's legacy
            (typically cp1252) bytes.
    """

    entries: list[StringEntry]
    encoding: str


def _resolve_file_type(file_path: str | Path, file_type: FileType | None = None) -> FileType:
    """Resolve the table format from an explicit file_type or from file_path's extension.

    Raises:
        UnsupportedFormatError: If file_type is invalid or the file extension is
            unrecognized.
    """
    if file_type is not None:
        if file_type not in ["zstring", "length_prefixed"]:
            raise UnsupportedFormatError(f"Invalid file_type '{file_type}' (expected 'zstring' or 'length_prefixed')")
        return file_type
    ext = Path(file_path).suffix.upper()
    if ext in _LENGTH_PREFIXED_EXTS:
        return "length_prefixed"
    if ext in _ZSTRING_EXTS:
        return "zstring"
    raise UnsupportedFormatError(
        f"Cannot determine string table format from extension '{ext}'. "
        f"Pass file_type='zstring' or file_type='length_prefixed' explicitly."
    )


def _decode_with_fallback(
    raw_bytes: bytes, *, primary_encoding: str = "utf-8", fallback_encoding: str = "cp1252"
) -> tuple[str, str]:
    """Decode raw_bytes, returning (text, encoding) where encoding was actually used.

    Decoding tries primary_encoding first. When that fails, raw_bytes are decoded via
    fallback_encoding (a legacy codepage such as cp1252).
    """
    try:
        return (raw_bytes.decode(primary_encoding), primary_encoding)
    except UnicodeDecodeError:
        logger.debug("%s decode failed, falling back to %s", primary_encoding, fallback_encoding)
        return (raw_bytes.decode(fallback_encoding), fallback_encoding)


def _extract_raw_bytes(data_block: bytes, string_offset: int, resolved_type: FileType, file_path: str | Path) -> bytes:
    """Return the raw string bytes at `string_offset` for the resolved table format.

    Raises:
        CorruptedStringTableError: The offset or declared length runs past the data
            block, the declared length field is invalid, or a zstring is unterminated.
    """
    if resolved_type == "zstring":
        terminator = data_block.find(b"\x00", string_offset)
        if terminator == -1:
            raise CorruptedStringTableError(f"Unterminated string at offset {string_offset} in '{file_path}'")
        return data_block[string_offset:terminator]
    if string_offset < 0 or string_offset + _LENGTH_STRUCT.size > len(data_block):
        raise CorruptedStringTableError(
            f"Length prefix at offset {string_offset} runs past the data block in '{file_path}'"
        )
    (length,) = _LENGTH_STRUCT.unpack_from(data_block, string_offset)
    if length < 1:
        raise CorruptedStringTableError(
            f"Invalid declared length field ({length}) at offset {string_offset} in '{file_path}'"
        )
    str_start = string_offset + _LENGTH_STRUCT.size
    str_end = str_start + length - 1
    if str_end > len(data_block):
        raise CorruptedStringTableError(
            f"String at offset {string_offset} (declared length {length}) exceeds the data block in '{file_path}'"
        )
    return data_block[str_start:str_end]


def parse_strings_file(
    file_path: str | Path, *, file_type: FileType | None = None, fallback_encoding: str = "cp1252"
) -> ParsedStringTable:
    """Parse a string table file into a `ParsedStringTable` (directory order preserved).

    Strings decode as UTF-8, falling back to `fallback_encoding` for bytes that are not
    valid UTF-8; `ParsedStringTable.encoding` reports which codec was used. Entries
    sharing an offset share the same decoded `string` value.

    Args:
        file_type: When `None`, inferred from the file extension.

    Raises:
        CorruptedStringTableError: Header or declared sizes are inconsistent with the
            file's actual contents.
        UnsupportedFormatError: Format cannot be resolved.
    """
    resolved_type = _resolve_file_type(file_path, file_type)
    data = Path(file_path).read_bytes()
    if len(data) < _HEADER_STRUCT.size:
        raise CorruptedStringTableError(f"File too small to contain a valid header: '{file_path}'")
    count, data_size = _HEADER_STRUCT.unpack_from(data, 0)
    directory_start = _HEADER_STRUCT.size
    directory_end = directory_start + count * _DIRECTORY_STRUCT.size
    if directory_end > len(data):
        raise CorruptedStringTableError(f"Declared entry count ({count}) exceeds file size: '{file_path}'")
    directory = [
        _DIRECTORY_STRUCT.unpack_from(data, directory_start + i * _DIRECTORY_STRUCT.size) for i in range(count)
    ]
    data_block = data[directory_end : directory_end + data_size]
    if len(data_block) != data_size:
        logger.warning(
            "Declared data size (%d) does not match remaining bytes (%d) in '%s'",
            data_size,
            len(data_block),
            file_path,
        )
    offset_cache: dict[int, str] = {}
    entries = []
    file_encoding = "utf-8"
    for string_id, string_offset in directory:
        if string_offset in offset_cache:
            string_value = offset_cache[string_offset]
        else:
            raw_bytes = _extract_raw_bytes(data_block, string_offset, resolved_type, file_path)
            string_value, used_encoding = _decode_with_fallback(raw_bytes, fallback_encoding=fallback_encoding)
            if used_encoding != "utf-8":
                file_encoding = used_encoding
            offset_cache[string_offset] = string_value
        entries.append(StringEntry(id=string_id, offset=string_offset, string=string_value))
    return ParsedStringTable(entries=entries, encoding=file_encoding)


def write_strings_file(
    entries: list[StringEntry], file_path: str | Path, *, file_type: FileType | None = None, encoding: str = "utf-8"
) -> Path:
    """Build a string table file from `entries`, preserving directory order.

    Each entry's `offset` field is ignored: offsets are recomputed, and identical
    strings are deduplicated into a single data-block entry. Pass
    `ParsedStringTable.encoding` to keep the output on the same on-disk codec as the
    source. Parent directories of `file_path` are created as needed.

    Args:
        file_type: When `None`, inferred from the file extension.

    Returns:
        The path written to.
    """
    resolved_type = _resolve_file_type(file_path, file_type)
    string_to_offset: dict[str, int] = {}
    data_chunks = []
    directory = []
    current_offset = 0
    for entry in entries:
        if entry.string in string_to_offset:
            string_offset = string_to_offset[entry.string]
        else:
            raw_bytes = entry.string.encode(encoding) + b"\x00"
            chunk = _LENGTH_STRUCT.pack(len(raw_bytes)) + raw_bytes if resolved_type == "length_prefixed" else raw_bytes
            string_offset = current_offset
            string_to_offset[entry.string] = string_offset
            data_chunks.append(chunk)
            current_offset += len(chunk)
        directory.append((entry.id, string_offset))
    data_block = b"".join(data_chunks)
    header = _HEADER_STRUCT.pack(len(directory), len(data_block))
    directory_bytes = b"".join((_DIRECTORY_STRUCT.pack(sid, off) for sid, off in directory))
    output_path = Path(file_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(header + directory_bytes + data_block)
    return output_path
