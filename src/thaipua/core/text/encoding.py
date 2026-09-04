"""Thai-to-PUA encoding maps and text transforms."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from thaipua.core.constants import SARA_AM_REPLACEMENTS
from thaipua.core.domain.cluster import canonical_cluster_text
from thaipua.core.domain.thai import NEEDS_SHAPER
from thaipua.core.pua_map import load_pua_map_dict

logger = logging.getLogger(__name__)

NEEDS_SHAPER_CHARS: frozenset[str] = frozenset(chr(code) for code in NEEDS_SHAPER)
"""Characters whose ink overlaps neighbors without a shaper; outside the cluster model by design."""


@dataclass(slots=True, frozen=True)
class PuaEncodingMap:
    """Longest-match-first substitution pattern paired with its lookup table."""

    pattern: re.Pattern[str]
    table: dict[str, str]


def load_encoding_map(dict_path: str | Path) -> PuaEncodingMap | None:
    """Compile the mapping file into a longest-match-first encoder; return `None` when unavailable."""
    map_data = load_pua_map_dict(dict_path)
    if not map_data:
        return None
    sorted_keys = sorted(map_data.keys(), key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(key) for key in sorted_keys))
    logger.info("Encoding map loaded (%d patterns)", len(map_data))
    return PuaEncodingMap(pattern=pattern, table=map_data)


def load_decode_table(dict_path: str | Path) -> dict[int, str] | None:
    """Invert the mapping file into a PUA-codepoint-to-Thai table; return `None` when unavailable."""
    data = load_pua_map_dict(dict_path)
    if not data:
        return None
    decode_table = {ord(pua_char): thai_text for thai_text, pua_char in data.items()}
    logger.info("Decoding map loaded (%d codepoints)", len(decode_table))
    return decode_table


def normalize_sara_am(content: str) -> str:
    """Rewrite SARA AM combinations into NIKHAHIT + SARA AA sequences."""
    for old_char, new_char in SARA_AM_REPLACEMENTS:
        content = content.replace(old_char, new_char)
    return content


def find_unshapable_spans(text: str) -> list[tuple[int, str]]:
    """Return `(offset, char)` for every character needing a shaper, in text order.

    The scan is purely about Unicode characters — it needs no encoding map, since
    the cluster model never attempts these characters in any map.
    """
    return [(index, char) for index, char in enumerate(text) if char in NEEDS_SHAPER_CHARS]


def _apply_encoding(content: str, encoding_map: PuaEncodingMap) -> str:
    """Normalize SARA AM forms and mark order, then substitute Thai clusters via `encoding_map`.

    Holes (legal grid combos excluded from the shipped map) partial-match by
    longest-match by design; the output still decodes back losslessly.
    """
    normalized = canonical_cluster_text(normalize_sara_am(content))
    return encoding_map.pattern.sub(lambda m: encoding_map.table[m.group(0)], normalized)


def build_encode_transform(encoding_map: PuaEncodingMap) -> Callable[[str], str]:
    """Return a callable that encodes Thai text to PUA codepoints via `encoding_map`."""
    return lambda content: _apply_encoding(content, encoding_map)
