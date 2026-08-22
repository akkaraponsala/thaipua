"""Derive composite-glyph specifications from a Thai-to-PUA mapping."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass

logger = logging.getLogger(__name__)

THAI_CONSONANTS: set[int] = {ord(c) for c in "กขคฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ"}
BELOW_VOWELS: set[int] = {3640, 3641}
ABOVE_VOWELS: set[int] = {3633, 3636, 3661, 3637, 3638, 3655, 3639}
TONE_MARKS: set[int] = {3658, 3660, 3656, 3659, 3657}

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

    Return `None` when the text is empty or contains an unrecognized codepoint.
    """
    if not thai_text:
        return None
    codes = [ord(ch) for ch in thai_text]
    cons_uni = codes[0]
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
