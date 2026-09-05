"""Thai cluster constants, PUA-map persistence, and free-codepoint search for relocations."""

import logging
from pathlib import Path
from typing import Any

from thaipua.core.constants import PUA_RANGE_END
from thaipua.core.store.json_store import DiskJsonStore
from thaipua.core.store.ports import JsonStore

logger = logging.getLogger(__name__)

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


def parse_pua_map_payload(raw: Any) -> dict[str, str]:
    """Validate a decoded JSON document into a Thai-to-PUA map, skipping malformed entries."""
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


def load_pua_map_dict(dict_path: str | Path, *, store: JsonStore | None = None) -> dict[str, str]:
    """Read a Thai-to-PUA mapping file, skipping malformed entries; return an empty dict on failure."""
    logger.info("Loading PUA map: '%s'", dict_path)
    source = store if store is not None else DiskJsonStore()
    try:
        raw = source.load(dict_path)
    except FileNotFoundError:
        logger.error("Map file not found: '%s'", dict_path)
        return {}
    except OSError, ValueError:
        logger.exception("Failed to parse map file: '%s'", dict_path)
        return {}
    return parse_pua_map_payload(raw)


def next_free_codepoint(start_pua: int, used_pua_chars: set[str]) -> int:
    """Return the lowest unused PUA codepoint at or above `start_pua`."""
    codepoint = start_pua
    while codepoint <= PUA_RANGE_END and chr(codepoint) in used_pua_chars:
        codepoint += 1
    if codepoint > PUA_RANGE_END:
        raise RuntimeError(f"No free PUA codepoint between U+{start_pua:04X} and U+{PUA_RANGE_END:04X}")
    return codepoint


def save_pua_map(mapping: dict[str, str], path: str | Path, *, store: JsonStore | None = None) -> None:
    """Persist `mapping` to `path` as UTF-8 JSON.

    Write failures are logged rather than raised.
    """
    source = store if store is not None else DiskJsonStore()
    try:
        source.save(path, mapping)
        logger.info("Saved %d entries to %s", len(mapping), path)
    except OSError:
        logger.exception("Failed to write map file: %s", path)
