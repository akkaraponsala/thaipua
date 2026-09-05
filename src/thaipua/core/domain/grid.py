"""Slot grid: the fixed stride-60 combination space."""

from pydantic import BaseModel, ConfigDict

from thaipua.core.domain.errors import GridError
from thaipua.core.domain.thai import CONSONANTS, AboveVowel, BelowVowel, ToneMark


def _build_legal_combos() -> tuple[str, ...]:
    """Generate the provably-closed 60-combination space in `(below, above, tone)` order."""
    below_opts: tuple[int | None, ...] = (None, BelowVowel.SARA_U, BelowVowel.SARA_UU)
    above_opts: tuple[int | None, ...] = (
        None,
        AboveVowel.MAI_HAN_AKAT,
        AboveVowel.SARA_I,
        AboveVowel.SARA_II,
        AboveVowel.SARA_UE,
        AboveVowel.SARA_UEE,
        AboveVowel.MAI_TAI_KHU,
        AboveVowel.NIKHAHIT,
    )
    tone_opts: tuple[int | None, ...] = (
        None,
        ToneMark.MAI_EK,
        ToneMark.MAI_THO,
        ToneMark.MAI_TRI,
        ToneMark.MAI_CHATTAWA,
        ToneMark.THANTHAKHAT,
    )
    combos: list[str] = []
    for below in below_opts:
        for above in above_opts:
            for tone in tone_opts:
                if below is not None and above is not None:
                    continue
                combos.append("".join(chr(c) for c in (below, above, tone) if c is not None))
    return tuple(combos)


LEGAL_COMBOS: tuple[str, ...] = _build_legal_combos()
"""All 60 legal suffixes, bare consonant (`""`) first; generated from domain facts."""

PER_CONSONANT: int = len(LEGAL_COMBOS)

EXCLUDED_COMBOS: frozenset[str] = frozenset(
    {
        "",  # bare consonant: no slot in the shipped table
        chr(0x0E31) + chr(0x0E4C),
        chr(0x0E35) + chr(0x0E4C),
        chr(0x0E36) + chr(0x0E4C),
        chr(0x0E37) + chr(0x0E4C),
        chr(0x0E39) + chr(0x0E4C),
        chr(0x0E47) + chr(0x0E48),
        chr(0x0E47) + chr(0x0E49),
        chr(0x0E47) + chr(0x0E4A),
        chr(0x0E47) + chr(0x0E4B),
        chr(0x0E47) + chr(0x0E4C),
        chr(0x0E4D) + chr(0x0E4C),
    }
)
"""Reserved-but-unmaterialized holes; hand-picked product choice, deliberately not derived by rule."""

MATERIALIZED: tuple[str, ...] = tuple(c for c in LEGAL_COMBOS if c not in EXCLUDED_COMBOS)

GRID_VERSION: int = 2
STRIDE: int = 60

if PER_CONSONANT != 60:
    raise GridError(f"PER_CONSONANT must be 60, got {PER_CONSONANT}")
if STRIDE < PER_CONSONANT:
    raise GridError(f"stride {STRIDE} cannot hold {PER_CONSONANT} combos")
if len(set(LEGAL_COMBOS)) != len(LEGAL_COMBOS):
    raise GridError("duplicate combos in LEGAL_COMBOS")
if not set(MATERIALIZED) <= set(LEGAL_COMBOS):
    raise GridError("MATERIALIZED must be a subset of LEGAL_COMBOS")


class GridSpec(BaseModel):
    """One registered grid geometry; only version 2 exists (Decision 1)."""

    model_config = ConfigDict(frozen=True)

    version: int = GRID_VERSION
    stride: int = STRIDE
    per_consonant: int = PER_CONSONANT


GRID_SPECS: dict[int, GridSpec] = {GRID_VERSION: GridSpec()}
"""Single registered grid; a future v3 registers here with its own golden test."""


class SlotGrid(BaseModel):
    """Ordinal math for the fixed grid: `ordinal = cons_index * stride + combo_index`."""

    model_config = ConfigDict(frozen=True)

    spec: GridSpec = GRID_SPECS[GRID_VERSION]

    def ordinal(self, cons_index: int, combo_index: int) -> int:
        """Return the slot ordinal for a consonant/combo position pair."""
        if not 0 <= cons_index < len(CONSONANTS):
            raise GridError(f"consonant index out of range: {cons_index}")
        if not 0 <= combo_index < PER_CONSONANT:
            raise GridError(f"combo index out of range: {combo_index}")
        return cons_index * self.spec.stride + combo_index

    def codepoint(self, base: int, cons_index: int, combo_index: int) -> int:
        """Return the absolute codepoint for `base` plus the slot ordinal."""
        return base + self.ordinal(cons_index, combo_index)

    def combo_index_of(self, suffix: str) -> int:
        """Return the combo index of a suffix, raising `GridError` when illegal."""
        try:
            return LEGAL_COMBOS.index(suffix)
        except ValueError:
            raise GridError(f"not a legal combo: {suffix!r}") from None
