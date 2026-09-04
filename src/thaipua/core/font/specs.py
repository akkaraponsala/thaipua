"""Derive composite-glyph specifications from a Thai-to-PUA mapping."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass

from thaipua.core.domain import thai as _thai
from thaipua.core.domain.cluster import try_key

logger = logging.getLogger(__name__)

THAI_CONSONANTS: set[int] = {consonant.value for consonant in _thai.CONSONANTS}
BELOW_VOWELS: set[int] = set(_thai.BELOW_VOWELS)
ABOVE_VOWELS: set[int] = set(_thai.ABOVE_VOWELS)
TONE_MARKS: set[int] = set(_thai.TONE_MARKS)

# Protrusion direction scoping consonant self-substitutions; canonical home is
# domain.thai (only ascender consonants such as ฬ are listed — all others fall
# back to the generic context canonicalization).
CONSONANT_PROTRUSION: dict[int, str] = dict(_thai.CONSONANT_PROTRUSION)


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

    Parsing is role-based and order-insensitive, shared with every other entry
    point through `try_key` — the single home of the cluster classifier.
    Return `None` for empty text, non-consonant leads, unrecognized marks,
    duplicate roles, and below+above stacks; callers report the skip themselves.
    """
    cluster = try_key(thai_text)
    if cluster is None:
        return None
    return (
        cluster.consonant.value,
        cluster.below.value if cluster.below is not None else None,
        cluster.above.value if cluster.above is not None else None,
        cluster.tone.value if cluster.tone is not None else None,
    )


def iter_composite_specs(mapping: dict[str, str]) -> Iterator[CompositeSpec]:
    """Yield one `CompositeSpec` per valid mapping entry in insertion order, skipping malformed entries."""
    for thai_key, pua_char in mapping.items():
        if len(pua_char) != 1:
            logger.warning("Skipping mapping entry %r: PUA value %r is not single-char", thai_key, pua_char)
            continue
        decomposed = decompose_thai_cluster(thai_key)
        if decomposed is None:
            logger.warning("Skipping mapping entry %r: not a decomposable Thai cluster", thai_key)
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
