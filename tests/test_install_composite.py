"""Integration tests for `ThaiPuaFontGenerator.install_composite` against the sample font."""

from __future__ import annotations

from pathlib import Path

import pytest

from thaipua.core.constants import PUA_RANGE_END, PUA_RANGE_START
from thaipua.core.font.composer import InstallResult, InstallStatus, ThaiPuaFontGenerator
from thaipua.core.font.ownership import TOOL_GLYPH_PREFIX

KO_KAI = 0x0E01


def _first_free_pua_code(gen: ThaiPuaFontGenerator) -> int:
    """Return the lowest PUA codepoint unmapped in the live font."""
    cmap = gen.font.getBestCmap()
    for codepoint in range(PUA_RANGE_START, PUA_RANGE_END + 1):
        if codepoint not in cmap:
            return codepoint
    pytest.skip("no free PUA codepoint in the sample font")


def _claim_pua_slot(gen: ThaiPuaFontGenerator, codepoint: int, glyph_name: str) -> None:
    """Map `codepoint` to `glyph_name` on every Unicode `cmap` subtable and the cached copy."""
    for table in gen.font["cmap"].tables:
        if table.isUnicode():
            table.cmap[codepoint] = glyph_name
    gen._cmap[codepoint] = glyph_name


def _glyph_order_count(gen: ThaiPuaFontGenerator, glyph_name: str) -> int:
    return sum(1 for name in gen.font.getGlyphOrder() if name == glyph_name)


def test_fresh_install_onto_free_codepoint(generator: ThaiPuaFontGenerator) -> None:
    pua_code = _first_free_pua_code(generator)
    expected_name = f"{TOOL_GLYPH_PREFIX}{pua_code:04X}"

    result = generator.install_composite(pua_code, KO_KAI)

    assert isinstance(result, InstallResult)
    assert result.status is InstallStatus.INSTALLED
    assert result.glyph_name == expected_name
    assert generator.font.getBestCmap()[pua_code] == expected_name
    assert generator.font["glyf"][expected_name].isComposite()
    assert _glyph_order_count(generator, expected_name) == 1


def test_reinstall_replaces_in_place_under_the_same_name(generator: ThaiPuaFontGenerator) -> None:
    pua_code = _first_free_pua_code(generator)
    expected_name = f"{TOOL_GLYPH_PREFIX}{pua_code:04X}"
    first = generator.install_composite(pua_code, KO_KAI)
    assert first.status is InstallStatus.INSTALLED

    second = generator.install_composite(pua_code, KO_KAI)

    assert second.status is InstallStatus.REPLACED_OWNED
    assert second.glyph_name == expected_name
    assert _glyph_order_count(generator, expected_name) == 1
    assert generator.font.getBestCmap()[pua_code] == expected_name


def test_locked_slot_is_skipped_without_writes(generator: ThaiPuaFontGenerator) -> None:
    cmap = generator.font.getBestCmap()
    if 0x0E01 not in cmap:
        pytest.skip("sample font has no ko-kai glyph")
    simple_name = cmap[0x0E01]
    pua_code = _first_free_pua_code(generator)
    _claim_pua_slot(generator, pua_code, simple_name)
    glyf_before = generator.font["glyf"][simple_name]

    result = generator.install_composite(pua_code, KO_KAI)

    assert result.status is InstallStatus.SKIPPED_LOCKED
    assert result.glyph_name == simple_name
    assert generator.font["glyf"][simple_name] is glyf_before
    assert generator.font.getBestCmap()[pua_code] == simple_name


def test_locked_slot_installs_only_with_user_override(generator: ThaiPuaFontGenerator) -> None:
    cmap = generator.font.getBestCmap()
    if 0x0E01 not in cmap:
        pytest.skip("sample font has no ko-kai glyph")
    simple_name = cmap[0x0E01]
    pua_code = _first_free_pua_code(generator)
    _claim_pua_slot(generator, pua_code, simple_name)
    glyf_before = generator.font["glyf"][simple_name]
    expected_name = f"{TOOL_GLYPH_PREFIX}{pua_code:04X}"

    denied = generator.install_composite(pua_code, KO_KAI, allowed_locked=frozenset())
    assert denied.status is InstallStatus.SKIPPED_LOCKED

    result = generator.install_composite(pua_code, KO_KAI, allowed_locked=frozenset({pua_code}))

    assert result.status is InstallStatus.OVERRIDDEN_LOCKED
    assert result.glyph_name == expected_name
    assert generator.font.getBestCmap()[pua_code] == expected_name
    assert generator.font["glyf"][expected_name].isComposite()
    assert generator.font["glyf"][simple_name] is glyf_before


def test_prefix_persists_across_save_reload_roundtrip(generator: ThaiPuaFontGenerator, tmp_path: Path) -> None:
    pua_code = _first_free_pua_code(generator)
    saved_path = tmp_path / "roundtrip.ttf"
    generator.install_composite(pua_code, KO_KAI)
    generator.font.save(str(saved_path))

    reloaded = ThaiPuaFontGenerator(str(saved_path), None)
    try:
        expected_name = f"{TOOL_GLYPH_PREFIX}{pua_code:04X}"
        result = reloaded.install_composite(pua_code, KO_KAI)
        assert result.status is InstallStatus.REPLACED_OWNED
        assert reloaded.font.getBestCmap()[pua_code] == expected_name
        assert reloaded.font["glyf"][expected_name].isComposite()
    finally:
        reloaded.font.close()


def test_missing_consonant_is_reported_not_raised(generator: ThaiPuaFontGenerator) -> None:
    pua_code = _first_free_pua_code(generator)

    result = generator.install_composite(pua_code, 0xFFFF)

    assert result.status is InstallStatus.SKIPPED_MISSING_CONSONANT
    assert result.glyph_name is None
    assert pua_code not in generator.font.getBestCmap()


def test_global_mark_offset_shifts_composed_tone_component(generator: ThaiPuaFontGenerator) -> None:
    from thaipua.core.fonttools.settings import ROLE_TONE_MARK, Offset, PlacementSettings

    tone_mai_ek = 0x0E48
    baseline = generator.compose_components(KO_KAI, None, None, tone_mai_ek)
    assert baseline is not None
    assert len(baseline) == 2
    if 0x0E48 not in generator._cmap:
        pytest.skip("sample font has no mai-ek glyph")

    settings = PlacementSettings(marks={ROLE_TONE_MARK: {tone_mai_ek: Offset(-40, -5)}})
    shifted = generator.compose_components(KO_KAI, None, None, tone_mai_ek, settings=settings)

    assert shifted is not None
    assert [p.glyph_name for p in shifted] == [p.glyph_name for p in baseline]
    base_tx, base_ty = baseline[1].transform[4], baseline[1].transform[5]
    new_tx, new_ty = shifted[1].transform[4], shifted[1].transform[5]
    assert (new_tx, new_ty) == (base_tx - 40, base_ty - 5)
