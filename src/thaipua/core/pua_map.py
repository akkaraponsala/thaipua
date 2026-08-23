"""Thai cluster constants, PUA-map persistence, and free-codepoint search for relocations."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from thaipua.core.constants import PUA_RANGE_END

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
    """Return the lowest unused PUA codepoint at or above `start_pua`."""
    codepoint = start_pua
    while codepoint <= PUA_RANGE_END and chr(codepoint) in used_pua_chars:
        codepoint += 1
    if codepoint > PUA_RANGE_END:
        raise RuntimeError(f"No free PUA codepoint between U+{start_pua:04X} and U+{PUA_RANGE_END:04X}")
    return codepoint


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
