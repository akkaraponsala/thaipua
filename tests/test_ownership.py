"""Unit tests for PUA slot ownership classification."""

from __future__ import annotations

from thaipua.core.fonttools.ownership import TOOL_GLYPH_PREFIX, SlotOwnership, classify_pua_slot


class _FakeGlyph:
    """Minimal stand-in for a `glyf` glyph exposing only `isComposite`."""

    def __init__(self, composite: bool) -> None:
        self._composite = composite

    def isComposite(self) -> bool:
        return self._composite


class _FakeGlyf:
    """Dict-like stand-in for a `glyf` table keyed by glyph name."""

    def __init__(self, glyphs: dict[str, _FakeGlyph]) -> None:
        self._glyphs = glyphs

    def __contains__(self, name: str) -> bool:
        return name in self._glyphs

    def __getitem__(self, name: str) -> _FakeGlyph:
        return self._glyphs[name]


def _glyf(**glyphs: bool) -> _FakeGlyf:
    return _FakeGlyf({name: _FakeGlyph(composite) for name, composite in glyphs.items()})


def test_unmapped_codepoint_is_free() -> None:
    assert classify_pua_slot(None, _glyf()) is SlotOwnership.FREE


def test_prefixed_glyph_is_owned() -> None:
    assert classify_pua_slot(f"{TOOL_GLYPH_PREFIX}E000", _glyf()) is SlotOwnership.OWNED


def test_prefixed_glyph_missing_from_glyf_is_still_owned() -> None:
    assert classify_pua_slot(f"{TOOL_GLYPH_PREFIX}E000", None) is SlotOwnership.OWNED


def test_foreign_composite_is_replaceable() -> None:
    assert classify_pua_slot("other_tool_E000", _glyf(other_tool_E000=True)) is SlotOwnership.REPLACEABLE


def test_unknown_simple_glyph_is_locked() -> None:
    assert classify_pua_slot("logo", _glyf(logo=False)) is SlotOwnership.LOCKED


def test_dangling_cmap_entry_without_glyf_glyph_is_locked() -> None:
    assert classify_pua_slot("ghost", _glyf()) is SlotOwnership.LOCKED


def test_any_cmap_entry_is_locked_without_a_glyf_table() -> None:
    assert classify_pua_slot("anything", None) is SlotOwnership.LOCKED
