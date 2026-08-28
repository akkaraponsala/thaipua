"""Derive composite-glyph specifications from a Thai-to-PUA mapping."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass

from thaipua.core.constants import THAI_CONSONANT_CHARS

logger = logging.getLogger(__name__)

THAI_CONSONANTS: set[int] = {ord(c) for c in THAI_CONSONANT_CHARS}
BELOW_VOWELS: set[int] = {0x0E38, 0x0E39}
ABOVE_VOWELS: set[int] = {0x0E31, 0x0E34, 0x0E35, 0x0E36, 0x0E37, 0x0E47, 0x0E4D}
TONE_MARKS: set[int] = {0x0E48, 0x0E49, 0x0E4A, 0x0E4B, 0x0E4C}

# Protrusion direction scoping consonant self-substitutions; only ascender
# consonants (e.g. ฬ) are listed — all others fall back to the generic context
# canonicalization.
CONSONANT_PROTRUSION: dict[int, str] = {
    ord("ฬ"): "ascender",
}


@dataclass(slots=True, frozen=True)
class CompositeSpec:
    """One composite glyph to build, derived from a mapping entry."""

    pua_code: int
    cons_uni: int
    below_uni: int | None = None
    above_uni: int | None = None
    tone_uni: int | None = None
    thai_key: str = ""


def decompose_thai_cluster(thai_text: str) -> tuple[int, int | None, int | None, int | None] | None:
    """Split a Thai cluster into `(cons_uni, below_uni, above_uni, tone_uni)`.

    Return `None` when the text is empty, does not start with a Thai consonant,
    or contains an unrecognized mark.
    """
    if not thai_text:
        return None
    codes = [ord(ch) for ch in thai_text]
    cons_uni = codes[0]
    if cons_uni not in THAI_CONSONANTS:
        logger.warning("Cannot decompose Thai cluster %r: U+%04X is not a Thai consonant", thai_text, cons_uni)
        return None
    below_uni = None
    above_uni = None
    tone_uni = None
    for code in codes[1:]:
        if code in BELOW_VOWELS:
            below_uni = code
        elif code in ABOVE_VOWELS:
            above_uni = code
        elif code in TONE_MARKS:
            tone_uni = code
        else:
            logger.warning(
                "Cannot decompose Thai cluster %r: U+%04X is not a recognized vowel or tone mark",
                thai_text,
                code,
            )
            return None
    return (cons_uni, below_uni, above_uni, tone_uni)


def iter_composite_specs(mapping: dict[str, str]) -> Iterator[CompositeSpec]:
    """Yield one `CompositeSpec` per valid mapping entry in insertion order, skipping malformed entries."""
    for thai_key, pua_char in mapping.items():
        if len(pua_char) != 1:
            logger.warning("Skipping mapping entry %r: PUA value %r is not single-char", thai_key, pua_char)
            continue
        decomposed = decompose_thai_cluster(thai_key)
        if decomposed is None:
            continue
        cons_uni, below_uni, above_uni, tone_uni = decomposed
        yield CompositeSpec(
            pua_code=ord(pua_char),
            cons_uni=cons_uni,
            below_uni=below_uni,
            above_uni=above_uni,
            tone_uni=tone_uni,
            thai_key=thai_key,
        )
