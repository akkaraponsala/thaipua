"""Classify PUA slot occupants to decide whether composite installs may overwrite them."""

from __future__ import annotations

import logging
from typing import Protocol

from thaipua.core.domain.slots import SlotOwnership

logger = logging.getLogger(__name__)

TOOL_GLYPH_PREFIX = "thaipua_"

__all__ = ["TOOL_GLYPH_PREFIX", "SlotOwnership", "classify_pua_slot"]


class _CompositeGlyphLike(Protocol):
    """Structural type of a `glyf` glyph exposing `isComposite`."""

    def isComposite(self) -> bool: ...


class _GlyfLike(Protocol):
    """Structural type of a `glyf` table keyed by glyph name."""

    def __contains__(self, glyph_name: str) -> bool: ...

    def __getitem__(self, glyph_name: str) -> _CompositeGlyphLike: ...


def classify_pua_slot(cmap_glyph: str | None, glyf: _GlyfLike | None) -> SlotOwnership:
    """Classify the occupant of a PUA codepoint as free, owned, replaceable, or locked."""
    if cmap_glyph is None:
        return SlotOwnership.FREE
    if cmap_glyph.startswith(TOOL_GLYPH_PREFIX):
        return SlotOwnership.OWNED
    if glyf is None or cmap_glyph not in glyf:
        return SlotOwnership.LOCKED
    if glyf[cmap_glyph].isComposite():
        return SlotOwnership.REPLACEABLE
    return SlotOwnership.LOCKED
