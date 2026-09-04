"""Thai cluster model: the canonical domain unit for every map key."""

from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer, model_validator

from thaipua.core.domain.errors import ClusterError
from thaipua.core.domain.thai import CONSONANTS, AboveVowel, BelowVowel, Consonant, ToneMark


def _serialize_key(cluster: ThaiCluster) -> str:
    """Render a cluster as a sorted `U+XXXX+U+YYYY` string."""
    parts = [f"U+{cluster.consonant.value:04X}"]
    for mark in (cluster.below, cluster.above, cluster.tone):
        if mark is not None:
            parts.append(f"U+{mark.value:04X}")
    return "+".join(parts)


class ThaiCluster(BaseModel):
    """One consonant plus at most one below vowel, one above vowel, and one tone."""

    model_config = ConfigDict(frozen=True)

    consonant: Consonant
    below: BelowVowel | None = None
    above: AboveVowel | None = None
    tone: ToneMark | None = None

    @model_validator(mode="after")
    def _reject_below_above_stack(self) -> ThaiCluster:
        """Reject the below+above combination Thai typography never allows."""
        if self.below is not None and self.above is not None:
            raise ValueError("a cluster cannot stack a below vowel and an above vowel")
        return self

    @property
    def key(self) -> str:
        """Return the canonical mapping key: consonant char plus marks in codepoint order."""
        marks = [chr(m.value) for m in (self.below, self.above, self.tone) if m is not None]
        return chr(self.consonant.value) + "".join(sorted(marks, key=ord))

    @classmethod
    def from_key(cls, key: str) -> ThaiCluster:
        """Parse a mapping key into a cluster; raise `ClusterError` when illegal."""
        try:
            return _coerce_key(key)
        except ValueError as exc:
            raise ClusterError(str(exc)) from exc


def render_key(cluster: ThaiCluster) -> str:
    """Render a validated cluster in stored construction order (`below + above + tone`)."""
    parts = [chr(cluster.consonant.value)]
    for mark in (cluster.below, cluster.above, cluster.tone):
        if mark is not None:
            parts.append(chr(mark.value))
    return "".join(parts)


def _coerce_key(value: Any) -> ThaiCluster:
    """Coerce `str` mapping keys and dicts into a validated `ThaiCluster`."""
    if isinstance(value, ThaiCluster):
        return value
    if isinstance(value, dict):
        return ThaiCluster.model_validate(value)
    if not isinstance(value, str) or not value:
        raise ValueError(f"not a Thai cluster key: {value!r}")
    codes = [ord(ch) for ch in value]
    try:
        consonant = Consonant(codes[0])
    except ValueError:
        raise ValueError(f"not a Thai consonant: U+{codes[0]:04X}") from None
    below: BelowVowel | None = None
    above: AboveVowel | None = None
    tone: ToneMark | None = None
    for code in codes[1:]:
        if code in BelowVowel._value2member_map_:
            if below is not None:
                raise ValueError(f"duplicate below vowel in {value!r}")
            below = BelowVowel(code)
        elif code in AboveVowel._value2member_map_:
            if above is not None:
                raise ValueError(f"duplicate above vowel in {value!r}")
            above = AboveVowel(code)
        elif code in ToneMark._value2member_map_:
            if tone is not None:
                raise ValueError(f"duplicate tone mark in {value!r}")
            tone = ToneMark(code)
        else:
            raise ValueError(f"unrecognized mark U+{code:04X} in {value!r}")
    return ThaiCluster(consonant=consonant, below=below, above=above, tone=tone)


ThaiKey = Annotated[ThaiCluster, BeforeValidator(_coerce_key), PlainSerializer(_serialize_key, when_used="json")]
"""Map-key type: invalid stacking is unconstructible instead of validated after the fact."""


def try_key(value: str) -> ThaiCluster | None:
    """Parse untrusted input leniently, returning `None` for the caller to report."""
    try:
        return _coerce_key(value)
    except ValueError:
        return None


def _classify_marks(codes: list[int]) -> tuple[int | None, int | None, int | None] | None:
    """Split mark codepoints into `(below, above, tone)` roles; `None` when illegal."""
    below: int | None = None
    above: int | None = None
    tone: int | None = None
    for code in codes:
        if code in BelowVowel._value2member_map_:
            if below is not None:
                return None
            below = code
        elif code in AboveVowel._value2member_map_:
            if above is not None:
                return None
            above = code
        elif code in ToneMark._value2member_map_:
            if tone is not None:
                return None
            tone = code
        else:
            return None
    if below is not None and above is not None:
        return None
    return (below, above, tone)


def canonical_suffix(suffix: str) -> str | None:
    """Normalize a mark suffix to construction order (`below + above + tone`); `None` when illegal.

    Stored keys already use this form — the grid generates it positionally and the
    shipped table never deviates — so normalization is idempotent over every live
    key. Entry points accept marks in any order and canonicalize here instead of
    rejecting valid-but-reordered input.
    """
    if not suffix:
        return ""
    classified = _classify_marks([ord(char) for char in suffix])
    if classified is None:
        return None
    return "".join(chr(code) for code in classified if code is not None)


def canonical_cluster_key(key: str) -> str | None:
    """Normalize a full cluster key to stored form; `None` when not a legal cluster."""
    if not key:
        return None
    try:
        Consonant(ord(key[0]))
    except ValueError:
        return None
    suffix = canonical_suffix(key[1:])
    return None if suffix is None else key[0] + suffix


_CONSONANT_CLASS = "".join(chr(c.value) for c in CONSONANTS)
_MARK_CLASS = "".join(
    [chr(v.value) for v in BelowVowel] + [chr(v.value) for v in AboveVowel] + [chr(v.value) for v in ToneMark]
)
_CLUSTER_RUN_RE = re.compile(f"([{_CONSONANT_CLASS}])([{_MARK_CLASS}]+)")


def canonical_cluster_text(text: str) -> str:
    """Reorder stacked marks to construction order inside every consonant-led run.

    Runs that are illegal (duplicate roles, below+above stacks, stray marks) pass
    through untouched, preserving the encoder's current behavior for them. The
    rewrite is a pure permutation, so offsets elsewhere in the string are stable.
    """
    return _CLUSTER_RUN_RE.sub(
        lambda m: m.group(1) + suffix if (suffix := canonical_suffix(m.group(2))) is not None else m.group(0),
        text,
    )
