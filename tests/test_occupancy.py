"""Unit tests for PUA occupancy scanning over duck-typed fonts."""

from typing import Any

from conftest import FakeCompositeGlyph, FakeGlyf, FakeGlyph

from thaipua.core.font.occupancy import scan_pua_occupants
from thaipua.core.font.ownership import SlotOwnership


class _ScanFont:
    """Duck-typed `TTFont` exposing `getBestCmap` and `get`."""

    def __init__(self, cmap: dict[int, str], glyf: FakeGlyf | None) -> None:
        self._cmap = cmap
        self._glyf = glyf

    def getBestCmap(self) -> dict[int, str]:
        return self._cmap

    def get(self, key: str) -> Any:
        return self._glyf if key == "glyf" else None


def _font(cmap: dict[int, str], glyphs: dict[str, Any] | None = None) -> _ScanFont:
    return _ScanFont(cmap, FakeGlyf(glyphs) if glyphs is not None else None)


def test_scan_classifies_and_sorts_pua_slots_only() -> None:
    font = _font(
        {0x0E01: "ko_kai", 0xE001: "foreign", 0xE000: "thaipua_E000", 0xE002: "logo", 0xE003: "ghost"},
        {
            "thaipua_E000": FakeCompositeGlyph(["ko_kai"]),
            "foreign": FakeCompositeGlyph(["a", "b"]),
            "logo": FakeGlyph(composite=False),
        },
    )

    occupants = scan_pua_occupants(font)

    assert [o.codepoint for o in occupants] == [0xE000, 0xE001, 0xE002, 0xE003]
    by_code = {o.codepoint: o for o in occupants}
    assert by_code[0xE000].ownership is SlotOwnership.OWNED
    assert by_code[0xE001].ownership is SlotOwnership.REPLACEABLE
    assert by_code[0xE002].ownership is SlotOwnership.LOCKED
    assert by_code[0xE003].ownership is SlotOwnership.LOCKED


def test_scan_details_describe_each_glyph_kind() -> None:
    font = _font(
        {0xE000: "thaipua_E000", 0xE001: "foreign", 0xE002: "logo", 0xE003: "ghost"},
        {
            "thaipua_E000": FakeCompositeGlyph(["ko_kai"]),
            "foreign": FakeCompositeGlyph(["a", "b"]),
            "logo": FakeGlyph(composite=False),
        },
    )

    occupants = {o.codepoint: o for o in scan_pua_occupants(font)}

    assert occupants[0xE000].detail == "composite of ko_kai"
    assert occupants[0xE001].detail == "composite of a, b"
    assert occupants[0xE002].detail == "simple glyph"
    assert occupants[0xE003].detail == "dangling cmap entry"


def test_scan_reports_contour_counts_and_missing_glyf() -> None:
    font = _font(
        {0xE000: "three", 0xE001: "one", 0xE002: "anything"},
        {"three": FakeGlyph(composite=False, contours=3), "one": FakeGlyph(composite=False, contours=1)},
    )

    occupants = {o.codepoint: o for o in scan_pua_occupants(font)}

    assert occupants[0xE000].detail == "simple glyph (3 contours)"
    assert occupants[0xE001].detail == "simple glyph (1 contour)"
    assert occupants[0xE002].detail == "dangling cmap entry"

    bare = _font({0xE000: "glyph"}, None)
    assert scan_pua_occupants(bare)[0].detail == "font has no glyf table"
