"""Unit tests for `validate_pua_map` and the editor's codepoint input parsing."""

from conftest import FakeGlyf, make_glyf

from thaipua.core.constants import PUA_RANGE_START
from thaipua.core.font.map_validation import (
    IssueSeverity,
    PuaSlotContext,
    parse_codepoint,
    validate_pua_map,
)


def _context(
    cmap: dict[int, str] | None = None,
    glyf: dict[str, bool] | None = None,
) -> PuaSlotContext:
    """Build a slot context from plain dicts."""
    glyf_table: FakeGlyf | None = None
    if glyf is not None:
        glyf_table = make_glyf(**glyf)
    return PuaSlotContext(cmap=cmap or {}, glyf=glyf_table)


def _severities_for(mapping: dict[str, str], context: PuaSlotContext | None) -> dict[str, list[IssueSeverity]]:
    return _severities_with(context, allowed=None, mapping=mapping)


def _severities_with(
    context: PuaSlotContext | None,
    *,
    allowed: frozenset[int] | None,
    mapping: dict[str, str],
) -> dict[str, list[IssueSeverity]]:
    issues = validate_pua_map(mapping, context, allowed_locked=allowed)
    grouped: dict[str, list[IssueSeverity]] = {}
    for issue in issues:
        grouped.setdefault(issue.thai_key, []).append(issue.severity)
    return grouped


def test_clean_map_yields_no_issues() -> None:
    mapping = {"ก": chr(0xE000), "ก่": chr(0xE001), "ปุ": chr(PUA_RANGE_START + 2)}
    assert validate_pua_map(mapping, None) == []


def test_multi_char_value_is_an_error() -> None:
    severities = _severities_for({"ก": "ab"}, None)
    assert severities == {"ก": [IssueSeverity.ERROR]}


def test_value_outside_pua_range_is_an_error() -> None:
    severities = _severities_for({"ก": "A"}, None)
    assert severities == {"ก": [IssueSeverity.ERROR]}


def test_undecomposable_key_is_an_error() -> None:
    severities = _severities_for({"กx": chr(0xE000)}, None)
    assert severities == {"กx": [IssueSeverity.ERROR]}


def test_duplicate_values_flag_every_involved_key() -> None:
    mapping = {"ก": chr(0xE000), "ข": chr(0xE000)}
    issues = validate_pua_map(mapping, None)
    flagged = {issue.thai_key for issue in issues}
    assert flagged == {"ก", "ข"}
    assert all(issue.severity is IssueSeverity.ERROR for issue in issues)
    assert all("shared by multiple keys" in issue.message for issue in issues)


def test_locked_occupant_is_an_error_with_font_context() -> None:
    context = _context(cmap={0xE000: "logo"}, glyf={"logo": False})
    severities = _severities_for({"ก": chr(0xE000)}, context)
    assert severities == {"ก": [IssueSeverity.ERROR]}


def test_overridden_locked_occupant_downgrades_to_warning() -> None:
    context = _context(cmap={0xE000: "logo"}, glyf={"logo": False})

    issues = validate_pua_map({"ก": chr(0xE000)}, context, allowed_locked=frozenset({0xE000}))

    assert [issue.severity for issue in issues] == [IssueSeverity.WARNING]
    assert "override" in issues[0].message


def test_locked_issues_carry_their_slot_codepoint() -> None:
    context = _context(cmap={0xE000: "logo", 0xE001: "other"}, glyf={"logo": False, "other": True})
    issues = validate_pua_map({"ก": chr(0xE000), "ข": chr(0xE001)}, context, allowed_locked=frozenset({0xE001}))
    by_key = {issue.thai_key: issue.slot_codepoint for issue in issues}
    assert by_key == {"ก": 0xE000, "ข": 0xE001}


def test_structural_issues_have_no_slot_codepoint() -> None:
    issues = validate_pua_map({"ก": chr(0xE000), "ข": chr(0xE000)}, None)
    assert issues
    assert all(issue.slot_codepoint is None for issue in issues)


def test_override_for_another_codepoint_keeps_the_error() -> None:
    context = _context(cmap={0xE000: "logo"}, glyf={"logo": False})
    severities = _severities_with(context, allowed=frozenset({0xE001}), mapping={"ก": chr(0xE000)})
    assert severities == {"ก": [IssueSeverity.ERROR]}


def test_foreign_composite_occupant_is_a_warning() -> None:
    context = _context(cmap={0xE000: "other_tool_E000"}, glyf={"other_tool_E000": True})
    severities = _severities_for({"ก": chr(0xE000)}, context)
    assert severities == {"ก": [IssueSeverity.WARNING]}


def test_owned_prefix_and_free_slots_produce_no_issues() -> None:
    free_cp = 0xE005
    context = _context(cmap={0xE000: "thaipua_E000"}, glyf={"thaipua_E000": True})
    severities = _severities_for({"ก": chr(free_cp), "ข": chr(0xE000)}, context)
    assert severities == {}


def test_none_context_skips_slot_checks() -> None:
    severities = _severities_for({"ก": chr(0xE000)}, None)
    assert severities == {}


# --- parse_codepoint ---


def test_parse_accepts_bare_hex() -> None:
    assert parse_codepoint("E0A3") == chr(0xE0A3)
    assert parse_codepoint("e003") == chr(0xE003)


def test_parse_accepts_prefixed_hex() -> None:
    assert parse_codepoint("U+E0A3") == chr(0xE0A3)
    assert parse_codepoint("0xE0A3") == chr(0xE0A3)


def test_parse_accepts_single_literal_char() -> None:
    assert parse_codepoint(chr(0xF8FF)) == chr(0xF8FF)


def test_parse_rejects_garbage() -> None:
    assert parse_codepoint("") is None
    assert parse_codepoint("   ") is None
    assert parse_codepoint("hello") is None
    assert parse_codepoint("E0AG") is None


def test_parse_returns_out_of_range_hex_unchanged_for_validator_to_flag() -> None:
    assert parse_codepoint("E0A31") == chr(0xE0A31)


def test_parse_rejects_unencodable_codepoints() -> None:
    assert parse_codepoint("D800") is None
    assert parse_codepoint("dfff") is None
    assert parse_codepoint("110000") is None
    assert parse_codepoint("-2") is None
    assert parse_codepoint(chr(0xD800)) is None
