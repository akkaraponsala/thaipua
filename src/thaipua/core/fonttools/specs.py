"""Derive composite-glyph specs from a Thai-to-PUA JSON mapping.

Each mapping key is a consonant plus one or more combining marks, and its value is the
single PUA codepoint the cluster should render as. `iter_composite_specs` splits each
key into the consonant, below-vowel, above-vowel, and tone-mark codepoints consumed by
`ThaiPuaFontGenerator.create_composite`, so glyph generation is driven entirely by the
mapping file.

SARA AM (U+0E33) is expected to be normalized upstream (see
`thaipua.core.encoding.normalize_sara_am`) into NIKKHIT (U+0E4D) followed by SARA AA
(U+0E32), so SARA AA never appears in a composite key. THANTHAKHAT (U+0E4C) is treated
as a tone mark because, like the four tone marks, it stacks above a vowel.

The four `THAI_CONSONANTS` / `BELOW_VOWELS` / `ABOVE_VOWELS` / `TONE_MARKS` sets
partition the codepoints covered by `iter_composite_specs` and supply the per-category
enumeration used by `thaipua.core.fonttools.alternates.find_glyph_substitutions`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass

logger = logging.getLogger(__name__)
THAI_CONSONANTS: set[int] = {ord(c) for c in "กขคฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ"}
BELOW_VOWELS: set[int] = {3640, 3641}
ABOVE_VOWELS: set[int] = {3633, 3636, 3661, 3637, 3638, 3655, 3639}
TONE_MARKS: set[int] = {3658, 3660, 3656, 3659, 3657}

# Direction of a consonant's protruding part, used to scope consonant self-
# substitutions: an "up" consonant (tail/loop extending above the base line, e.g. ฬ)
# must clear the stack above, so any above vowel or tone mark triggers its
# substitution. Only actively-substituted consonants are listed; all others
# (including the down-protruding descenders ญ ฐ ฎ ฏ) fall back to the generic
# tone-within-vowel-family canonicalisation, which keeps a below-vowel rule from
# firing in no-below-vowel clusters while leaving a below-plus-above cluster distinct.
CONSONANT_PROTRUSION: dict[int, str] = {
    ord("ฬ"): "up",
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
    """Split a Thai cluster into a base consonant and categorized mark codepoints.

    The first character is the base consonant. Any subsequent character that is not a
    recognized below-vowel, above-vowel, or tone-mark codepoint causes decomposition to
    fail.

    Returns:
        A `(cons_uni, below_uni, above_uni, tone_uni)` tuple, or `None` if `thai_text`
        is empty or contains an unrecognized codepoint.
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
    """Yield one `CompositeSpec` per entry of a Thai-to-PUA mapping.

    Entries whose PUA value is not a single character, or whose Thai key cannot be
    decomposed, are skipped with a warning.

    Yields:
        Composite specs in mapping (insertion) order.
    """
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
