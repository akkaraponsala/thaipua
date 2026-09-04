"""Phase 0 golden test: the v2 stride-60 grid is frozen by digest, not by description."""

from __future__ import annotations

import hashlib

from thaipua.core.domain.cluster import ThaiCluster
from thaipua.core.domain.grid import EXCLUDED_COMBOS, LEGAL_COMBOS, MATERIALIZED, PER_CONSONANT, STRIDE
from thaipua.core.domain.layout import fresh_engine
from thaipua.core.layout import canonical_layout
from thaipua.core.pua_map import THAI_SUFFIXES

GOLDEN_V2_SHA256 = "05c08aff1b6b502a65e3089219fca31a9ad60af4b58eae2df871421bf536d44a"
BASE = 0xE000


def _digest(table: dict[ThaiCluster, int]) -> str:
    """Hash the full table in ordinal order, exactly as the proposal's Appendix A does."""
    return hashlib.sha256(
        "".join(f"{c.key}={cp:04X};" for c, cp in sorted(table.items(), key=lambda kv: kv[1])).encode()
    ).hexdigest()


def test_full_table_holds_2520_ordinals_with_golden_digest() -> None:
    full = fresh_engine(BASE).full_table()
    assert len(full) == 2520 == 42 * PER_CONSONANT
    assert _digest(full) == GOLDEN_V2_SHA256


def test_spot_checks_anchor_grid_geometry() -> None:
    full = fresh_engine(BASE).full_table()
    assert full[ThaiCluster.from_key("ก")] == BASE
    assert full[ThaiCluster.from_key("ก่")] == BASE + 1
    assert full[ThaiCluster.from_key("ข")] == BASE + STRIDE
    assert max(full.values()) == BASE + 42 * STRIDE - 1


def test_materialized_matches_legacy_suffixes_and_grows_free() -> None:
    canonical = canonical_layout(BASE)
    assert {key[1:] for key in canonical} == set(THAI_SUFFIXES)
    assert set(MATERIALIZED) == {key[1:] for key in canonical}
    assert set(LEGAL_COMBOS) - set(MATERIALIZED) == set(EXCLUDED_COMBOS)
    engine = fresh_engine(BASE)
    full = engine.full_table()
    for cluster, codepoint in engine.map.items():
        assert full[cluster] == codepoint


def test_v2_canonical_agrees_with_full_table() -> None:
    canonical = canonical_layout(BASE)
    full = fresh_engine(BASE).full_table()
    assert len(canonical) == 2016
    for key, char in canonical.items():
        assert full[ThaiCluster.from_key(key)] == ord(char)
