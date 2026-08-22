"""Shared fixtures and duck-typed fakes for the test suite."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from thaipua.core.fonttools.composer import ThaiPuaFontGenerator

SAMPLE_FONT_PATH = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "Sarabun-Regular.ttf"


class FakeGlyph:
    """Minimal stand-in for a `glyf` glyph exposing only `isComposite`."""

    def __init__(self, composite: bool) -> None:
        self._composite = composite

    def isComposite(self) -> bool:
        return self._composite


class FakeGlyf:
    """Dict-like stand-in for a `glyf` table keyed by glyph name."""

    def __init__(self, glyphs: dict[str, FakeGlyph]) -> None:
        self._glyphs = glyphs

    def __contains__(self, name: str) -> bool:
        return name in self._glyphs

    def __getitem__(self, name: str) -> FakeGlyph:
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
