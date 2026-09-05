"""Encode and decode files between Thai text and PUA codepoints, routing by extension."""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from thaipua.core.constants import STRING_TABLE_EXTENSIONS
from thaipua.core.text.encoding import (
    build_encode_transform,
    find_unshapable_spans,
    load_decode_table,
    load_encoding_map,
)
from thaipua.core.text.string_table import StringEntry, StringTableError, parse_string_table, write_string_table
from thaipua.core.text.text_encoding import detect_text_encoding

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class UnshapableReport:
    """Strict-mode finding: a source file holding characters a PUA font cannot render."""

    source: str
    characters: tuple[str, ...]
    """Distinct offending characters in first-seen order."""

    occurrences: int
    """Total offending-character count across the file."""


def _report_for(source: str | Path, texts: Iterable[str]) -> UnshapableReport | None:
    """Fold strict-mode findings over `texts` into one report, or `None` when clean."""
    characters: list[str] = []
    occurrences = 0
    for text in texts:
        for _offset, char in find_unshapable_spans(text):
            if char not in characters:
                characters.append(char)
            occurrences += 1
    if not occurrences:
        return None
    report = UnshapableReport(source=str(source), characters=tuple(characters), occurrences=occurrences)
    logger.warning(
        "Strict mode: '%s' holds %d unshapable character(s) (%s); they pass through unencoded",
        report.source,
        report.occurrences,
        "".join(report.characters),
    )
    return report


def _encode_string_table_file(
    input_path: str | Path,
    output_path: str | Path,
    transform_text: Callable[[str], str],
    *,
    strict: bool = False,
) -> UnshapableReport | None:
    """Encode every string in a string table file and write the result."""
    parsed = parse_string_table(input_path)
    report: UnshapableReport | None = None
    if strict:
        report = _report_for(input_path, [entry.string for entry in parsed.entries])
    for entry in parsed.entries:
        entry.string = transform_text(entry.string)
    _write_string_table_file(parsed.entries, output_path, parsed.encoding)
    return report


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


def _transform_text_file(
    input_path: Path, output_path: Path, transform_text: Callable[[str], str], *, strict: bool = False
) -> tuple[bool, UnshapableReport | None]:
    """Transform a plain-text file in its detected encoding, falling back to UTF-8 on write failure.

    Return whether an output file was written, plus the strict-mode report when requested.
    """
    encoding = detect_text_encoding(input_path)
    logger.info("Processing file: '%s' (%s)", input_path, encoding)
    try:
        content = input_path.read_text(encoding=encoding)
        transformed = transform_text(content)
    except OSError, UnicodeDecodeError:
        logger.exception("Failed to process '%s'", input_path)
        return (False, None)
    report = _report_for(input_path, [content]) if strict else None
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
        return (False, None)
    else:
        logger.info("File written: '%s'", output_path)
    return (True, report)


def _route_files(
    target_files: list[str | Path],
    *,
    output_suffix: str,
    string_table_handler: Callable[[Path, Path], UnshapableReport | None],
    transform_text: Callable[[str], str],
    strict: bool = False,
) -> tuple[int, int, list[UnshapableReport]]:
    """Route each target file to the matching handler, writing `<stem>_<suffix><ext>` outputs.

    Return `(written, failed, unshapable)`; missing and unreadable files count as failed.
    """
    written = 0
    failed = 0
    unshapable: list[UnshapableReport] = []
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
                report = string_table_handler(input_path, output_path)
            except OSError, StringTableError:
                logger.exception("Failed to process '%s'", input_path)
                failed += 1
            else:
                logger.info("File written: '%s'", output_path)
                written += 1
                if report is not None:
                    unshapable.append(report)
        else:
            ok, report = _transform_text_file(input_path, output_path, transform_text, strict=strict)
            if ok:
                written += 1
                if report is not None:
                    unshapable.append(report)
            else:
                failed += 1
    return (written, failed, unshapable)


def encode_files(
    map_path: str | Path, target_files: list[str | Path], *, strict: bool = False
) -> tuple[int, int, list[UnshapableReport]]:
    """Encode Thai text in each target file to PUA codepoints.

    Return `(written, failed, unshapable)`; `(0, len(target_files), [])` when the
    mapping cannot load. With `strict=True`, files holding characters a PUA font
    cannot render are additionally reported instead of passing silently.
    """
    encoding_map = load_encoding_map(map_path)
    if encoding_map is None:
        return (0, len(target_files), [])
    transform_text = build_encode_transform(encoding_map)
    return _route_files(
        target_files,
        output_suffix="encoded",
        string_table_handler=partial(_encode_string_table_file, transform_text=transform_text, strict=strict),
        transform_text=transform_text,
        strict=strict,
    )


def decode_files(map_path: str | Path, target_files: list[str | Path]) -> tuple[int, int]:
    """Decode PUA codepoints in each target file back to Thai text.

    Return `(written, failed)`; `(0, len(target_files))` when the mapping cannot load.
    """
    decode_table = load_decode_table(map_path)
    if decode_table is None:
        return (0, len(target_files))

    def _decode_table_handler(input_path: Path, output_path: Path) -> None:
        _decode_string_table_file(input_path, output_path, decode_table)

    written, failed, _no_reports = _route_files(
        target_files,
        output_suffix="decoded",
        string_table_handler=_decode_table_handler,
        transform_text=lambda content: content.translate(decode_table),
    )
    return (written, failed)
