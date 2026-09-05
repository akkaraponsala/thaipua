"""Unit tests for PUA slot ownership classification."""

from conftest import make_glyf

from thaipua.core.font.ownership import TOOL_GLYPH_PREFIX, SlotOwnership, classify_pua_slot


def test_unmapped_codepoint_is_free() -> None:
    assert classify_pua_slot(None, make_glyf()) is SlotOwnership.FREE


def test_prefixed_glyph_is_owned() -> None:
    assert classify_pua_slot(f"{TOOL_GLYPH_PREFIX}E000", make_glyf()) is SlotOwnership.OWNED


def test_prefixed_glyph_missing_from_glyf_is_still_owned() -> None:
    assert classify_pua_slot(f"{TOOL_GLYPH_PREFIX}E000", None) is SlotOwnership.OWNED


def test_foreign_composite_is_replaceable() -> None:
    assert classify_pua_slot("other_tool_E000", make_glyf(other_tool_E000=True)) is SlotOwnership.REPLACEABLE


def test_unknown_simple_glyph_is_locked() -> None:
    assert classify_pua_slot("logo", make_glyf(logo=False)) is SlotOwnership.LOCKED


def test_dangling_cmap_entry_without_glyf_glyph_is_locked() -> None:
    assert classify_pua_slot("ghost", make_glyf()) is SlotOwnership.LOCKED


def test_any_cmap_entry_is_locked_without_a_glyf_table() -> None:
    assert classify_pua_slot("anything", None) is SlotOwnership.LOCKED
