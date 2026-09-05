"""Shared fixtures and duck-typed fakes for the test suite."""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thaipua.core.font.composer import ThaiPuaFontGenerator

SAMPLE_FONT_PATH = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "Sarabun-Regular.ttf"


class FakeGlyph:
    """Minimal stand-in for a `glyf` glyph exposing only `isComposite`."""

    def __init__(self, composite: bool, contours: int | None = None) -> None:
        self._composite = composite
        self.numberOfContours = contours

    def isComposite(self) -> bool:
        return self._composite


class FakeCompositeGlyph:
    """Composite glyph stand-in exposing its component names."""

    def __init__(self, component_names: list[str]) -> None:
        self.components = [SimpleNamespace(glyphName=name) for name in component_names]

    def isComposite(self) -> bool:
        return True


class FakeGlyf:
    """Dict-like stand-in for a `glyf` table keyed by glyph name."""

    def __init__(self, glyphs: dict[str, Any]) -> None:
        self._glyphs = glyphs

    def __contains__(self, name: str) -> bool:
        return name in self._glyphs

    def __getitem__(self, name: str) -> Any:
        return self._glyphs[name]


def make_glyf(**glyphs: bool) -> FakeGlyf:
    """Build a `FakeGlyf` mapping each glyph name to its composite flag."""
    return FakeGlyf({name: FakeGlyph(composite) for name, composite in glyphs.items()})


@pytest.fixture
def generator() -> Iterator[ThaiPuaFontGenerator]:
    """Yield a generator over the sample font, skipping when the asset is missing."""
    if not SAMPLE_FONT_PATH.exists():
        pytest.skip(f"sample font missing: {SAMPLE_FONT_PATH}")
    gen = ThaiPuaFontGenerator(str(SAMPLE_FONT_PATH), None)
    yield gen
    gen.font.close()
