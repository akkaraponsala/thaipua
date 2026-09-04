"""Own the live font: lifecycle, output paths, and raw font access."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thaipua.core.domain.settings import PlacementSettings, default_placement_settings
from thaipua.core.font.composer import ThaiPuaFontGenerator
from thaipua.core.paths import RuntimeRoot, default_runtime_root

if TYPE_CHECKING:
    from fontTools.ttLib import TTFont

logger = logging.getLogger(__name__)


class FontWorkspace:
    """Hold the loaded `TTFont` and answer raw font queries; layout state lives elsewhere."""

    def __init__(self, root: RuntimeRoot | None = None) -> None:
        """Initialize an empty workspace rooted at `root` or the default."""
        self._root = root if root is not None else default_runtime_root()
        self.gen: ThaiPuaFontGenerator | None = None
        """Live generator; `None` before a load."""
        self._src_path: Path | None = None
        self._output_path: str | None = None

    @property
    def root(self) -> RuntimeRoot:
        """Return the injectable filesystem root this workspace resolves data paths from."""
        return self._root

    @property
    def is_loaded(self) -> bool:
        """Return `True` once a source font has been loaded via `load_font`."""
        return self.gen is not None

    @property
    def generator(self) -> ThaiPuaFontGenerator | None:
        """Return the live `ThaiPuaFontGenerator`, or `None` before a load."""
        return self.gen

    @property
    def font(self) -> TTFont | None:
        """Return the live `TTFont`, or `None` before a load."""
        return self.gen.font if self.gen is not None else None

    @property
    def font_path(self) -> Path | None:
        """Return the loaded font's path, or `None` before a load."""
        return self._src_path

    @property
    def output_path(self) -> str | None:
        """Return the default output path, set when a font is loaded."""
        return self._output_path

    @output_path.setter
    def output_path(self, value: str | None) -> None:
        self._output_path = value

    def load_font(self, path: str | Path, settings: PlacementSettings | None = None) -> None:
        """Open a font for editing with `settings`, closing any previously loaded font first."""
        self.close()
        src = Path(path)
        self.gen = ThaiPuaFontGenerator(str(src), settings if settings is not None else default_placement_settings())
        self._src_path = src
        self._output_path = self._default_output_path(src, ttf_suffix=self.gen.source_is_cff)
        logger.info("Loaded font %s (output target %s)", src, self._output_path)

    @staticmethod
    def _default_output_path(src: Path, *, ttf_suffix: bool = False) -> str:
        """Return the Save-Font default `<stem>_pua.<ext>` beside the source.

        A CFF source is converted to a TrueType working copy at load time, so its
        saved output always carries the `.ttf` extension.
        """
        suffix = ".ttf" if ttf_suffix else src.suffix
        return str(src.with_name(f"{src.stem}_pua{suffix}"))

    def close(self) -> None:
        """Close the underlying `TTFont` if one is open; safe to call repeatedly."""
        if self.gen is not None and self.gen.font is not None:
            try:
                self.gen.font.close()
            except Exception:
                logger.debug("Ignoring font close failure", exc_info=True)
        self.gen = None
        self._src_path = None
        self._output_path = None

    def display_extents(self) -> tuple[float, float]:
        """Return the font's (ascent, descent) line box in font units for uniform glyph scaling.

        Prefers typo metrics with hhea fallback so glyphs stay optically large;
        mark stacks exceeding the box are clamped per cell at paint time.
        Return (0, 0) without a font.
        """
        if self.gen is None or self.gen.font is None:
            return (0.0, 0.0)
        font = self.gen.font
        upem = _units_per_em(font)
        os2 = font.get("OS/2")
        hhea = font.get("hhea")
        ascent = max(
            abs(_coerce_int_field(os2, "sTypoAscender")),
            abs(_coerce_int_field(hhea, "ascent")),
            upem * 4 // 5,
        )
        descent = max(
            abs(_coerce_int_field(os2, "sTypoDescender")),
            abs(_coerce_int_field(hhea, "descent")),
            upem // 5,
        )
        return (float(ascent), float(descent))


def _units_per_em(font: TTFont) -> int:
    """Return the font's `head.unitsPerEm` as an `int` (default 1000 on absence)."""
    head = font.get("head")
    if head is None:
        return 1000
    return int(getattr(head, "unitsPerEm", 1000))


def _font_metrics(font: TTFont, upem: int) -> tuple[int, int, int, int]:
    """Collect canvas guide metrics, substituting rational defaults for missing fields."""
    os2 = font.get("OS/2")
    hhea = font.get("hhea")
    ascender = _coerce_int_field(os2, "sTypoAscender")
    descender = _coerce_int_field(os2, "sTypoDescender")
    if ascender == 0 and hhea is not None:
        ascender = int(hhea.ascent)
    if descender == 0 and hhea is not None:
        descender = -int(hhea.descent)
    if ascender == 0:
        ascender = upem * 4 // 5
    if descender == 0:
        descender = -upem // 5
    cap_height = _coerce_int_field(os2, "sCapHeight")
    x_height = _coerce_int_field(os2, "sxHeight")
    if cap_height == 0:
        cap_height = upem * 7 // 10
    if x_height == 0:
        x_height = upem // 2
    return (ascender, descender, cap_height, x_height)


def _coerce_int_field(table: Any | None, attr: str) -> int:
    """Coerce an optional `fontTools` table field to `int`, returning `0` if unset."""
    if table is None:
        return 0
    value = getattr(table, attr, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
