"""Unit tests for `FontService`'s PUA map loading and slot-context snapshotting."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from conftest import FakeGlyf, make_glyf

from thaipua.core.fonttools.composer import ThaiPuaFontGenerator
from thaipua.core.fonttools.specs import CompositeSpec
from thaipua.gui.font_service import FontService


class _FakeFont:
    """Duck-typed `TTFont` exposing only `getBestCmap` and `get`."""

    def __init__(self, cmap: dict[int, str], glyf: FakeGlyf | None = None) -> None:
        self._cmap = cmap
        self._glyf = glyf

    def getBestCmap(self) -> dict[int, str]:
        return self._cmap

    def get(self, key: str) -> Any:
        return self._glyf if key == "glyf" else None


def _service_with_font(cmap: dict[int, str], glyf: FakeGlyf | None = None) -> FontService:
    service = FontService()
    service._gen = cast(ThaiPuaFontGenerator, SimpleNamespace(font=_FakeFont(cmap, glyf)))
    return service


def test_pua_slot_context_is_none_without_a_font() -> None:
    assert FontService().pua_slot_context() is None


def test_pua_slot_context_snapshots_cmap_and_glyf() -> None:
    cmap = {0xE000: "logo", 0x0E01: "ko_kai"}
    glyf = make_glyf(logo=False, ko_kai=False)
    context = _service_with_font(cmap, glyf).pua_slot_context()
    assert context is not None
    assert context.cmap == cmap
    assert context.glyf is glyf


def test_occupied_pua_chars_scans_the_font_cmap() -> None:
    cmap = {0xE000: "a", 0xE001: "b", 0x0E01: "ko_kai"}
    assert _service_with_font(cmap)._occupied_pua_chars() == {chr(0xE000), chr(0xE001)}


def test_component_boxes_are_empty_without_a_glyf_table() -> None:
    """CFF/OTF fonts carry no component structure; a mapped PUA slot still renders."""
    spec = CompositeSpec(pua_code=0xE000, cons_uni=0x0E01)
    service = _service_with_font({0xE000: "foreign_glyph"}, glyf=None)
    assert service._component_boxes("foreign_glyph", spec) == []


def test_ensure_pua_map_bootstraps_an_empty_map_and_never_touches_existing(
    tmp_path: Path,
) -> None:
    """An existing mapping file is loaded as-is — the user owns the static map."""
    service = FontService()
    map_path = tmp_path / "pua.json"
    service.set_pua_map_path(str(map_path))
    existing = {"ก่": chr(0xF100)}
    from thaipua.core.pua_map import save_pua_map

    save_pua_map(existing, str(map_path))

    loaded = service.ensure_pua_map()

    assert loaded == existing
    assert service.pua_map == existing
