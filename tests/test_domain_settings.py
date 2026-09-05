"""Slice 1: strict Pydantic domain settings — codec, tier rule, resolve(), with_* copies."""

import pytest

from thaipua.core.domain.errors import SettingsError
from thaipua.core.domain.settings import (
    ROLE_ABOVE_VOWEL,
    ROLE_TONE_MARK,
    ROLE_TONE_MARK_ON_ABOVE_VOWEL,
    SUB_ABOVE_VOWEL,
    SUB_BELOW_VOWEL,
    SUB_TONE_MARK,
    ConsonantSettings,
    Metadata,
    Offset,
    PlacementSettings,
    SnapConfig,
    SubstitutionRule,
    combo_key_for_marks,
    default_placement_settings,
    settings_from_dict,
    settings_to_dict,
)

TONE_MAI_EK = 0x0E48
CONSONANT_KO_KAI = 0x0E01
CONSONANT_PO_PLA = 0x0E1B
VOWEL_SARA_U = 0x0E38
VOWEL_MAI_HAN_AKAT = 0x0E31
COMBO = f"{chr(VOWEL_MAI_HAN_AKAT)}{chr(TONE_MAI_EK)}"


def test_missing_version_defaults_to_current() -> None:
    settings = settings_from_dict({"consonants": {"U+0E1B": {"base_offsets": {"tone_mark": {"x": 1, "y": 0}}}}})
    assert settings.version == 1
    assert settings.consonants[CONSONANT_PO_PLA].base_offsets[ROLE_TONE_MARK] == Offset(x=1, y=0)


def test_unsupported_version_raises() -> None:
    with pytest.raises(SettingsError, match="unsupported settings version 99"):
        settings_from_dict({"version": 99})


def test_non_object_document_raises() -> None:
    with pytest.raises(SettingsError, match="must be an object"):
        settings_from_dict([])  # type: ignore[arg-type]


def test_raw_thai_consonant_key_raises() -> None:
    with pytest.raises(SettingsError, match="U\\+XXXX"):
        settings_from_dict({"version": 1, "consonants": {"ก": {"base_offsets": {"tone_mark": {"x": 1, "y": 0}}}}})


def test_non_consonant_codepoint_key_raises() -> None:
    with pytest.raises(SettingsError, match="not a Thai consonant"):
        settings_from_dict({"version": 1, "consonants": {"U+0E31": {"base_offsets": {"tone_mark": {"x": 1, "y": 0}}}}})


def test_unknown_base_role_raises() -> None:
    with pytest.raises(SettingsError, match="unknown base_offsets role"):
        settings_from_dict({"version": 1, "consonants": {"U+0E1B": {"base_offsets": {"bogus": {"x": 1, "y": 0}}}}})


def test_unknown_mark_group_raises() -> None:
    with pytest.raises(SettingsError, match="unknown mark group"):
        settings_from_dict(
            {"version": 1, "consonants": {"U+0E1B": {"mark_offsets": {"bogus": {"U+0E48": {"x": 1, "y": 0}}}}}}
        )


def test_mark_outside_group_category_raises() -> None:
    with pytest.raises(SettingsError, match="not in the 'above_vowels' category"):
        settings_from_dict(
            {
                "version": 1,
                "consonants": {
                    "U+0E1B": {
                        "mark_offsets": {
                            "above_vowels": {"U+0E48": {"x": 1, "y": 0}},
                            "tone_marks": {"U+0E48": {"x": 2, "y": 0}},
                        }
                    }
                },
            }
        )


def test_junk_combo_key_raises() -> None:
    with pytest.raises(SettingsError, match=r"not a .* combo key"):
        settings_from_dict(
            {"version": 1, "consonants": {"U+0E1B": {"combo_offsets": {"U+0E31foo+U+0E48": {"tone_mark": {"x": 1}}}}}}
        )


def test_duplicate_combo_codepoints_raise() -> None:
    with pytest.raises(SettingsError, match="repeats a codepoint"):
        settings_from_dict(
            {"version": 1, "consonants": {"U+0E1B": {"combo_offsets": {"U+0E31+U+0E31": {"tone_mark": {"x": 1}}}}}}
        )


def test_single_segment_combo_key_raises() -> None:
    with pytest.raises(SettingsError, match="at least two marks"):
        settings_from_dict(
            {"version": 1, "consonants": {"U+0E1B": {"combo_offsets": {"U+0E48": {"tone_mark": {"x": 1}}}}}}
        )


def test_non_mark_combo_member_raises() -> None:
    with pytest.raises(SettingsError, match="not a Thai mark"):
        settings_from_dict(
            {"version": 1, "consonants": {"U+0E1B": {"combo_offsets": {"U+0E01+U+0E48": {"tone_mark": {"x": 1}}}}}}
        )


def test_unknown_combo_role_raises() -> None:
    with pytest.raises(SettingsError, match=r"unknown combo_offsets.* role"):
        settings_from_dict(
            {
                "version": 1,
                "consonants": {"U+0E1B": {"combo_offsets": {"U+0E31+U+0E48": {"bogus": {"x": 1, "y": 0}}}}},
            }
        )


def test_empty_replacement_raises() -> None:
    with pytest.raises(SettingsError):
        settings_from_dict(
            {
                "version": 1,
                "consonants": {"U+0E1B": {"glyph_substitutions": {"U+0E48": [{"replacement": ""}]}}},
            }
        )


def test_unknown_condition_role_raises() -> None:
    with pytest.raises(SettingsError, match="unknown substitution condition role"):
        settings_from_dict(
            {
                "version": 1,
                "consonants": {
                    "U+0E1B": {"glyph_substitutions": {"U+0E48": [{"replacement": "x", "conditions": ["bogus"]}]}}
                },
            }
        )


def test_non_list_conditions_raise() -> None:
    with pytest.raises(SettingsError, match="must be a list of roles"):
        settings_from_dict(
            {
                "version": 1,
                "consonants": {
                    "U+0E1B": {"glyph_substitutions": {"U+0E48": [{"replacement": "x", "conditions": "tone_mark"}]}}
                },
            }
        )


def test_fractional_offset_raises() -> None:
    with pytest.raises(SettingsError):
        settings_from_dict(
            {
                "version": 1,
                "consonants": {"U+0E1B": {"mark_offsets": {"tone_marks": {"U+0E48": {"x": 1.5, "y": 0}}}}},
            }
        )


def test_non_positive_units_per_em_raises() -> None:
    with pytest.raises(SettingsError):
        settings_from_dict({"version": 1, "metadata": {"units_per_em": -100}})


def test_blank_metadata_name_raises() -> None:
    with pytest.raises(SettingsError, match="non-empty string"):
        settings_from_dict({"version": 1, "metadata": {"font_name": ""}})


def test_unknown_snap_name_raises() -> None:
    with pytest.raises(SettingsError, match="unknown snap_configs role"):
        settings_from_dict({"version": 1, "consonants": {"U+0E1B": {"snap_configs": {"bogus": True}}}})


def test_non_bool_snap_enabled_raises() -> None:
    with pytest.raises(SettingsError):
        settings_from_dict({"version": 1, "consonants": {"U+0E1B": {"snap_configs": {"tone_mark_to_above_vowel": 1}}}})


def test_extra_top_level_key_raises() -> None:
    with pytest.raises(SettingsError):
        settings_from_dict({"version": 1, "bogus_section": {}})


def test_out_of_order_combo_key_normalizes() -> None:
    settings = settings_from_dict(
        {"version": 1, "consonants": {"U+0E1B": {"combo_offsets": {"U+0E48+U+0E31": {"tone_mark": {"x": 5, "y": 3}}}}}}
    )
    assert settings.consonants[CONSONANT_PO_PLA].combo_offsets == {COMBO: {ROLE_TONE_MARK: Offset(5, 3)}}


def test_duplicate_condition_rules_last_wins() -> None:
    settings = settings_from_dict(
        {
            "version": 1,
            "consonants": {
                "U+0E1B": {
                    "glyph_substitutions": {
                        "U+0E48": [
                            {"replacement": "first", "conditions": ["tone_mark"]},
                            {"replacement": "second", "conditions": ["tone_mark"]},
                        ]
                    }
                }
            },
        }
    )
    cs = settings.consonants[CONSONANT_PO_PLA]
    assert cs.substitution_for(TONE_MAI_EK, present_roles=frozenset({SUB_TONE_MARK})) == "second"


def test_tone_rule_below_vowel_family_fires_for_tone_only() -> None:
    settings = settings_from_dict(
        {
            "version": 1,
            "consonants": {
                "U+0E1B": {"glyph_substitutions": {"U+0E48": [{"replacement": "x", "conditions": ["below_vowel"]}]}}
            },
        }
    )
    cs = settings.consonants[CONSONANT_PO_PLA]
    assert cs.substitution_for(TONE_MAI_EK, present_roles=frozenset({SUB_TONE_MARK})) == "x"
    assert cs.substitution_for(TONE_MAI_EK, present_roles=frozenset({SUB_ABOVE_VOWEL, SUB_TONE_MARK})) is None


def test_full_round_trip_preserves_settings() -> None:
    settings = PlacementSettings(
        metadata=Metadata(font_name="Sarabun", family_name="Sarabun", units_per_em=1000),
        marks={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-40, 3)}},
        consonants={
            CONSONANT_KO_KAI: ConsonantSettings(
                base_offsets={ROLE_TONE_MARK: Offset(-150, 10)},
                mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-1, 2)}},
                combo_offsets={COMBO: {ROLE_TONE_MARK: Offset(5, 3)}},
                snap_configs={"tone_mark_to_above_vowel": SnapConfig(enabled=True, gap=12)},
                glyph_substitutions={TONE_MAI_EK: [SubstitutionRule(replacement="alt", conditions=frozenset())]},
            )
        },
    )
    assert settings_from_dict(settings_to_dict(settings)) == settings


def test_global_marks_wire_shape() -> None:
    settings = PlacementSettings(marks={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-40, 3)}})
    assert settings_to_dict(settings)["marks"] == {"tone_marks": {"U+0E48": {"x": -40, "y": 3}}}


def test_resolve_keeps_tier_breakdown() -> None:
    settings = PlacementSettings(
        marks={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-40, 0)}},
        consonants={
            CONSONANT_KO_KAI: ConsonantSettings(
                base_offsets={ROLE_TONE_MARK: Offset(1, 2)},
                mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(10, 20)}},
            )
        },
    )
    resolved = settings.resolve(CONSONANT_KO_KAI, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None)
    assert resolved.per_glyph == Offset(10, 20)
    assert resolved.global_offset == Offset(-40, 0)
    assert resolved.base == Offset(1, 2)
    assert resolved.total == Offset(-29, 22)
    assert settings.mark_offset_for(CONSONANT_KO_KAI, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None) == (
        resolved.total
    )


def test_resolve_stacked_base_role_falls_back_to_role() -> None:
    settings = PlacementSettings(
        consonants={
            CONSONANT_KO_KAI: ConsonantSettings(
                base_offsets={
                    ROLE_TONE_MARK_ON_ABOVE_VOWEL: Offset(-150, 0),
                    ROLE_TONE_MARK: Offset(-10, 0),
                },
                mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-1, 0)}},
            )
        },
    )
    stacked = settings.resolve(
        CONSONANT_KO_KAI,
        ROLE_TONE_MARK,
        mark_uni=TONE_MAI_EK,
        combo_key=None,
        base_role=ROLE_TONE_MARK_ON_ABOVE_VOWEL,
    )
    assert stacked.base == Offset(-150, 0)
    assert stacked.total == Offset(-151, 0)
    fallback = settings.resolve(
        CONSONANT_KO_KAI, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None, base_role="missing_role"
    )
    assert fallback.base == Offset(-10, 0)


def test_tier_rule_single_uses_mark_tier_combo_uses_combo_tier() -> None:
    settings = PlacementSettings(
        consonants={
            CONSONANT_KO_KAI: ConsonantSettings(
                mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(10, 20)}},
                combo_offsets={COMBO: {ROLE_TONE_MARK: Offset(5, -5)}},
            )
        },
    )
    single = settings.mark_offset_for(CONSONANT_KO_KAI, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None)
    combo = settings.mark_offset_for(CONSONANT_KO_KAI, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=COMBO)
    assert single == Offset(10, 20)
    assert combo == Offset(5, -5)


def test_combo_without_entry_resolves_to_zero() -> None:
    settings = PlacementSettings(
        consonants={CONSONANT_KO_KAI: ConsonantSettings(mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(10, 20)}})},
    )
    assert settings.mark_offset_for(CONSONANT_KO_KAI, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=COMBO) == (
        Offset()
    )


def test_with_mark_offset_is_immutable_and_prunes() -> None:
    settings = default_placement_settings()
    updated = settings.with_mark_offset(CONSONANT_KO_KAI, ROLE_TONE_MARK, TONE_MAI_EK, Offset(3, 4))
    assert settings.consonants == {}
    assert updated.consonants[CONSONANT_KO_KAI].mark_offsets == {ROLE_TONE_MARK: {TONE_MAI_EK: Offset(3, 4)}}
    cleared = updated.with_mark_offset(CONSONANT_KO_KAI, ROLE_TONE_MARK, TONE_MAI_EK, Offset(0, 0))
    assert cleared.consonants[CONSONANT_KO_KAI].mark_offsets == {}
    assert CONSONANT_KO_KAI in cleared.consonants


def test_with_combo_and_base_offsets() -> None:
    settings = default_placement_settings()
    updated = settings.with_combo_offset(CONSONANT_KO_KAI, COMBO, ROLE_ABOVE_VOWEL, Offset(5, -5))
    assert updated.consonants[CONSONANT_KO_KAI].combo_offsets == {COMBO: {ROLE_ABOVE_VOWEL: Offset(5, -5)}}
    cleared = updated.with_combo_offset(CONSONANT_KO_KAI, COMBO, ROLE_ABOVE_VOWEL, None)
    assert cleared.consonants[CONSONANT_KO_KAI].combo_offsets == {}
    based = settings.with_base_offset(CONSONANT_KO_KAI, ROLE_TONE_MARK, Offset(1, 1))
    assert based.consonants[CONSONANT_KO_KAI].base_offsets == {ROLE_TONE_MARK: Offset(1, 1)}
    assert (
        based.with_base_offset(CONSONANT_KO_KAI, ROLE_TONE_MARK, Offset(0, 0)).consonants[CONSONANT_KO_KAI].base_offsets
        == {}
    )


def test_with_global_mark_sets_and_prunes() -> None:
    settings = default_placement_settings()
    updated = settings.with_global_mark(ROLE_TONE_MARK, TONE_MAI_EK, Offset(-40, 0))
    assert updated.marks == {ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-40, 0)}}
    cleared = updated.with_global_mark(ROLE_TONE_MARK, TONE_MAI_EK, Offset(0, 0))
    assert cleared.marks == {}
    assert settings.marks == {}


def test_with_rule_upserts_and_removes() -> None:
    settings = default_placement_settings()
    updated = settings.with_rule(CONSONANT_KO_KAI, VOWEL_SARA_U, frozenset({SUB_BELOW_VOWEL}), "alt")
    cs = updated.consonants[CONSONANT_KO_KAI]
    assert cs.substitution_for(VOWEL_SARA_U, present_roles=frozenset({SUB_BELOW_VOWEL})) == "alt"
    replaced = updated.with_rule(CONSONANT_KO_KAI, VOWEL_SARA_U, frozenset({SUB_BELOW_VOWEL}), "alt2")
    assert replaced.consonants[CONSONANT_KO_KAI].glyph_substitutions[VOWEL_SARA_U][0].replacement == "alt2"
    removed = replaced.with_rule(CONSONANT_KO_KAI, VOWEL_SARA_U, frozenset({SUB_BELOW_VOWEL}), None)
    assert removed.consonants[CONSONANT_KO_KAI].glyph_substitutions == {}
    assert settings.consonants == {}


def test_with_snap_sets_and_removes() -> None:
    settings = default_placement_settings()
    updated = settings.with_snap(CONSONANT_KO_KAI, "tone_mark_to_above_vowel", SnapConfig(enabled=True, gap=3))
    assert updated.consonants[CONSONANT_KO_KAI].snap_configs["tone_mark_to_above_vowel"] == SnapConfig(
        enabled=True, gap=3
    )
    assert (
        updated.with_snap(CONSONANT_KO_KAI, "tone_mark_to_above_vowel", None).consonants[CONSONANT_KO_KAI].snap_configs
        == {}
    )
    disabled = updated.with_snap(CONSONANT_KO_KAI, "tone_mark_to_above_vowel", SnapConfig(enabled=False, gap=0))
    assert disabled.consonants[CONSONANT_KO_KAI].snap_configs == {}


def test_with_metadata_stamps_identity() -> None:
    settings = default_placement_settings()
    stamped = settings.with_metadata(Metadata(font_name="Sarabun Regular", family_name="Sarabun", units_per_em=1000))
    assert stamped.metadata.family_name == "Sarabun"
    assert settings.metadata == Metadata()


def test_direct_construction_canonicalizes_conditions() -> None:
    cs = ConsonantSettings(
        glyph_substitutions={TONE_MAI_EK: [SubstitutionRule(replacement="x", conditions=frozenset({SUB_BELOW_VOWEL}))]}
    )
    assert cs.glyph_substitutions[TONE_MAI_EK][0].conditions == frozenset({SUB_TONE_MARK})


def test_combo_key_requires_two_marks() -> None:
    assert combo_key_for_marks(None, VOWEL_MAI_HAN_AKAT, None) is None
    assert combo_key_for_marks(None, VOWEL_MAI_HAN_AKAT, TONE_MAI_EK) == COMBO
