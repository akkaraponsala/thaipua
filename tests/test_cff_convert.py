"""Integration tests for in-memory CFF-to-TrueType conversion using a built `.otf` fixture."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from conftest import SAMPLE_FONT_PATH
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont

from thaipua.core.font.cff_convert import MAX_APPROXIMATION_ERROR, convert_cff_to_truetype, has_cff_outlines
from thaipua.core.font.composer import InstallStatus, ThaiPuaFontGenerator
from thaipua.gui.font_service import FontService

_TRUETYPE_SFNT_VERSION = "\000\001\000\000"


def _square_charstring(width: int, size: int) -> Any:
    """Return a simple closed-square charstring of `size` units with advance `width`."""
    pen = T2CharStringPen(width, None)
    pen.moveTo((0, 0))
    pen.lineTo((size, 0))
    pen.lineTo((size, size))
    pen.lineTo((0, size))
    pen.closePath()
    return pen.getCharString()


def _write_cff_otf(path: Path) -> Path:
    """Write a minimal three-glyph CFF-flavored font covering ก and a tone mark."""
    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder([".notdef", "ko_kai", "mai_ek"])
    builder.setupCharacterMap({0x0E01: "ko_kai", 0x0E48: "mai_ek"})
    charstrings = {
        ".notdef": _square_charstring(600, 500),
        "ko_kai": _square_charstring(550, 400),
        "mai_ek": _square_charstring(500, 300),
    }
    builder.setupCFF(
        "TestCFF", {"FamilyName": "TestCFF", "FullName": "TestCFF Regular", "Weight": "Regular"}, charstrings, {}
    )
    builder.setupHorizontalMetrics({".notdef": (600, 0), "ko_kai": (550, 0), "mai_ek": (500, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "TestCFF", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200)
    builder.setupPost()
    builder.save(str(path))
    return path


def _contour_bounds(font: TTFont, glyph_name: str) -> tuple[int, int, int, int]:
    pen = BoundsPen(font.getGlyphSet())
    font.getGlyphSet()[glyph_name].draw(pen)
    assert pen.bounds is not None
    x_min, y_min, x_max, y_max = pen.bounds
    return (int(x_min), int(y_min), int(x_max), int(y_max))


def test_convert_flips_flavor_and_preserves_cmap_and_geometry(tmp_path: Path) -> None:
    src = _write_cff_otf(tmp_path / "src.otf")
    font = TTFont(str(src))
    assert has_cff_outlines(font)

    convert_cff_to_truetype(font)

    assert not has_cff_outlines(font)
    assert font.sfntVersion == _TRUETYPE_SFNT_VERSION
    assert font.getBestCmap()[0x0E01] == "ko_kai"
    assert _contour_bounds(font, "ko_kai") == (0, 0, 400, 400)
    width, lsb = font["hmtx"]["ko_kai"]
    assert width == 550
    assert lsb == 0


def test_convert_is_a_no_op_for_truetype_fonts(tmp_path: Path) -> None:
    ttf = TTFont(str(SAMPLE_FONT_PATH))
    assert not has_cff_outlines(ttf)
    convert_cff_to_truetype(ttf)
    assert "glyf" in ttf


def test_generator_converts_source_and_installs_composites(tmp_path: Path) -> None:
    src = _write_cff_otf(tmp_path / "src.otf")
    generator = ThaiPuaFontGenerator(str(src), None)

    assert generator.source_is_cff is True
    assert not has_cff_outlines(generator.font)

    result = generator.install_composite(0xE000, 0x0E01, tone_uni=0x0E48)

    assert result.status is InstallStatus.INSTALLED
    out = tmp_path / "out.ttf"
    generator.font.save(str(out))
    reloaded = TTFont(str(out))
    assert reloaded.sfntVersion == _TRUETYPE_SFNT_VERSION
    assert reloaded.getBestCmap()[0xE000] == "thaipua_E000"


def test_load_font_defaults_output_to_ttf_for_cff_sources(tmp_path: Path) -> None:
    src = _write_cff_otf(tmp_path / "Test.otf")
    service = FontService()
    service.load_font(src, profiles_dir=tmp_path / "profiles")
    assert service.output_path == str(tmp_path / "Test_pua.ttf")


def test_approximation_error_constant_matches_fonttools_reference() -> None:
    assert MAX_APPROXIMATION_ERROR == 1.0
