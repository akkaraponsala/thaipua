"""Parse and build Bethesda Creation Engine string table files (.STRINGS/.DLSTRINGS/.ILSTRINGS)."""

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
    """One id-offset-string record from a string table."""

    id: int
    offset: int
    string: str


@dataclass(slots=True)
class ParsedStringTable:
    """Parsed entries plus the codec that decoded them."""

    entries: list[StringEntry]
    encoding: str


def _resolve_file_type(file_path: str | Path, file_type: FileType | None = None) -> FileType:
    """Infer the table format from the file extension, or validate an explicit type."""
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
    """Decode bytes preferring the primary encoding; return the text plus the codec used."""
    try:
        return (raw_bytes.decode(primary_encoding), primary_encoding)
    except UnicodeDecodeError:
        logger.debug("%s decode failed, falling back to %s", primary_encoding, fallback_encoding)
        return (raw_bytes.decode(fallback_encoding), fallback_encoding)


def _extract_raw_bytes(data_block: bytes, string_offset: int, resolved_type: FileType, file_path: str | Path) -> bytes:
    """Read one string's bytes at `string_offset` according to the table format."""
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


def parse_string_table(
    file_path: str | Path, *, file_type: FileType | None = None, fallback_encoding: str = "cp1252"
) -> ParsedStringTable:
    """Parse a string table into ordered entries, decoding UTF-8 with a legacy fallback.

    Entries sharing an offset share the same decoded value.
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


def write_string_table(
    entries: list[StringEntry], file_path: str | Path, *, file_type: FileType | None = None, encoding: str = "utf-8"
) -> Path:
    """Write entries as a string table, deduplicating identical strings and recomputing offsets.

    Pass `ParsedStringTable.encoding` to keep the source's on-disk codec.
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
