"""Unit tests for placement-offset tier resolution and substitution matching."""

from __future__ import annotations

import json
from pathlib import Path

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
    canonicalize_consonant_context,
    canonicalize_substitution_context,
    canonicalize_tone_mark_context,
    settings_to_dict,
)
from thaipua.core.fonttools.settings import (
    load_placement_settings,
    save_placement_settings,
)

TONE_MAI_EK = 0x0E48
CONSONANT_LO_CHULA = 0x0E2C
CONSONANT_YO_YING = 0x0E0D
CONSONANT_KO_KAI = 0x0E01
VOWEL_SARA_U = 0x0E38
VOWEL_SARA_AA = 0x0E32
VOWEL_MAI_HAN_AKAT = 0x0E31


def _resolve(
    cs: ConsonantSettings, role: str, *, mark_uni: int, combo_key: str | None, base_role: str | None = None
) -> Offset:
    """Resolve `cs` through `PlacementSettings.mark_offset_for` with an empty global tier."""
    settings = PlacementSettings(consonants={CONSONANT_KO_KAI: cs})
    return settings.mark_offset_for(CONSONANT_KO_KAI, role, mark_uni=mark_uni, combo_key=combo_key, base_role=base_role)


def test_mark_offset_adds_to_base_offset() -> None:
    cs = ConsonantSettings(
        base_offsets={ROLE_TONE_MARK: Offset(-150, 10)},
        mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-1, 2)}},
    )
    assert _resolve(cs, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None) == Offset(-151, 12)


def test_combo_offset_adds_to_base_offset() -> None:
    cs = ConsonantSettings(
        base_offsets={ROLE_TONE_MARK: Offset(0, -20)},
        combo_offsets={f"{chr(VOWEL_MAI_HAN_AKAT)}{chr(TONE_MAI_EK)}": {ROLE_TONE_MARK: Offset(5, 3)}},
    )
    off = _resolve(cs, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=f"{chr(VOWEL_MAI_HAN_AKAT)}{chr(TONE_MAI_EK)}")
    assert off == Offset(5, -17)


def test_tone_on_above_vowel_resolves_stacked_base_role() -> None:
    cs = ConsonantSettings(
        base_offsets={
            ROLE_TONE_MARK_ON_ABOVE_VOWEL: Offset(-150, 0),
            ROLE_TONE_MARK: Offset(-10, 0),
        },
        mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-1, 0)}},
    )
    off = _resolve(cs, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None, base_role=ROLE_TONE_MARK_ON_ABOVE_VOWEL)
    assert off == Offset(-151, 0)


def test_base_role_falls_back_to_role() -> None:
    cs = ConsonantSettings(base_offsets={ROLE_TONE_MARK: Offset(-10, 0)})
    off = _resolve(cs, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None, base_role=ROLE_TONE_MARK_ON_ABOVE_VOWEL)
    assert off == Offset(-10, 0)


def test_mark_offset_without_base_tier() -> None:
    cs = ConsonantSettings(mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-1, 0)}})
    assert _resolve(cs, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None) == Offset(-1, 0)


def test_no_tiers_yields_zero() -> None:
    assert _resolve(ConsonantSettings(), ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None) == Offset()


def test_canonicalize_tone_mark_context_merges_below_family_with_tone_only() -> None:
    assert canonicalize_tone_mark_context(frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == frozenset({SUB_TONE_MARK})
    assert canonicalize_tone_mark_context(frozenset({SUB_BELOW_VOWEL})) == frozenset({SUB_TONE_MARK})
    assert canonicalize_tone_mark_context(frozenset({SUB_TONE_MARK})) == frozenset({SUB_TONE_MARK})


def test_canonicalize_tone_mark_context_keeps_above_vowel_and_empty_families() -> None:
    assert canonicalize_tone_mark_context(frozenset({SUB_ABOVE_VOWEL, SUB_TONE_MARK})) == frozenset({SUB_ABOVE_VOWEL})
    assert canonicalize_tone_mark_context(frozenset({SUB_ABOVE_VOWEL})) == frozenset({SUB_ABOVE_VOWEL})
    assert canonicalize_tone_mark_context(frozenset()) == frozenset()


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


def test_canonicalize_substitution_context_unchanged_within_vowel_families() -> None:
    assert canonicalize_substitution_context(frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == frozenset(
        {SUB_BELOW_VOWEL}
    )
    assert canonicalize_substitution_context(frozenset({SUB_TONE_MARK})) == frozenset({SUB_TONE_MARK})


def test_canonicalize_consonant_context_ascender_families() -> None:
    assert canonicalize_consonant_context(frozenset({SUB_BELOW_VOWEL}), protrusion="ascender") == frozenset(
        {SUB_BELOW_VOWEL}
    )
    assert canonicalize_consonant_context(frozenset({SUB_TONE_MARK}), protrusion="ascender") == frozenset(
        {SUB_ABOVE_VOWEL, SUB_TONE_MARK}
    )
    assert canonicalize_consonant_context(frozenset({SUB_ABOVE_VOWEL}), protrusion="ascender") == frozenset(
        {SUB_ABOVE_VOWEL, SUB_TONE_MARK}
    )
    assert canonicalize_consonant_context(
        frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK}), protrusion="ascender"
    ) == frozenset({SUB_ABOVE_VOWEL, SUB_TONE_MARK})
    assert canonicalize_consonant_context(
        frozenset({SUB_ABOVE_VOWEL, SUB_TONE_MARK}), protrusion="ascender"
    ) == frozenset({SUB_ABOVE_VOWEL, SUB_TONE_MARK})
    assert canonicalize_consonant_context(frozenset(), protrusion="ascender") == frozenset()


def test_consonant_without_protrusion_uses_generic_families() -> None:
    assert canonicalize_consonant_context(frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK}), protrusion=None) == frozenset(
        {SUB_BELOW_VOWEL}
    )
    assert canonicalize_consonant_context(frozenset({SUB_TONE_MARK}), protrusion=None) == frozenset({SUB_TONE_MARK})
    assert canonicalize_consonant_context(frozenset({SUB_ABOVE_VOWEL, SUB_BELOW_VOWEL}), protrusion=None) == frozenset(
        {SUB_ABOVE_VOWEL, SUB_BELOW_VOWEL}
    )


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


def test_descender_below_rule_fires_only_with_below_present() -> None:
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


def test_descender_below_plus_tone_rule_fires_for_below_only() -> None:
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


def test_descender_rule_round_trip_loads_below_tone_as_below_only(tmp_path: Path) -> None:
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


def test_descender_rule_serializes_below_only_in_canonical_form() -> None:
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


def test_descender_loads_below_and_below_plus_above_as_distinct(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "consonants": {
            "U+0E0D": {
                "glyph_substitutions": {
                    "U+0E0D": [
                        {"replacement": "trim", "conditions": ["below_vowel"]},
                        {"replacement": "trim_wide", "conditions": ["above_vowel", "below_vowel"]},
                    ]
                }
            }
        },
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    settings = load_placement_settings(path)
    cs = settings.for_consonant(CONSONANT_YO_YING)
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_BELOW_VOWEL})) == "trim"
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_ABOVE_VOWEL, SUB_BELOW_VOWEL})) == (
        "trim_wide"
    )
    assert cs.substitution_for(CONSONANT_YO_YING, present_roles=frozenset({SUB_BELOW_VOWEL, SUB_TONE_MARK})) == "trim"
    payload = settings_to_dict(settings)
    rules = payload["consonants"]["U+0E0D"]["glyph_substitutions"]["U+0E0D"]
    assert rules == [
        {"replacement": "trim", "conditions": ["below_vowel"]},
        {"replacement": "trim_wide", "conditions": ["above_vowel", "below_vowel"]},
    ]


def test_ascender_consonant_rule_serializes_conditions_in_canonical_form() -> None:
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


def test_offset_add() -> None:
    assert Offset(1, 2) + Offset(3, 4) == Offset(4, 6)
    assert Offset() + Offset(-1, 0) == Offset(-1, 0)


def test_full_round_trip_preserves_settings(tmp_path: Path) -> None:
    settings = PlacementSettings(
        metadata=Metadata(font_name="Sarabun", family_name="Sarabun", units_per_em=1000),
        consonants={
            CONSONANT_YO_YING: ConsonantSettings(
                base_offsets={ROLE_TONE_MARK: Offset(-150, 10)},
                mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-1, 2)}},
                combo_offsets={f"{chr(VOWEL_MAI_HAN_AKAT)}{chr(TONE_MAI_EK)}": {ROLE_TONE_MARK: Offset(5, 3)}},
                snap_configs={"tone_mark_to_above_vowel": SnapConfig(enabled=True, gap=12)},
                glyph_substitutions={
                    CONSONANT_YO_YING: [
                        SubstitutionRule(replacement="cut_base", conditions=frozenset({SUB_BELOW_VOWEL}))
                    ]
                },
            )
        },
    )
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings_to_dict(settings)), encoding="utf-8")
    assert load_placement_settings(path) == settings


def test_load_rejects_unsupported_version(tmp_path: Path) -> None:
    data = {
        "version": 99,
        "consonants": {"U+0E1B": {"base_offsets": {"tone_mark": {"x": 1, "y": 0}}}},
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SettingsError, match="unsupported settings version 99"):
        load_placement_settings(path)


def test_load_missing_version_defaults_to_current(tmp_path: Path) -> None:
    data = {"consonants": {"U+0E1B": {"base_offsets": {"tone_mark": {"x": 1, "y": 0}}}}}
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_placement_settings(path).consonants[0x0E1B].base_offsets["tone_mark"] == Offset(x=1, y=0)


def test_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    assert load_placement_settings(tmp_path / "nope.json").consonants == {}


def test_load_invalid_json_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_placement_settings(path).consonants == {}


def test_load_rejects_raw_thai_character_keys(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "consonants": {"ก": {"base_offsets": {"tone_mark": {"x": 1, "y": 0}}}},
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SettingsError, match=r"not a U\+XXXX codepoint"):
        load_placement_settings(path)


def test_load_rejects_non_consonant_codepoint_keys(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "consonants": {
            "U+0E31": {"base_offsets": {"tone_mark": {"x": 1, "y": 0}}},
            "U+0E1B": {"base_offsets": {"tone_mark": {"x": 2, "y": 0}}},
        },
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SettingsError, match="not a Thai consonant"):
        load_placement_settings(path)


def test_load_rejects_mark_outside_group_category(tmp_path: Path) -> None:
    data = {
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
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SettingsError, match="not in the"):
        load_placement_settings(path)


def test_load_rejects_junk_combo_keys(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "consonants": {"U+0E1B": {"combo_offsets": {"U+0E31foo+U+0E48": {"tone_mark": {"x": 1, "y": 0}}}}},
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SettingsError, match=r"not a .* combo key"):
        load_placement_settings(path)


def test_load_rejects_duplicate_combo_codepoints(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "consonants": {"U+0E1B": {"combo_offsets": {"U+0E31+U+0E31": {"tone_mark": {"x": 1, "y": 0}}}}},
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SettingsError, match="repeats a codepoint"):
        load_placement_settings(path)


def test_load_normalizes_out_of_order_combo_key(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "consonants": {"U+0E1B": {"combo_offsets": {"U+0E48+U+0E31": {"tone_mark": {"x": 5, "y": 3}}}}},
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    cs = load_placement_settings(path).for_consonant(0x0E1B)
    assert cs.combo_offsets == {f"{chr(VOWEL_MAI_HAN_AKAT)}{chr(TONE_MAI_EK)}": {ROLE_TONE_MARK: Offset(5, 3)}}


def test_load_duplicate_condition_rules_last_wins(tmp_path: Path) -> None:
    data = {
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
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    cs = load_placement_settings(path).for_consonant(0x0E1B)
    assert cs.substitution_for(TONE_MAI_EK, present_roles=frozenset({SUB_TONE_MARK})) == "second"


def test_load_rejects_non_positive_and_fractional_units_per_em(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "metadata": {"units_per_em": -100},
        "consonants": {"U+0E1B": {"base_offsets": {"tone_mark": {"x": 0, "y": 0}}}},
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SettingsError, match="invalid settings document"):
        load_placement_settings(path)
    data["metadata"] = {"units_per_em": 1.5}
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SettingsError, match="invalid settings document"):
        load_placement_settings(path)


def test_load_rejects_empty_metadata_strings(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "metadata": {"font_name": "", "family_name": "Sarabun"},
        "consonants": {"U+0E1B": {"base_offsets": {"tone_mark": {"x": 0, "y": 0}}}},
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SettingsError, match="non-empty string"):
        load_placement_settings(path)


def test_load_rejects_fractional_offset(tmp_path: Path) -> None:
    data = {
        "version": 1,
        "consonants": {"U+0E1B": {"mark_offsets": {"tone_marks": {"U+0E48": {"x": 1.5, "y": 0}}}}},
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SettingsError, match="invalid settings document"):
        load_placement_settings(path)


def test_combo_cluster_resolves_from_combo_tier() -> None:
    combo_key = f"{chr(VOWEL_MAI_HAN_AKAT)}{chr(TONE_MAI_EK)}"
    cs = ConsonantSettings(
        mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(10, 20)}},
        combo_offsets={combo_key: {ROLE_TONE_MARK: Offset(5, -5)}},
    )
    assert _resolve(cs, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=combo_key) == Offset(5, -5)
    assert _resolve(cs, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None) == Offset(10, 20)


def test_combo_cluster_without_entry_resolves_to_zero() -> None:
    combo_key = f"{chr(VOWEL_MAI_HAN_AKAT)}{chr(TONE_MAI_EK)}"
    cs = ConsonantSettings(mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(10, 20)}})
    assert _resolve(cs, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=combo_key) == Offset()


def test_combo_and_base_offsets_stack() -> None:
    combo_key = f"{chr(VOWEL_MAI_HAN_AKAT)}{chr(TONE_MAI_EK)}"
    cs = ConsonantSettings(
        base_offsets={ROLE_TONE_MARK: Offset(1, 1)},
        mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(10, 20)}},
        combo_offsets={combo_key: {ROLE_TONE_MARK: Offset(5, -5)}},
    )
    assert _resolve(cs, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=combo_key) == Offset(6, -4)
    assert _resolve(cs, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None) == Offset(11, 21)


def test_state_single_and_combo_offsets_are_independent() -> None:
    from thaipua.core.font.specs import CompositeSpec
    from thaipua.gui.state import MarkCategory, apply_offset, current_mark_offset

    cons = CONSONANT_KO_KAI
    above = VOWEL_MAI_HAN_AKAT
    tone = TONE_MAI_EK
    spec_base = CompositeSpec(pua_code=0xE000, cons_uni=cons, above_uni=above)
    spec_combo = CompositeSpec(pua_code=0xE001, cons_uni=cons, above_uni=above, tone_uni=tone)
    settings = PlacementSettings()
    settings = apply_offset(spec_base, settings, 10, 20, category=MarkCategory.ABOVE_VOWEL)
    assert current_mark_offset(spec_base, settings, category=MarkCategory.ABOVE_VOWEL) == Offset(10, 20)
    assert current_mark_offset(spec_combo, settings, category=MarkCategory.ABOVE_VOWEL) == Offset(0, 0)
    combo_key = f"{chr(above)}{chr(tone)}"
    assert settings.mark_offset_for(cons, ROLE_ABOVE_VOWEL, mark_uni=above, combo_key=combo_key) == Offset()
    settings = apply_offset(spec_combo, settings, 5, -5, category=MarkCategory.ABOVE_VOWEL)
    assert current_mark_offset(spec_combo, settings, category=MarkCategory.ABOVE_VOWEL) == Offset(5, -5)
    assert settings.mark_offset_for(cons, ROLE_ABOVE_VOWEL, mark_uni=above, combo_key=combo_key) == Offset(5, -5)
    settings = apply_offset(spec_base, settings, 0, 0, category=MarkCategory.ABOVE_VOWEL)
    assert current_mark_offset(spec_base, settings, category=MarkCategory.ABOVE_VOWEL) == Offset(0, 0)
    assert current_mark_offset(spec_combo, settings, category=MarkCategory.ABOVE_VOWEL) == Offset(5, -5)


def test_combo_key_requires_two_marks() -> None:
    from thaipua.core.domain.settings import combo_key_for_marks

    assert combo_key_for_marks(None, VOWEL_MAI_HAN_AKAT, None) is None
    assert combo_key_for_marks(None, VOWEL_MAI_HAN_AKAT, TONE_MAI_EK) == f"{chr(VOWEL_MAI_HAN_AKAT)}{chr(TONE_MAI_EK)}"


def test_global_mark_offset_adds_to_per_consonant_and_base_tiers() -> None:
    settings = PlacementSettings(
        marks={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-40, 0)}},
        consonants={
            CONSONANT_KO_KAI: ConsonantSettings(
                base_offsets={ROLE_TONE_MARK: Offset(1, 2)},
                mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(10, 20)}},
            )
        },
    )
    off = settings.mark_offset_for(CONSONANT_KO_KAI, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None)
    assert off == Offset(-29, 22)


def test_global_mark_offset_applies_under_combo_tier() -> None:
    combo_key = f"{chr(VOWEL_MAI_HAN_AKAT)}{chr(TONE_MAI_EK)}"
    settings = PlacementSettings(
        marks={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-40, 0)}},
        consonants={CONSONANT_KO_KAI: ConsonantSettings(combo_offsets={combo_key: {ROLE_TONE_MARK: Offset(5, 5)}})},
    )
    off = settings.mark_offset_for(CONSONANT_KO_KAI, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=combo_key)
    assert off == Offset(-35, 5)


def test_mark_offset_for_without_global_entry_resolves_consonant_tiers() -> None:
    combo_key = f"{chr(VOWEL_MAI_HAN_AKAT)}{chr(TONE_MAI_EK)}"
    settings = PlacementSettings(
        consonants={
            CONSONANT_KO_KAI: ConsonantSettings(
                base_offsets={ROLE_TONE_MARK: Offset(1, 1)},
                mark_offsets={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(10, 20)}},
                combo_offsets={combo_key: {ROLE_TONE_MARK: Offset(5, -5)}},
            )
        }
    )
    single = settings.mark_offset_for(CONSONANT_KO_KAI, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None)
    combo = settings.mark_offset_for(CONSONANT_KO_KAI, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=combo_key)
    assert single == Offset(11, 21)
    assert combo == Offset(6, -4)


def test_global_mark_offset_is_scoped_to_its_role() -> None:
    settings = PlacementSettings(marks={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-40, 0)}})
    assert settings.mark_offset_for(
        CONSONANT_KO_KAI, ROLE_ABOVE_VOWEL, mark_uni=VOWEL_MAI_HAN_AKAT, combo_key=None
    ) == (Offset())


def test_global_marks_round_trip(tmp_path: Path) -> None:
    settings = PlacementSettings(
        metadata=Metadata(font_name="Sarabun"),
        marks={ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-40, 3)}},
        consonants={CONSONANT_KO_KAI: ConsonantSettings(base_offsets={ROLE_TONE_MARK: Offset(1, 1)})},
    )
    path = tmp_path / "settings.json"
    save_placement_settings(settings, path)
    save_and_load = load_placement_settings(path)
    assert save_and_load.marks == {ROLE_TONE_MARK: {TONE_MAI_EK: Offset(-40, 3)}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["marks"] == {"tone_marks": {"U+0E48": {"x": -40, "y": 3}}}


def test_load_v1_file_without_marks_yields_empty_global_tier(tmp_path: Path) -> None:
    data = {"version": 1, "consonants": {"U+0E01": {"base_offsets": {"tone_mark": {"x": 1, "y": 1}}}}}
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    settings = load_placement_settings(path)
    assert settings.marks == {}
    off = settings.mark_offset_for(CONSONANT_KO_KAI, ROLE_TONE_MARK, mark_uni=TONE_MAI_EK, combo_key=None)
    assert off == Offset(1, 1)


def test_apply_global_mark_offset_sets_updates_and_clears() -> None:
    from thaipua.gui.state import apply_global_mark_offset, current_global_mark_offset

    settings = PlacementSettings()
    settings = apply_global_mark_offset(ROLE_TONE_MARK, TONE_MAI_EK, -40, 0, settings)
    assert current_global_mark_offset(ROLE_TONE_MARK, TONE_MAI_EK, settings) == Offset(-40, 0)
    settings = apply_global_mark_offset(ROLE_TONE_MARK, TONE_MAI_EK, -35, 1, settings)
    assert current_global_mark_offset(ROLE_TONE_MARK, TONE_MAI_EK, settings) == Offset(-35, 1)
    settings = apply_global_mark_offset(ROLE_TONE_MARK, TONE_MAI_EK, 0, 0, settings)
    assert current_global_mark_offset(ROLE_TONE_MARK, TONE_MAI_EK, settings) == Offset()
    assert settings.marks == {}


def test_apply_global_mark_offset_rejects_unknown_role_or_codepoint() -> None:
    from thaipua.gui.state import apply_global_mark_offset

    settings = PlacementSettings()
    settings = apply_global_mark_offset("unknown_role", TONE_MAI_EK, -40, 0, settings)
    settings = apply_global_mark_offset(ROLE_TONE_MARK, CONSONANT_KO_KAI, -40, 0, settings)
    assert settings.marks == {}
