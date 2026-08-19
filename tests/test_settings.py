"""Unit tests for `ConsonantSettings.offset_for` tier layering and substitution matching."""

from __future__ import annotations

import json
from pathlib import Path

from thaipua.core.fonttools.settings import (
    ROLE_TONE_MARK,
    ROLE_TONE_MARK_ON_ABOVE_VOWEL,
    SUB_ABOVE_VOWEL,
    SUB_BELOW_VOWEL,
    SUB_TONE_MARK,
    ConsonantSettings,
    Offset,
    PlacementSettings,
    SubstitutionRule,
    canonicalise_consonant_context,
    canonicalise_substitution_context,
    canonicalise_tone_mark_context,
    load_placement_settings,
    settings_to_dict,
)

TONE_MAI_EK = 0x0E48
CONSONANT_LO_CHULA = 0x0E2C
CONSONANT_YO_YING = 0x0E0D
CONSONANT_KO_KAI = 0x0E01
VOWEL_SARA_U = 0x0E38
VOWEL_SARA_AA = 0x0E32
VOWEL_MAI_HAN_AKAT = 0x0E31


def test_mark_offset_adds_to_base_offset() -> None:
    cs = ConsonantSettings(
        base_offsets={ROLE_TONE_MARK: Offset(-150, 10)},
        mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-1, 2)}},
    )
    assert cs.offset_for(ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None) == Offset(-151, 12)


def test_combo_offset_adds_to_base_offset() -> None:
    cs = ConsonantSettings(
        base_offsets={ROLE_TONE_MARK: Offset(0, -20)},
        combo_offsets={f"{chr(VOWEL_MAI_HAN_AKAT)}{chr(TONE_MAI_EK)}": {ROLE_TONE_MARK: Offset(5, 3)}},
    )
    off = cs.offset_for(ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=f"{chr(VOWEL_MAI_HAN_AKAT)}{chr(TONE_MAI_EK)}")
    assert off == Offset(5, -17)


def test_tone_on_above_vowel_resolves_stacked_base_role() -> None:
    cs = ConsonantSettings(
        base_offsets={
            ROLE_TONE_MARK_ON_ABOVE_VOWEL: Offset(-150, 0),
            ROLE_TONE_MARK: Offset(-10, 0),
        },
        mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-1, 0)}},
    )
    off = cs.offset_for(ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None, base_role=ROLE_TONE_MARK_ON_ABOVE_VOWEL)
    assert off == Offset(-151, 0)


def test_base_role_falls_back_to_role() -> None:
    cs = ConsonantSettings(base_offsets={ROLE_TONE_MARK: Offset(-10, 0)})
    off = cs.offset_for(ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None, base_role=ROLE_TONE_MARK_ON_ABOVE_VOWEL)
    assert off == Offset(-10, 0)


def test_mark_offset_without_base_tier() -> None:
    cs = ConsonantSettings(mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-1, 0)}})
    assert cs.offset_for(ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None) == Offset(-1, 0)


def test_no_tiers_yields_zero() -> None:
    assert ConsonantSettings().offset_for(ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None) == Offset()


def test_canonicalise_tone_mark_context_merges_below_family_with_tone_only() -> None:
    assert canonicalise_tone_mark_context(frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == frozenset({SUB_TONE_MARK})
    assert canonicalise_tone_mark_context(frozenset({SUB_BELOW_VOWEL})) == frozenset({SUB_TONE_MARK})
    assert canonicalise_tone_mark_context(frozenset({SUB_TONE_MARK})) == frozenset({SUB_TONE_MARK})


def test_canonicalise_tone_mark_context_keeps_above_vowel_and_empty_families() -> None:
    assert canonicalise_tone_mark_context(frozenset({SUB_ABOVE_VOWEL, SUB_TONE_MARK})) == frozenset({SUB_ABOVE_VOWEL})
    assert canonicalise_tone_mark_context(frozenset({SUB_ABOVE_VOWEL})) == frozenset({SUB_ABOVE_VOWEL})
    assert canonicalise_tone_mark_context(frozenset()) == frozenset()


def test_tone_rule_below_vowel_family_fires_for_tone_only_cluster() -> None:
    cs = ConsonantSettings(
        glyph_substitutions={
            TONE_MAI_EK: [SubstitutionRule(replacement="sara_u_tone_alt", conditions=frozenset({SUB_BELOW_VOWEL}))]
        }
    )
    assert cs.substitution_for(TONE_MAI_EK, present_roles=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == (
        "sara_u_tone_alt"
    )
    assert cs.substitution_for(TONE_MAI_EK, present_roles=frozenset({SUB_TONE_MARK})) == "sara_u_tone_alt"


def test_tone_rule_tone_only_fires_for_below_vowel_family() -> None:
    cs = ConsonantSettings(
        glyph_substitutions={
            TONE_MAI_EK: [SubstitutionRule(replacement="plain_tone_alt", conditions=frozenset({SUB_TONE_MARK}))]
        }
    )
    assert cs.substitution_for(TONE_MAI_EK, present_roles=frozenset({SUB_TONE_MARK})) == "plain_tone_alt"
    assert cs.substitution_for(TONE_MAI_EK, present_roles=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == (
        "plain_tone_alt"
    )


def test_tone_rule_above_vowel_family_stays_distinct() -> None:
    cs = ConsonantSettings(
        glyph_substitutions={
            TONE_MAI_EK: [SubstitutionRule(replacement="tone_alt", conditions=frozenset({SUB_BELOW_VOWEL}))]
        }
    )
    assert cs.substitution_for(TONE_MAI_EK, present_roles=frozenset({SUB_ABOVE_VOWEL, SUB_TONE_MARK})) is None
    above_cs = ConsonantSettings(
        glyph_substitutions={
            TONE_MAI_EK: [SubstitutionRule(replacement="above_tone_alt", conditions=frozenset({SUB_ABOVE_VOWEL}))]
        }
    )
    assert above_cs.substitution_for(TONE_MAI_EK, present_roles=frozenset({SUB_TONE_MARK})) is None


def test_non_tone_codepoint_rules_keep_below_vowel_contexts_distinct() -> None:
    cs = ConsonantSettings(
        glyph_substitutions={
            VOWEL_SARA_U: [SubstitutionRule(replacement="sara_u_alt", conditions=frozenset({SUB_BELOW_VOWEL}))]
        }
    )
    assert cs.substitution_for(VOWEL_SARA_U, present_roles=frozenset({SUB_BELOW_VOWEL})) == "sara_u_alt"
    assert cs.substitution_for(VOWEL_SARA_U, present_roles=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == "sara_u_alt"
    assert cs.substitution_for(VOWEL_SARA_U, present_roles=frozenset({SUB_TONE_MARK})) is None


def test_tone_rule_round_trip_loads_canonical_below_vowel_conditions(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "consonants": {
            "U+0E1B": {
                "glyph_substitutions": {
                    "U+0E48": [{"replacement": "tone_alt", "conditions": ["below_vowel", "tone_mark"]}]
                }
            }
        },
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    settings = load_placement_settings(path)
    cs = settings.for_consonant(0x0E1B)
    assert cs.substitution_for(TONE_MAI_EK, present_roles=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == "tone_alt"
    assert cs.substitution_for(TONE_MAI_EK, present_roles=frozenset({SUB_TONE_MARK})) == "tone_alt"
    assert cs.substitution_for(TONE_MAI_EK, present_roles=frozenset({SUB_ABOVE_VOWEL, SUB_TONE_MARK})) is None


def test_tone_rule_serializes_conditions_in_canonical_form() -> None:
    settings = PlacementSettings(
        consonants={
            0x0E1B: ConsonantSettings(
                glyph_substitutions={
                    TONE_MAI_EK: [SubstitutionRule(replacement="tone_alt", conditions=frozenset({SUB_TONE_MARK}))]
                }
            )
        }
    )
    payload = settings_to_dict(settings)
    rules = payload["consonants"]["U+0E1B"]["glyph_substitutions"]["U+0E48"]
    assert rules == [{"replacement": "tone_alt", "conditions": ["tone_mark"]}]


def test_canonicalise_substitution_context_unchanged_within_vowel_families() -> None:
    assert canonicalise_substitution_context(frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == frozenset(
        {SUB_BELOW_VOWEL}
    )
    assert canonicalise_substitution_context(frozenset({SUB_TONE_MARK})) == frozenset({SUB_TONE_MARK})


def test_canonicalise_consonant_context_up_families() -> None:
    assert canonicalise_consonant_context(frozenset({SUB_BELOW_VOWEL}), protrusion="up") == frozenset({SUB_BELOW_VOWEL})
    assert canonicalise_consonant_context(frozenset({SUB_TONE_MARK}), protrusion="up") == frozenset(
        {SUB_ABOVE_VOWEL, SUB_TONE_MARK}
    )
    assert canonicalise_consonant_context(frozenset({SUB_ABOVE_VOWEL}), protrusion="up") == frozenset(
        {SUB_ABOVE_VOWEL, SUB_TONE_MARK}
    )
    assert canonicalise_consonant_context(frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK}), protrusion="up") == frozenset(
        {SUB_ABOVE_VOWEL, SUB_TONE_MARK}
    )
    assert canonicalise_consonant_context(frozenset({SUB_ABOVE_VOWEL, SUB_TONE_MARK}), protrusion="up") == frozenset(
        {SUB_ABOVE_VOWEL, SUB_TONE_MARK}
    )
    assert canonicalise_consonant_context(frozenset(), protrusion="up") == frozenset()


def test_canonicalise_consonant_context_down_families() -> None:
    assert canonicalise_consonant_context(frozenset({SUB_BELOW_VOWEL}), protrusion="down") == frozenset(
        {SUB_BELOW_VOWEL}
    )
    assert canonicalise_consonant_context(frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK}), protrusion="down") == frozenset(
        {SUB_BELOW_VOWEL}
    )
    assert canonicalise_consonant_context(
        frozenset({SUB_ABOVE_VOWEL, SUB_BELOW_VOWEL}), protrusion="down"
    ) == frozenset({SUB_BELOW_VOWEL})
    assert canonicalise_consonant_context(frozenset({SUB_TONE_MARK}), protrusion="down") == frozenset({SUB_TONE_MARK})
    assert canonicalise_consonant_context(frozenset({SUB_ABOVE_VOWEL}), protrusion="down") == frozenset(
        {SUB_ABOVE_VOWEL}
    )
    assert canonicalise_consonant_context(frozenset(), protrusion="down") == frozenset()


def test_consonant_without_protrusion_uses_generic_families() -> None:
    assert canonicalise_consonant_context(frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK}), protrusion=None) == frozenset(
        {SUB_BELOW_VOWEL}
    )
    assert canonicalise_consonant_context(frozenset({SUB_TONE_MARK}), protrusion=None) == frozenset({SUB_TONE_MARK})


def test_consonant_rule_below_only_does_not_fire_with_tone() -> None:
    cs = ConsonantSettings(
        glyph_substitutions={
            CONSONANT_LO_CHULA: [SubstitutionRule(replacement="short_tail", conditions=frozenset({SUB_BELOW_VOWEL}))]
        }
    )
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_BELOW_VOWEL})) == "short_tail"
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) is None
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_TONE_MARK})) is None
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_ABOVE_VOWEL})) is None


def test_consonant_rule_below_plus_tone_fires_for_tone_only() -> None:
    cs = ConsonantSettings(
        glyph_substitutions={
            CONSONANT_LO_CHULA: [
                SubstitutionRule(replacement="short_tail", conditions=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK}))
            ]
        }
    )
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == (
        "short_tail"
    )
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_TONE_MARK})) == "short_tail"
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_BELOW_VOWEL})) is None


def test_consonant_rule_above_vowel_fires_for_every_above_stack() -> None:
    cs = ConsonantSettings(
        glyph_substitutions={
            CONSONANT_LO_CHULA: [SubstitutionRule(replacement="short_tail", conditions=frozenset({SUB_ABOVE_VOWEL}))]
        }
    )
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_ABOVE_VOWEL})) == "short_tail"
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_ABOVE_VOWEL, SUB_TONE_MARK})) == (
        "short_tail"
    )
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_TONE_MARK})) == "short_tail"
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == (
        "short_tail"
    )
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_BELOW_VOWEL})) is None


def test_consonant_rule_round_trip_collapses_above_stacks(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "consonants": {
            "U+0E2C": {
                "glyph_substitutions": {
                    "U+0E2C": [{"replacement": "short_tail", "conditions": ["below_vowel", "tone_mark"]}]
                }
            }
        },
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    settings = load_placement_settings(path)
    cs = settings.for_consonant(CONSONANT_LO_CHULA)
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == (
        "short_tail"
    )
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_TONE_MARK})) == "short_tail"
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_ABOVE_VOWEL})) == "short_tail"
    assert cs.substitution_for(CONSONANT_LO_CHULA, present_roles=frozenset({SUB_BELOW_VOWEL})) is None


def test_down_consonant_rule_fires_only_with_below_vowel() -> None:
    cs = ConsonantSettings(
        glyph_substitutions={
            CONSONANT_YO_YING: [SubstitutionRule(replacement="cut_base", conditions=frozenset({SUB_BELOW_VOWEL}))]
        }
    )
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_BELOW_VOWEL})) == "cut_base"
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == (
        "cut_base"
    )
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_TONE_MARK})) is None
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_ABOVE_VOWEL})) is None
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_ABOVE_VOWEL, SUB_TONE_MARK})) is None


def test_down_consonant_rule_below_plus_tone_fires_for_below_only() -> None:
    cs = ConsonantSettings(
        glyph_substitutions={
            CONSONANT_YO_YING: [
                SubstitutionRule(replacement="cut_base", conditions=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK}))
            ]
        }
    )
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_BELOW_VOWEL})) == "cut_base"
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == (
        "cut_base"
    )
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_TONE_MARK})) is None


def test_unlisted_consonant_rule_keeps_generic_tone_merge() -> None:
    cs = ConsonantSettings(
        glyph_substitutions={
            CONSONANT_KO_KAI: [SubstitutionRule(replacement="alt", conditions=frozenset({SUB_BELOW_VOWEL}))]
        }
    )
    assert cs.substitution_for(CONSONANT_KO_KAI, present_roles=frozenset({SUB_BELOW_VOWEL})) == "alt"
    assert cs.substitution_for(CONSONANT_KO_KAI, present_roles=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == "alt"
    assert cs.substitution_for(CONSONANT_KO_KAI, present_roles=frozenset({SUB_TONE_MARK})) is None


def test_down_consonant_rule_round_trip_collapses_to_below_family(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "consonants": {
            "U+0E0D": {
                "glyph_substitutions": {
                    "U+0E0D": [{"replacement": "cut_base", "conditions": ["below_vowel", "tone_mark"]}]
                }
            }
        },
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    settings = load_placement_settings(path)
    cs = settings.for_consonant(CONSONANT_YO_YING)
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_BELOW_VOWEL})) == "cut_base"
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == (
        "cut_base"
    )
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_TONE_MARK})) is None


def test_down_consonant_rule_serializes_conditions_in_canonical_form() -> None:
    settings = PlacementSettings(
        consonants={
            CONSONANT_YO_YING: ConsonantSettings(
                glyph_substitutions={
                    CONSONANT_YO_YING: [
                        SubstitutionRule(replacement="cut_base", conditions=frozenset({SUB_BELOW_VOWEL}))
                    ]
                }
            )
        }
    )
    payload = settings_to_dict(settings)
    rules = payload["consonants"]["U+0E0D"]["glyph_substitutions"]["U+0E0D"]
    assert rules == [{"replacement": "cut_base", "conditions": ["below_vowel"]}]


def test_up_consonant_rule_serializes_conditions_in_canonical_form() -> None:
    settings = PlacementSettings(
        consonants={
            CONSONANT_LO_CHULA: ConsonantSettings(
                glyph_substitutions={
                    CONSONANT_LO_CHULA: [
                        SubstitutionRule(replacement="short_tail", conditions=frozenset({SUB_TONE_MARK}))
                    ]
                }
            )
        }
    )
    payload = settings_to_dict(settings)
    rules = payload["consonants"]["U+0E2C"]["glyph_substitutions"]["U+0E2C"]
    assert rules == [{"replacement": "short_tail", "conditions": ["above_vowel", "tone_mark"]}]
