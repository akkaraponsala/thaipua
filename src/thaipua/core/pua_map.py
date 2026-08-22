"""PUA-map allocation and persistence for the Thai-to-PUA mapping file.

Allocates a PUA codepoint for every consonant plus vowel/tone suffix combination, with
one consonant's suffix variants occupying consecutive PUA codepoints so the mapping
stays deterministic across runs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from thaipua.core.constants import DEFAULT_PUA_MAP_PATH, PUA_RANGE_END, PUA_RANGE_START
from thaipua.core.encoding import load_pua_map_dict

logger = logging.getLogger(__name__)

THAI_CONSONANTS: str = "กขคฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ"
THAI_SUFFIXES: list[str] = [
    "ั",
    "ั่",
    "ั้",
    "ั๊",
    "ั๋",
    "ิ",
    "ิ่",
    "ิ้",
    "ิ๊",
    "ิ๋",
    "ิ์",
    "ี",
    "ี่",
    "ี้",
    "ี๊",
    "ี๋",
    "ึ",
    "ึ่",
    "ึ้",
    "ึ๊",
    "ึ๋",
    "ื",
    "ื่",
    "ื้",
    "ื๊",
    "ื๋",
    "ุ",
    "ุ่",
    "ุ้",
    "ุ๊",
    "ุ๋",
    "ุ์",
    "ู",
    "ู่",
    "ู้",
    "ู๊",
    "ู๋",
    "็",
    "่",
    "้",
    "๊",
    "๋",
    "์",
    "ํ",
    "ํ่",
    "ํ้",
    "ํ๊",
    "ํ๋",
]


def next_free_codepoint(start_pua: int, used_pua_chars: set[str]) -> int:
    """Find the lowest free PUA codepoint at or above `start_pua`.

    Raises:
        RuntimeError: Every codepoint from `start_pua` through `PUA_RANGE_END` is
            already in `used_pua_chars`.
    """
    codepoint = start_pua
    while codepoint <= PUA_RANGE_END and chr(codepoint) in used_pua_chars:
        codepoint += 1
    if codepoint > PUA_RANGE_END:
        raise RuntimeError(f"No free PUA codepoint between U+{start_pua:04X} and U+{PUA_RANGE_END:04X}")
    return codepoint


def allocate_consonant_block(
    consonant: str, suffixes: list[str], next_pua: int, used_pua_chars: set[str], mapped_thai_keys: set[str]
) -> tuple[dict[str, str], int]:
    """Allocate PUA codepoints for every suffix variant of one consonant.

    `used_pua_chars` is mutated in place as codepoints are allocated, and `next_pua` is
    advanced past each allocation. Keys already present in `mapped_thai_keys` are
    skipped individually.

    Returns:
        A tuple of (new Thai-key -> PUA-char entries, the next free codepoint after the
        block).

    Raises:
        RuntimeError: The next free codepoint falls past `PUA_RANGE_END`.
    """
    block_entries = {}
    for suffix in suffixes:
        thai_key = f"{consonant}{suffix}"
        if thai_key in mapped_thai_keys:
            logger.warning("Thai key %r already mapped. Skipping", thai_key)
            continue
        while next_pua <= PUA_RANGE_END and chr(next_pua) in used_pua_chars:
            next_pua += 1
        if next_pua > PUA_RANGE_END:
            raise RuntimeError(f"No free PUA codepoint between U+{next_pua:04X} and U+{PUA_RANGE_END:04X}")
        pua_char = chr(next_pua)
        block_entries[thai_key] = pua_char
        used_pua_chars.add(pua_char)
        next_pua += 1
    return (block_entries, next_pua)


def save_pua_map(mapping: dict[str, str], path: str | Path) -> None:
    """Persist `mapping` to `path` as UTF-8 JSON.

    Write failures are logged rather than raised.
    """
    try:
        with Path(path).open("w", encoding="utf-8") as handle:
            json.dump(mapping, handle, ensure_ascii=False, indent=4)
        logger.info("Saved %d entries to %s", len(mapping), path)
    except OSError:
        logger.exception("Failed to write map file: %s", path)


def ensure_pua_map(
    suffixes: list[str],
    path: str | Path = DEFAULT_PUA_MAP_PATH,
    start_pua: int = PUA_RANGE_START,
    reserved_pua_chars: set[str] | None = None,
) -> None:
    """Load the PUA mapping at `path` and extend it with new consonant/suffix entries.

    Walks `THAI_CONSONANTS` and `suffixes` in order, allocating consecutive PUA
    codepoints per consonant block from `start_pua`. Already-mapped keys are skipped
    individually. `reserved_pua_chars` are treated as in use by the allocation scan.
    """
    current_mapping = load_pua_map_dict(path)
    mapped_thai_keys = set(current_mapping.keys())
    used_pua_chars = set(current_mapping.values())
    if reserved_pua_chars:
        used_pua_chars.update(reserved_pua_chars)
    next_pua = next_free_codepoint(start_pua, used_pua_chars)
    new_entries = {}
    for consonant in THAI_CONSONANTS:
        block_entries, next_pua = allocate_consonant_block(
            consonant, suffixes, next_pua, used_pua_chars, mapped_thai_keys
        )
        new_entries.update(block_entries)
        mapped_thai_keys.update(block_entries.keys())
        logger.info("Consonant '%s' allocated (%d mappings)", consonant, len(block_entries))
    if not new_entries:
        logger.info("No new entries to save.")
        return
    current_mapping.update(new_entries)
    save_pua_map(current_mapping, path)
