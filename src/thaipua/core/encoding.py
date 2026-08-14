"""Thai-to-PUA encoding maps and text transforms."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from thaipua.core.constants import SARA_AM_REPLACEMENTS

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class PuaEncodingMap:
    """A longest-match-first PUA substitution pattern paired with its lookup table."""

    pattern: re.Pattern[str]
    table: dict[str, str]


def detect_text_encoding(file_path: str | Path) -> str:
    """Detect a text file's encoding from its byte-order mark and content.

    BOM-prefixed files resolve to the matching UTF codec. BOM-less files are utf-8
    when their bytes are valid UTF-8, otherwise cp1252 — the legacy codepage many mod
    text files are authored in.
    """
    raw = Path(file_path).read_bytes()
    if raw.startswith(b"\xff\xfe\x00\x00"):
        return "utf-32-le"
    if raw.startswith(b"\x00\x00\xfe\xff"):
        return "utf-32-be"
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return "cp1252"
    return "utf-8"


def load_pua_map_dict(dict_path: str | Path) -> dict[str, str]:
    """Read a Thai-to-PUA JSON mapping file.

    Returns an empty dict when the file is missing or cannot be parsed. Entries whose
    key is not a non-empty string, or whose value is not a single PUA character, are
    logged and skipped — never coerced, since a `str()`-cast literal like "57345"
    would silently break the encode and decode tables downstream.
    """
    logger.info("Loading PUA map: '%s'", dict_path)
    path = Path(dict_path)
    if not path.exists():
        logger.error("Map file not found: '%s'", dict_path)
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to parse map file: '%s'", dict_path)
        return {}
    if not isinstance(raw, dict):
        return {}
    mapping = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            logger.warning("Skipping map entry %r: key is not a non-empty string", key)
            continue
        if not isinstance(value, str) or len(value) != 1:
            logger.warning("Skipping map entry %r: value %r is not a single PUA character", key, value)
            continue
        mapping[key] = value
    return mapping


def load_encoding_map(dict_path: str | Path) -> PuaEncodingMap | None:
    """Compile a Thai-to-PUA JSON map into a longest-match-first substitution pattern.

    Returns `None` when the map cannot be loaded.
    """
    map_data = load_pua_map_dict(dict_path)
    if not map_data:
        return None
    sorted_keys = sorted(map_data.keys(), key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(key) for key in sorted_keys))
    logger.info("Encoding map loaded (%d patterns)", len(map_data))
    return PuaEncodingMap(pattern=pattern, table=map_data)


def load_decode_table(dict_path: str | Path) -> dict[int, str] | None:
    """Invert a Thai-to-PUA JSON map into a PUA-codepoint-to-Thai decode table.

    Returns `None` when the map cannot be loaded.
    """
    data = load_pua_map_dict(dict_path)
    if not data:
        return None
    decode_table = {ord(pua_char): thai_text for thai_text, pua_char in data.items()}
    logger.info("Decoding map loaded (%d codepoints)", len(decode_table))
    return decode_table


def normalize_sara_am(content: str) -> str:
    """Rewrite SARA AM combinations in content into NIKHAHIT + SARA AA sequences.

    Flattening the precomposed SARA AM (U+0E33) and its tone-bearing variants into the
    two-codepoint form lets them match the individual entries in a PUA mapping.
    """
    for old_char, new_char in SARA_AM_REPLACEMENTS:
        content = content.replace(old_char, new_char)
    return content


def _apply_encoding(content: str, encoding_map: PuaEncodingMap) -> str:
    """Normalize SARA AM forms in content and substitute Thai clusters via encoding_map."""
    normalized = normalize_sara_am(content)
    return encoding_map.pattern.sub(lambda m: encoding_map.table[m.group(0)], normalized)


def build_encode_transform(encoding_map: PuaEncodingMap) -> Callable[[str], str]:
    """Return a callable that encodes Thai text to PUA codepoints via encoding_map."""
    return lambda content: _apply_encoding(content, encoding_map)
