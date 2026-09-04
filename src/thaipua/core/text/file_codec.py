"""Encode and decode files between Thai text and PUA codepoints, routing by extension."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial
from pathlib import Path

from thaipua.core.constants import STRING_TABLE_EXTENSIONS
from thaipua.core.text.encoding import build_encode_transform, load_decode_table, load_encoding_map
from thaipua.core.text.string_table import StringEntry, StringTableError, parse_string_table, write_string_table
from thaipua.core.text.text_encoding import detect_text_encoding

logger = logging.getLogger(__name__)


def _encode_string_table_file(
    input_path: str | Path, output_path: str | Path, transform_text: Callable[[str], str]
) -> None:
    """Encode every string in a string table file and write the result."""
    parsed = parse_string_table(input_path)
    for entry in parsed.entries:
        entry.string = transform_text(entry.string)
    _write_string_table_file(parsed.entries, output_path, parsed.encoding)


def _decode_string_table_file(input_path: str | Path, output_path: str | Path, decode_table: dict[int, str]) -> None:
    """Decode every string in a string table file and write the result."""
    parsed = parse_string_table(input_path)
    for entry in parsed.entries:
        entry.string = entry.string.translate(decode_table)
    _write_string_table_file(parsed.entries, output_path, parsed.encoding)


def _write_string_table_file(entries_from_src: list[StringEntry], output_path: str | Path, encoding: str) -> None:
    """Write transformed entries in `encoding`, falling back to UTF-8 when unencodable."""
    try:
        write_string_table(entries_from_src, output_path, encoding=encoding)
    except UnicodeEncodeError:
        logger.warning(
            "Transformed strings are not encodable as '%s'; writing '%s' as UTF-8 instead", encoding, output_path
        )
        write_string_table(entries_from_src, output_path, encoding="utf-8")


def _transform_text_file(input_path: Path, output_path: Path, transform_text: Callable[[str], str]) -> bool:
    """Transform a plain-text file in its detected encoding, falling back to UTF-8 on write failure.

    Return whether an output file was written.
    """
    encoding = detect_text_encoding(input_path)
    logger.info("Processing file: '%s' (%s)", input_path, encoding)
    try:
        content = input_path.read_text(encoding=encoding)
        transformed = transform_text(content)
    except (OSError, UnicodeDecodeError):
        logger.exception("Failed to process '%s'", input_path)
        return False
    try:
        output_path.write_text(transformed, encoding=encoding)
    except UnicodeEncodeError:
        logger.warning(
            "Transformed content cannot be encoded as '%s'; writing '%s' as UTF-8 instead",
            encoding,
            output_path,
        )
        output_path.write_text(transformed, encoding="utf-8")
    except OSError:
        logger.exception("Failed to write '%s'", output_path)
        return False
    else:
        logger.info("File written: '%s'", output_path)
    return True


def _route_files(
    target_files: list[str | Path],
    *,
    output_suffix: str,
    string_table_handler: Callable[[Path, Path], None],
    transform_text: Callable[[str], str],
) -> tuple[int, int]:
    """Route each target file to the matching handler, writing `<stem>_<suffix><ext>` outputs.

    Return `(written, failed)`; missing and unreadable files count as failed.
    """
    written = 0
    failed = 0
    for target_path in target_files:
        input_path = Path(target_path)
        if not input_path.exists():
            logger.warning("Skipping missing file: '%s'", input_path)
            failed += 1
            continue
        output_path = input_path.with_name(f"{input_path.stem}_{output_suffix}{input_path.suffix}")
        if input_path.suffix.upper() in STRING_TABLE_EXTENSIONS:
            logger.info("Processing string table file: '%s'", input_path)
            try:
                string_table_handler(input_path, output_path)
            except (OSError, StringTableError):
                logger.exception("Failed to process '%s'", input_path)
                failed += 1
            else:
                logger.info("File written: '%s'", output_path)
                written += 1
        elif _transform_text_file(input_path, output_path, transform_text):
            written += 1
        else:
            failed += 1
    return written, failed


def encode_files(map_path: str | Path, target_files: list[str | Path]) -> tuple[int, int]:
    """Encode Thai text in each target file to PUA codepoints.

    Return `(written, failed)`; `(0, len(target_files))` when the mapping cannot load.
    """
    encoding_map = load_encoding_map(map_path)
    if encoding_map is None:
        return (0, len(target_files))
    transform_text = build_encode_transform(encoding_map)
    return _route_files(
        target_files,
        output_suffix="encoded",
        string_table_handler=partial(_encode_string_table_file, transform_text=transform_text),
        transform_text=transform_text,
    )


def decode_files(map_path: str | Path, target_files: list[str | Path]) -> tuple[int, int]:
    """Decode PUA codepoints in each target file back to Thai text.

    Return `(written, failed)`; `(0, len(target_files))` when the mapping cannot load.
    """
    decode_table = load_decode_table(map_path)
    if decode_table is None:
        return (0, len(target_files))
    return _route_files(
        target_files,
        output_suffix="decoded",
        string_table_handler=partial(_decode_string_table_file, decode_table=decode_table),
        transform_text=lambda content: content.translate(decode_table),
    )
