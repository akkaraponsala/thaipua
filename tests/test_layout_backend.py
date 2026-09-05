"""Slice 3 pin: the domain `LayoutEngine` computes every production map; JSON is untouched."""

import pytest

from thaipua.core.constants import THAI_CONSONANT_CHARS
from thaipua.core.domain.errors import LayoutError
from thaipua.core.domain.grid import LEGAL_COMBOS, MATERIALIZED
from thaipua.core.domain.layout import fresh_engine, layout_from_dict
from thaipua.core.domain.thai import CONSONANT_INDEX, THAI_CONSONANTS
from thaipua.core.font.map_validation import IssueSeverity, validate_pua_map
from thaipua.core.layout import (
    LayoutState,
    canonical_layout,
    cluster_count,
    cluster_ordinal,
    effective_layout,
    key_at_ordinal,
    max_base_codepoint,
)

DIVERGENT = "ก" + chr(0x0E4D) + chr(0x0E48)
DIVERGENT_REORDERED = "ก" + chr(0x0E48) + chr(0x0E4D)
HOLE = "ก" + chr(0x0E4D) + chr(0x0E4C)


@pytest.mark.parametrize("base", [0xE000, 0xE100, max_base_codepoint()])
def test_effective_map_matches_ordinal_math(base: int) -> None:
    mapping = LayoutState(base=base).effective_map()
    assert len(mapping) == 2016
    for key in ("ก่", "กั", "ข่", "ฮ่", DIVERGENT, "ก" + chr(0x0E38) + chr(0x0E49)):
        ordinal = cluster_ordinal(key)
        assert ordinal is not None
        assert mapping[key] == chr(base + ordinal)
    assert cluster_ordinal("ก" + chr(0x0E49) + chr(0x0E38)) == cluster_ordinal("ก" + chr(0x0E38) + chr(0x0E49))
    assert HOLE not in mapping


def test_reordered_keys_resolve_to_stored_form() -> None:
    mapping = effective_layout(0xE000, {DIVERGENT_REORDERED: chr(0xE900)})
    assert mapping[DIVERGENT] == chr(0xE900)
    assert DIVERGENT_REORDERED not in mapping


def test_hole_pins_materialize_and_out_of_range_pins_overlay() -> None:
    mapping = effective_layout(0xE000, {HOLE: chr(0xE9D8), "ก่": "A", "bogus": chr(0xE902)})
    assert mapping[HOLE] == chr(0xE9D8)
    assert mapping["ก่"] == "A"
    assert "bogus" not in mapping
    issues = validate_pua_map(mapping, None)
    flagged = {issue.thai_key for issue in issues if issue.severity is IssueSeverity.ERROR}
    assert "ก่" in flagged
    assert HOLE not in flagged


def test_key_order_matches_grid_order() -> None:
    mapping = effective_layout(0xE000, {"ก่": chr(0xE900), HOLE: chr(0xE901)})
    expected = [f"{consonant}{suffix}" for consonant in THAI_CONSONANT_CHARS for suffix in LEGAL_COMBOS]
    expected = [key for key in expected if key[1:] in set(MATERIALIZED)]
    assert mapping["ก่"] == chr(0xE900)
    assert list(mapping) == [*expected, HOLE]
    assert canonical_layout(0xE000) == effective_layout(0xE000, {})


def test_consonant_text_round_trips_through_the_ordinal_math() -> None:
    assert len(THAI_CONSONANT_CHARS) == len(set(THAI_CONSONANT_CHARS)) == len(THAI_CONSONANTS) == 42
    for char in THAI_CONSONANT_CHARS:
        codepoint = ord(char)
        assert codepoint in THAI_CONSONANTS
        assert THAI_CONSONANT_CHARS[CONSONANT_INDEX[codepoint]] == char
        ordinal = cluster_ordinal(f"{char}่")
        assert ordinal is not None
        assert key_at_ordinal(ordinal)[0] == char


def test_ordinals_agree_with_the_engine_full_table() -> None:
    full = fresh_engine(0xE000).full_table()
    assert len(full) == cluster_count() == 2520
    for ordinal in range(cluster_count()):
        key = key_at_ordinal(ordinal)
        assert cluster_ordinal(key) == ordinal
        assert full[key] == 0xE000 + ordinal


def test_layout_from_dict_accepts_current_and_missing_versions() -> None:
    assert layout_from_dict({"base": 0xE000}).version == 2
    assert layout_from_dict({"version": 2, "base": 0xE000}).base == 0xE000


def test_layout_from_dict_rejects_unknown_versions() -> None:
    for version in (1, 99):
        with pytest.raises(LayoutError, match=f"unsupported layout version {version}"):
            layout_from_dict({"version": version, "base": 0xE000})
