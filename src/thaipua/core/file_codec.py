"""Encode and decode files between Thai text and PUA codepoints, routing by extension."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial
from pathlib import Path

from thaipua.core.constants import STRING_TABLE_EXTENSIONS
from thaipua.core.encoding import build_encode_transform, load_decode_table, load_encoding_map
from thaipua.core.string_table import StringEntry, StringTableError, parse_strings_file, write_strings_file
from thaipua.core.text_encoding import detect_text_encoding

logger = logging.getLogger(__name__)


def _encode_string_table_file(
    input_path: str | Path, output_path: str | Path, transform_text: Callable[[str], str]
) -> None:
    """Encode every string in a string table file and write the result."""
    parsed = parse_strings_file(input_path)
    for entry in parsed.entries:
        entry.string = transform_text(entry.string)
    _write_string_table_file(parsed.entries, output_path, parsed.encoding)


def _decode_string_table_file(input_path: str | Path, output_path: str | Path, decode_table: dict[int, str]) -> None:
    """Decode every string in a string table file and write the result."""
    parsed = parse_strings_file(input_path)
    for entry in parsed.entries:
        entry.string = entry.string.translate(decode_table)
    _write_string_table_file(parsed.entries, output_path, parsed.encoding)


def _write_string_table_file(entries_from_src: list[StringEntry], output_path: str | Path, encoding: str) -> None:
    """Write transformed entries in `encoding`, falling back to UTF-8 when unencodable."""
    try:
        write_strings_file(entries_from_src, output_path, encoding=encoding)
    except UnicodeEncodeError:
        logger.warning(
            "Transformed strings are not encodable as '%s'; writing '%s' as UTF-8 instead", encoding, output_path
        )
        write_strings_file(entries_from_src, output_path, encoding="utf-8")


def _process_text_file(input_path: Path, output_path: Path, transform_text: Callable[[str], str]) -> None:
    """Transform a plain-text file in its detected encoding, falling back to UTF-8 on write failure."""
    encoding = detect_text_encoding(input_path)
    logger.info("Processing file: '%s' (%s)", input_path, encoding)
    try:
        content = input_path.read_text(encoding=encoding)
        transformed = transform_text(content)
    except (OSError, UnicodeDecodeError):
        logger.exception("Failed to process '%s'", input_path)
        return
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
    else:
        logger.info("File written: '%s'", output_path)


def _process_files(
    target_files: list[str | Path],
    *,
    output_suffix: str,
    string_table_handler: Callable[[Path, Path], None],
    transform_text: Callable[[str], str],
) -> None:
    """Route each target file to the matching handler, writing `<stem>_<suffix><ext>` outputs.

    Missing files are skipped with a warning.
    """
    for target_path in target_files:
        input_path = Path(target_path)
        if not input_path.exists():
            logger.warning("Skipping missing file: '%s'", input_path)
            continue
        output_path = input_path.with_name(f"{input_path.stem}_{output_suffix}{input_path.suffix}")
        if input_path.suffix.upper() in STRING_TABLE_EXTENSIONS:
            logger.info("Processing string table file: '%s'", input_path)
            try:
                string_table_handler(input_path, output_path)
            except (OSError, StringTableError):
                logger.exception("Failed to process '%s'", input_path)
            else:
                logger.info("File written: '%s'", output_path)
        else:
            _process_text_file(input_path, output_path, transform_text)


def encode_files(map_path: str | Path, target_files: list[str | Path]) -> None:
    """Encode Thai text in each target file to PUA codepoints.

    Returns without writing when the mapping at `map_path` cannot be loaded.
    """
    encoding_map = load_encoding_map(map_path)
    if encoding_map is None:
        return
    transform_text = build_encode_transform(encoding_map)
    _process_files(
        target_files,
        output_suffix="encoded",
        string_table_handler=partial(_encode_string_table_file, transform_text=transform_text),
        transform_text=transform_text,
    )


def decode_files(map_path: str | Path, target_files: list[str | Path]) -> None:
    """Decode PUA codepoints in each target file back to Thai text.

    Returns without writing when the mapping at `map_path` cannot be loaded.
    """
    decode_table = load_decode_table(map_path)
    if decode_table is None:
        return
    _process_files(
        target_files,
        output_suffix="decoded",
        string_table_handler=partial(_decode_string_table_file, decode_table=decode_table),
        transform_text=lambda content: content.translate(decode_table),
    )
