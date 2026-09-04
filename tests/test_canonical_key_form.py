"""Slice 1 pin: construction order is the stored key form; boundaries normalize input order."""

from __future__ import annotations

import json
from pathlib import Path

from thaipua.core.constants import THAI_CONSONANT_CHARS
from thaipua.core.domain.cluster import (
    ThaiCluster,
    canonical_cluster_key,
    canonical_cluster_text,
    canonical_suffix,
)
from thaipua.core.domain.grid import EXCLUDED_COMBOS, LEGAL_COMBOS, MATERIALIZED
from thaipua.core.domain.thai import AboveVowel, ToneMark
from thaipua.core.layout import canonical_layout, cluster_ordinal, load_layout_state
from thaipua.core.pua_map import save_pua_map
from thaipua.core.text.encoding import build_encode_transform, find_unshapable_spans, load_encoding_map
from thaipua.gui.font_service import FontService

NIKHAHIT = chr(AboveVowel.NIKHAHIT)
MAI_EK = chr(ToneMark.MAI_EK)
MAI_THO = chr(ToneMark.MAI_THO)
THANTHAKHAT = chr(ToneMark.THANTHAKHAT)
SARA_U = chr(0x0E38)

# Stored keys use grid construction order (below + above + tone, frozen by
# Decision 1); `ThaiCluster.key` sorts by codepoint instead, so the two forms
# diverge exactly for NIKHAHIT + tone (0xE4D sorts after every tone mark).
DIVERGENT_PAIRS = [(NIKHAHIT, chr(tone.value)) for tone in ToneMark]


def _write_map(tmp_path: Path, mapping: dict[str, str]) -> Path:
    map_path = tmp_path / "pua.json"
    save_pua_map(mapping, map_path)
    return map_path


def test_stored_suffixes_are_already_construction_order() -> None:
    assert all(canonical_suffix(suffix) == suffix for suffix in LEGAL_COMBOS)


def test_shipped_map_keys_survive_normalization() -> None:
    mapping = canonical_layout(0xE000)
    assert len(mapping) == 2016
    assert all(canonical_cluster_key(key) == key for key in mapping)


def test_divergence_inventory_is_exactly_nikhahit_times_five_tones() -> None:
    divergent = [
        consonant + suffix
        for consonant in THAI_CONSONANT_CHARS
        for suffix in LEGAL_COMBOS
        if ThaiCluster.from_key(consonant + suffix).key != consonant + suffix
    ]
    assert len(divergent) == 42 * len(ToneMark)
    assert all(ThaiCluster.from_key(key).above == AboveVowel.NIKHAHIT for key in divergent)
    shipped = [key for key in divergent if key[1:] not in EXCLUDED_COMBOS]
    assert len(shipped) == 42 * (len(ToneMark) - 1)
    assert {key[1:] for key in shipped} <= set(MATERIALIZED)


def test_parser_accepts_both_mark_orders() -> None:
    pairs = [("ก" + above + tone, "ก" + tone + above) for above, tone in DIVERGENT_PAIRS]
    pairs += [("ก" + SARA_U + MAI_EK, "ก" + MAI_EK + SARA_U)]
    for construction, reordered in pairs:
        assert ThaiCluster.from_key(construction) == ThaiCluster.from_key(reordered)


def test_encoder_treats_both_mark_orders_identically(tmp_path: Path) -> None:
    mapping = canonical_layout(0xE000)
    encoding_map = load_encoding_map(_write_map(tmp_path, mapping))
    assert encoding_map is not None
    encode = build_encode_transform(encoding_map)
    cases = [("ก" + NIKHAHIT + MAI_EK, "ก" + MAI_EK + NIKHAHIT), ("ก" + SARA_U + MAI_THO, "ก" + MAI_THO + SARA_U)]
    for construction, reordered in cases:
        assert encode(reordered) == encode(construction) == mapping[construction]
    hole, hole_reordered = "ก" + NIKHAHIT + THANTHAKHAT, "ก" + THANTHAKHAT + NIKHAHIT
    assert encode(hole) == encode(hole_reordered) == mapping["ก" + NIKHAHIT] + THANTHAKHAT


def test_illegal_runs_pass_through_untouched() -> None:
    assert canonical_suffix(MAI_EK + chr(ToneMark.MAI_THO)) is None
    assert canonical_suffix(SARA_U + chr(0x0E34)) is None
    assert canonical_suffix(MAI_EK + chr(0x0E32)) is None
    assert canonical_suffix("") == ""
    assert canonical_cluster_key("") is None
    assert canonical_cluster_key("ก" + MAI_EK + chr(ToneMark.MAI_THO)) is None
    assert canonical_cluster_key("abc") is None
    assert canonical_cluster_text("ก" + MAI_EK + chr(ToneMark.MAI_THO)) == "ก" + MAI_EK + chr(ToneMark.MAI_THO)


def test_cluster_ordinal_accepts_both_orders() -> None:
    construction, reordered = "ก" + NIKHAHIT + MAI_EK, "ก" + MAI_EK + NIKHAHIT
    assert cluster_ordinal(construction) == cluster_ordinal(reordered) is not None
    assert cluster_ordinal("ก") == 0
    assert cluster_ordinal("ก" + MAI_EK + chr(ToneMark.MAI_THO)) is None
    assert cluster_ordinal("ก" + SARA_U + chr(0x0E34)) is None
    assert cluster_ordinal("") is None


def test_normalization_preserves_offsets() -> None:
    text = "ก" + MAI_EK + NIKHAHIT + "แก่โ"
    assert len(canonical_cluster_text(text)) == len(text)
    assert find_unshapable_spans(canonical_cluster_text(text)) == find_unshapable_spans(text)


def _service_with_layout(tmp_path: Path) -> FontService:
    service = FontService()
    service.set_layout_path(str(tmp_path / "layout.json"))
    service.set_pua_map_path(str(tmp_path / "pua.json"))
    service.load_layout()
    return service


def test_relocate_normalizes_reordered_keys(tmp_path: Path) -> None:
    service = _service_with_layout(tmp_path)
    reordered = "ก" + MAI_EK + NIKHAHIT
    canonical = "ก" + NIKHAHIT + MAI_EK
    moved = service.relocate_keys([reordered])
    assert list(moved) == [canonical]
    assert service.pua_map[canonical] == chr(moved[canonical])
    second = service.relocate_key(reordered)
    assert second is not None
    assert second != moved[canonical]
    assert service.pua_map[canonical] == chr(second)
    assert service.relocate_key("not-a-cluster") is None
    assert service._layout is not None
    assert "not-a-cluster" not in service._layout.relocations


def test_layout_load_canonicalizes_relocation_keys(tmp_path: Path) -> None:
    layout_path = tmp_path / "layout.json"
    reordered = "ก" + MAI_EK + NIKHAHIT
    canonical = "ก" + NIKHAHIT + MAI_EK
    layout_path.write_text(
        json.dumps({"base": "E000", "relocations": {reordered: "𛲕", canonical: "𛲖"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    state = load_layout_state(layout_path)
    assert state is not None
    assert state.relocations == {canonical: "𛲖"}
