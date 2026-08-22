"""PUA slot ownership classification for composite-glyph installs.

A PUA codepoint's cmap occupant is classified into one of `SlotOwnership` verdicts
from two signals:

- the glyph name carrying this tool's prefix (`TOOL_GLYPH_PREFIX`) — an authoritative
  ownership marker that survives font save/load,
- `glyf` composition — a composite glyph at a PUA slot is presumed to be stacking
  output from a similar tool, while anything else (an unknown simple glyph, a dangling
  cmap entry, or a font with no `glyf` table at all) may be irreplaceable foreign
  content.

The decision table (see `classify_pua_slot`):

==============  ==========  =========================================
Composite        Prefix      Verdict / action on install
==============  ==========  =========================================
(yes implied)    yes         OWNED — replace in place
yes              no          REPLACEABLE — replace foreign composite
no               no          LOCKED — unknown simple content, never overwrite
(any)            no          LOCKED when absent from `glyf` (dangling cmap)
(no glyf table)  no          LOCKED — defensive only; CFF sources are converted
                             to TrueType quadratics before reaching installs
==============  ==========  =========================================
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Protocol

logger = logging.getLogger(__name__)

TOOL_GLYPH_PREFIX = "thaipua_"


class SlotOwnership(Enum):
    """Ownership verdict for the glyph currently mapped at a PUA codepoint."""

    FREE = "free"
    """The codepoint has no cmap entry; install freely."""

    OWNED = "owned"
    """Glyph name carries `TOOL_GLYPH_PREFIX`; replace in place."""

    REPLACEABLE = "replaceable"
    """Foreign composite unreferenced by this tool; replaceable."""

    LOCKED = "locked"
    """Unrecognized occupant; installs onto this slot must skip."""


class _CompositeGlyphLike(Protocol):
    """Structural type of a `glyf` glyph entry exposing only `isComposite`."""

    def isComposite(self) -> bool:
        """Return whether the glyph references components rather than contours."""
        ...


class _GlyfLike(Protocol):
    """Structural type of a `glyf` table keyed by glyph name."""

    def __contains__(self, glyph_name: str) -> bool:
        """Return whether `glyph_name` exists in the table."""
        ...

    def __getitem__(self, glyph_name: str) -> _CompositeGlyphLike:
        """Return the glyph entry stored under `glyph_name`."""
        ...


def classify_pua_slot(cmap_glyph: str | None, glyf: _GlyfLike | None) -> SlotOwnership:
    """Classify the occupant of a PUA codepoint into a `SlotOwnership` verdict.

    `cmap_glyph` is the glyph name mapped at the codepoint (`None` when unmapped) and
    `glyf` the font's glyf table (`None` only for fonts lacking one — generator-loaded
    sources arrive converted, so this guards direct/edge callers).
    """
    if cmap_glyph is None:
        return SlotOwnership.FREE
    if cmap_glyph.startswith(TOOL_GLYPH_PREFIX):
        return SlotOwnership.OWNED
    if glyf is None or cmap_glyph not in glyf:
        return SlotOwnership.LOCKED
    if glyf[cmap_glyph].isComposite():
        return SlotOwnership.REPLACEABLE
    return SlotOwnership.LOCKED


__all__ = ["TOOL_GLYPH_PREFIX", "SlotOwnership", "classify_pua_slot"]
