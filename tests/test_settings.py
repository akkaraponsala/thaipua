"""Unit tests for `ConsonantSettings.offset_for` tier layering."""

from __future__ import annotations

from thaipua.core.fonttools.settings import (
    ROLE_TONE_MARK,
    ROLE_TONE_MARK_ON_ABOVE_VOWEL,
    ConsonantSettings,
    Offset,
)

TONE_MAI_EK = 0x0E48
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
