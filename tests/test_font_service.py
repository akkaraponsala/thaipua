"""Unit tests for `FontService`'s font-aware PUA collision handling."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from thaipua.core.encoding import load_pua_map_dict
from thaipua.core.fonttools.composer import ThaiPuaFontGenerator
from thaipua.core.pua_allocator import save_pua_map
from thaipua.gui.font_service import FontService


class _FakeGlyph:
    """Minimal stand-in for a `glyf` glyph exposing only `isComposite`."""

    def __init__(self, composite: bool) -> None:
        self._composite = composite

    def isComposite(self) -> bool:
        return self._composite


class _FakeGlyf:
    """Dict-like stand-in for a `glyf` table keyed by glyph name."""

    def __init__(self, glyphs: dict[str, _FakeGlyph]) -> None:
        self._glyphs = glyphs

    def __contains__(self, name: str) -> bool:
        return name in self._glyphs

    def __getitem__(self, name: str) -> _FakeGlyph:
        return self._glyphs[name]


class _FakeFont:
    """Duck-typed `TTFont` exposing only `getBestCmap` and `get`."""

    def __init__(self, cmap: dict[int, str], glyf: _FakeGlyf | None = None) -> None:
        self._cmap = cmap
        self._glyf = glyf

    def getBestCmap(self) -> dict[int, str]:
        return self._cmap

    def get(self, key: str) -> Any:
        return self._glyf if key == "glyf" else None


def _service_with_font(cmap: dict[int, str], glyf: _FakeGlyf | None = None) -> FontService:
    service = FontService()
    service._gen = cast(ThaiPuaFontGenerator, SimpleNamespace(font=_FakeFont(cmap, glyf)))
    return service


def test_foreign_pua_chars_is_empty_without_a_font() -> None:
    assert FontService()._foreign_pua_chars() == set()


def test_foreign_pua_chars_excludes_composite_glyphs() -> None:
    cmap = {0xE000: "simple", 0xE001: "composite", 0x0E01: "ko_kai"}
    glyf = _FakeGlyf({"simple": _FakeGlyph(False), "composite": _FakeGlyph(True)})
    assert _service_with_font(cmap, glyf)._foreign_pua_chars() == {chr(0xE000)}


def test_foreign_pua_chars_reserves_cmap_entries_without_a_glyf_glyph() -> None:
    cmap = {0xE000: "ghost", 0xE001: "composite"}
    glyf = _FakeGlyf({"composite": _FakeGlyph(True)})
    assert _service_with_font(cmap, glyf)._foreign_pua_chars() == {chr(0xE000)}


def test_foreign_pua_chars_reserves_everything_without_a_glyf_table() -> None:
    cmap = {0xE000: "simple", 0xE001: "composite", 0x0E01: "ko_kai"}
    assert _service_with_font(cmap, None)._foreign_pua_chars() == {chr(0xE000), chr(0xE001)}


def test_repair_pua_map_reallocates_collisions_and_persists(tmp_path: Path) -> None:
    service = FontService()
    service.set_pua_map_path(str(tmp_path / "pua.json"))
    mapping = {"ก": chr(0xE000), "ข": chr(0xE001)}
    save_pua_map(mapping, service.pua_map_path)
    font = _FakeFont({0xE000: "foreign"}, _FakeGlyf({"foreign": _FakeGlyph(False)}))
    service._gen = cast(ThaiPuaFontGenerator, SimpleNamespace(font=font))
    repaired = service._repair_pua_map(mapping)
    assert repaired["ก"] != chr(0xE000)
    assert repaired["ข"] == chr(0xE001)
    assert service.pua_map == repaired
    assert load_pua_map_dict(service.pua_map_path) == repaired


def test_repair_pua_map_leaves_non_colliding_map_untouched(tmp_path: Path) -> None:
    service = FontService()
    service.set_pua_map_path(str(tmp_path / "pua.json"))
    mapping = {"ก": chr(0xE000), "ข": chr(0xE001)}
    service._pua_map = mapping
    font = _FakeFont({}, _FakeGlyf({}))
    service._gen = cast(ThaiPuaFontGenerator, SimpleNamespace(font=font))
    assert service._repair_pua_map(mapping) == mapping
    assert service.pua_map == mapping
    assert not Path(service.pua_map_path).exists()
