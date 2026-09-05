"""Thai orthographic constants as concrete enum classes."""

from enum import IntEnum


class Consonant(IntEnum):
    """The 42 modern Thai consonants in canonical codepoint order."""

    KO_KAI = 0x0E01
    KHO_KHAI = 0x0E02
    KHO_KHON = 0x0E04
    KHO_RAKHANG = 0x0E06
    NGO_NGU = 0x0E07
    CHO_CHAN = 0x0E08
    CHO_CHING = 0x0E09
    CHO_CHANG = 0x0E0A
    SO_SO = 0x0E0B
    CHO_CHOE = 0x0E0C
    YO_YING = 0x0E0D
    DO_CHADA = 0x0E0E
    TO_PATAK = 0x0E0F
    THO_THAN = 0x0E10
    THO_MONTHO = 0x0E11
    THO_PHUTHAO = 0x0E12
    NO_NEN = 0x0E13
    DO_DEK = 0x0E14
    TO_TAO = 0x0E15
    THO_THUNG = 0x0E16
    THO_THAHAN = 0x0E17
    THO_THONG = 0x0E18
    NO_NU = 0x0E19
    BO_BAIMAI = 0x0E1A
    PO_PLA = 0x0E1B
    PHO_PHUENG = 0x0E1C
    FO_FA = 0x0E1D
    PHO_PHAN = 0x0E1E
    FO_FAN = 0x0E1F
    PHO_SAMPHAO = 0x0E20
    MO_MA = 0x0E21
    YO_YAK = 0x0E22
    RO_RUA = 0x0E23
    LO_LING = 0x0E25
    WO_WAEN = 0x0E27
    SO_SALA = 0x0E28
    SO_RUSI = 0x0E29
    SO_SUA = 0x0E2A
    HO_HIP = 0x0E2B
    LO_CHULA = 0x0E2C
    O_ANG = 0x0E2D
    HO_NOKHUK = 0x0E2E


class BelowVowel(IntEnum):
    """Vowels rendered below the consonant."""

    SARA_U = 0x0E38
    SARA_UU = 0x0E39


class AboveVowel(IntEnum):
    """Vowels rendered above the consonant, including NIKHAHIT."""

    MAI_HAN_AKAT = 0x0E31
    SARA_I = 0x0E34
    SARA_II = 0x0E35
    SARA_UE = 0x0E36
    SARA_UEE = 0x0E37
    MAI_TAI_KHU = 0x0E47
    NIKHAHIT = 0x0E4D


class ToneMark(IntEnum):
    """Tone marks stacking above, including THANTHAKHAT as a stacking mark."""

    MAI_EK = 0x0E48
    MAI_THO = 0x0E49
    MAI_TRI = 0x0E4A
    MAI_CHATTAWA = 0x0E4B
    THANTHAKHAT = 0x0E4C


CONSONANTS: tuple[Consonant, ...] = tuple(Consonant)
"""Canonical consonant order; index here is the grid consonant index."""

CONSONANT_INDEX: dict[int, int] = {c.value: i for i, c in enumerate(CONSONANTS)}

BELOW_VOWELS: frozenset[int] = frozenset(v.value for v in BelowVowel)
ABOVE_VOWELS: frozenset[int] = frozenset(v.value for v in AboveVowel)
TONE_MARKS: frozenset[int] = frozenset(t.value for t in ToneMark)

CONSONANT_PROTRUSION: dict[int, str] = {0x0E2C: "ascender"}
"""Protrusion direction scoping consonant self-substitutions; only ascender consonants are listed."""

UNCLUSTERED: frozenset[int] = frozenset({0x0E30, 0x0E32, 0x0E40, 0x0E41, 0x0E46})
"""Codepoints passing through the encoder without clustering (safe raw advance)."""

NEEDS_SHAPER: frozenset[int] = frozenset({0x0E42, 0x0E43, 0x0E44, 0x0E45})
"""Codepoints whose ink overlaps the previous glyph without a shaper."""
