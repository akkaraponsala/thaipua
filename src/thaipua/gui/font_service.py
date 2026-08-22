"""Backend facade owning the live font generator; the sole bridge between GUI and `fontTools`."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont

from thaipua.core.constants import DEFAULT_PROFILES_DIR, DEFAULT_PUA_MAP_PATH, PUA_RANGE_END, PUA_RANGE_START
from thaipua.core.encoding import load_pua_map_dict
from thaipua.core.fonttools.alternates import GlyphSubstitution, find_glyph_substitutions
from thaipua.core.fonttools.bounding_box import BoundingBox
from thaipua.core.fonttools.composer import (
    ComponentPlacement,
    InstallResult,
    InstallStatus,
    ThaiPuaFontGenerator,
)
from thaipua.core.fonttools.map_validation import PuaSlotContext, slot_context_from_font
from thaipua.core.fonttools.settings import (
    SUB_ABOVE_VOWEL,
    SUB_BELOW_VOWEL,
    SUB_CONSONANT,
    SUB_TONE_MARK,
    PlacementSettings,
    save_placement_settings,
)
from thaipua.core.fonttools.specs import CompositeSpec, iter_composite_specs
from thaipua.core.profiles import resolve_settings_profile
from thaipua.core.pua_map import THAI_SUFFIXES
from thaipua.gui.glyph_pen import PathLike, render_glyph_path, render_placed_components

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ComponentBox:
    """Per-component outline box for preview overlays."""

    role: str
    glyph_name: str
    bbox: tuple[int, int, int, int]


@dataclass(slots=True)
class GlyphRender:
    """Metrics and metadata for drawing one glyph on the preview canvas."""

    codepoint: int
    glyph_name: str | None
    units_per_em: int
    advance_width: int
    bbox: tuple[int, int, int, int] | None
    ascender: int
    descender: int
    cap_height: int
    x_height: int
    component_boxes: list[ComponentBox] = field(default_factory=list)


class FontService:
    """Own the live generator and expose font operations to the GUI."""

    def __init__(self) -> None:
        """Initialize an empty service with no loaded font."""
        self._src_path: Path | None = None
        self._output_path: str | None = None
        self._profiles_dir = DEFAULT_PROFILES_DIR
        self._gen: ThaiPuaFontGenerator | None = None
        self._pua_map_path = DEFAULT_PUA_MAP_PATH
        self._pua_map: dict[str, str] = {}

    @property
    def is_loaded(self) -> bool:
        """Return `True` once a source font has been loaded via `load_font`."""
        return self._gen is not None

    @property
    def generator(self) -> ThaiPuaFontGenerator | None:
        """Return the live `ThaiPuaFontGenerator`, or `None` before a load."""
        return self._gen

    @property
    def font(self) -> TTFont | None:
        """Return the live `TTFont`, or `None` before a load."""
        return self._gen.font if self._gen is not None else None

    @property
    def font_path(self) -> Path | None:
        """Return the loaded font's path, or `None` before a load."""
        return self._src_path

    @property
    def output_path(self) -> str | None:
        """Return the default output path, set when a font is loaded."""
        return self._output_path

    @property
    def pua_map(self) -> dict[str, str]:
        """Return the in-memory Thai-to-PUA map; empty until `load_pua_map`."""
        return self._pua_map

    @property
    def pua_map_path(self) -> str:
        """Return the path to the on-disk PUA map mutated by `ensure_pua_map`."""
        return self._pua_map_path

    def set_pua_map_path(self, path: str) -> None:
        """Change the on-disk PUA map path consulted by `load_pua_map`/`ensure_pua_map`/`save_pua_map`."""
        self._pua_map_path = path

    def load_font(
        self, path: str | Path, settings: PlacementSettings | None = None, profiles_dir: str | Path | None = None
    ) -> None:
        """Open a font for editing, resolving its placement profile when settings are omitted."""
        src = Path(path)
        self._profiles_dir = str(profiles_dir) if profiles_dir is not None else DEFAULT_PROFILES_DIR
        if settings is None:
            resolved = resolve_settings_profile(src, profiles_dir=profiles_dir)
            settings = resolved.settings
        self._gen = ThaiPuaFontGenerator(str(src), settings)
        self._src_path = src
        self._output_path = self._default_output_path(src, ttf_suffix=self._gen.source_is_cff)
        logger.info("Loaded font %s (output target %s)", src, self._output_path)

    @staticmethod
    def _default_output_path(src: Path, *, ttf_suffix: bool = False) -> str:
        """Return the Save-Font default `<stem>_pua.<ext>` beside the source.

        A CFF source is converted to a TrueType working copy at load time, so its
        saved output always carries the `.ttf` extension.
        """
        suffix = ".ttf" if ttf_suffix else src.suffix
        return str(src.with_name(f"{src.stem}_pua{suffix}"))

    def load_pua_map(self, path: str | Path | None = None) -> dict[str, str]:
        """Read the Thai-to-PUA map from `path` (defaults to the stored path)."""
        target = str(path) if path is not None else self._pua_map_path
        self._pua_map_path = target
        self._pua_map = load_pua_map_dict(target)
        return self._pua_map

    def ensure_pua_map(self) -> dict[str, str]:
        """Load the PUA map, allocating a full mapping only when the file is empty.

        Pre-existing mappings are returned untouched; collisions surface through
        validation and skipped installs instead.
        """
        mapping = self.load_pua_map()
        if not mapping:
            logger.info("PUA map empty at %s; allocating full mapping", self._pua_map_path)
            mapping = self.allocate_pua_map()
        return mapping

    def save_pua_map(self, mapping: dict[str, str]) -> None:
        """Persist `mapping` back to the stored PUA-map path as UTF-8 JSON."""
        from thaipua.core.pua_map import save_pua_map

        save_pua_map(mapping, self._pua_map_path)

    def allocate_pua_map(self) -> dict[str, str]:
        """Allocate a complete mapping, reserving codepoints already mapped in the live font."""
        from thaipua.core.pua_map import ensure_pua_map

        ensure_pua_map(
            THAI_SUFFIXES,
            path=self._pua_map_path,
            start_pua=PUA_RANGE_START,
            reserved_pua_chars=self._occupied_pua_chars(),
        )
        return self.load_pua_map()

    def _occupied_pua_chars(self) -> set[str]:
        """Return PUA characters mapped in the live font's `cmap`.

        Returns an empty set when no font is loaded.
        """
        if self._gen is None or self._gen.font is None:
            return set()
        return {chr(cp) for cp in self._gen.font.getBestCmap() if PUA_RANGE_START <= cp <= PUA_RANGE_END}

    def pua_slot_context(self) -> PuaSlotContext | None:
        """Snapshot the font's slot facts for mapping validation, or `None` without a font."""
        if self._gen is None or self._gen.font is None:
            return None
        return slot_context_from_font(self._gen.font)

    def glyph_name_for(self, codepoint: int) -> str | None:
        """Return the font's glyph name for `codepoint`, or `None` when unmapped."""
        if self._gen is None:
            return None
        return self._gen._cmap.get(codepoint)

    def has_codepoint(self, codepoint: int) -> bool:
        """Return `True` when `codepoint` has an installed glyph in the font."""
        return self.glyph_name_for(codepoint) is not None

    def advance_width_for(self, glyph_name: str) -> int:
        """Return the typed advance width of `glyph_name` in font units."""
        if self._gen is None or self._gen.font is None:
            return 0
        width, _lsb = self._gen.font["hmtx"][glyph_name]
        return int(width)

    def display_extents(self) -> tuple[float, float]:
        """Return the font's (ascent, descent) line box in font units for uniform glyph scaling.

        Prefers typo metrics with hhea fallback so glyphs stay optically large;
        mark stacks exceeding the box are clamped per cell at paint time.
        Returns (0, 0) without a font.
        """
        if self._gen is None or self._gen.font is None:
            return (0.0, 0.0)
        font = self._gen.font
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

    def render_glyph(self, codepoint: int, path: PathLike, spec: CompositeSpec | None = None) -> GlyphRender:
        """Draw a codepoint's installed glyph into `path` and return its metrics.

        When `spec` is provided, the result carries per-component bounding boxes.
        """
        if self._gen is None or self._gen.font is None:
            return GlyphRender(
                codepoint=codepoint,
                glyph_name=None,
                units_per_em=0,
                advance_width=0,
                bbox=None,
                ascender=0,
                descender=0,
                cap_height=0,
                x_height=0,
            )
        font = self._gen.font
        glyph_name = self._gen._cmap.get(codepoint)
        upem = _units_per_em(font)
        asc, desc, cap, xh = _font_metrics(font, upem)
        if glyph_name is None:
            return GlyphRender(
                codepoint=codepoint,
                glyph_name=None,
                units_per_em=upem,
                advance_width=0,
                bbox=None,
                ascender=asc,
                descender=desc,
                cap_height=cap,
                x_height=xh,
            )
        render_glyph_path(font, glyph_name, path)
        advance = self.advance_width_for(glyph_name)
        bbox = self._gen.bbox.get_bounding_box(glyph_name)
        bbox_tuple = bbox.as_tuple() if bbox is not None else None
        return GlyphRender(
            codepoint=codepoint,
            glyph_name=glyph_name,
            units_per_em=upem,
            advance_width=advance,
            bbox=bbox_tuple,
            ascender=asc,
            descender=desc,
            cap_height=cap,
            x_height=xh,
            component_boxes=self._component_boxes(glyph_name, spec),
        )

    def _component_boxes(self, glyph_name: str, spec: CompositeSpec | None) -> list[ComponentBox]:
        """Compute per-component boxes for an installed composite, ordered consonant first.

        Returns an empty list for non-composite glyphs or fonts without `glyf`.
        """
        if spec is None or self._gen is None or self._gen.font is None:
            return []
        glyf = self._gen.font.get("glyf")
        if glyf is None:
            return []
        if glyph_name not in glyf:
            return []
        glyph = glyf[glyph_name]
        components = getattr(glyph, "components", None)
        if not components:
            return []
        roles = [SUB_CONSONANT]
        if spec.below_uni:
            roles.append(SUB_BELOW_VOWEL)
        if spec.above_uni:
            roles.append(SUB_ABOVE_VOWEL)
        if spec.tone_uni:
            roles.append(SUB_TONE_MARK)
        boxes = []
        for index, component in enumerate(components):
            base = self._gen.bbox.get_bounding_box(component.glyphName)
            if base is None:
                continue
            _name, (xx, xy, yx, yy, dx, dy) = component.getComponentInfo()
            role = roles[index] if index < len(roles) else roles[-1]
            boxes.append(
                ComponentBox(
                    role=role,
                    glyph_name=component.glyphName,
                    bbox=self._transform_bbox(base, (xx, xy, yx, yy, dx, dy)),
                )
            )
        return boxes

    @staticmethod
    def _transform_bbox(
        base: BoundingBox, transform: tuple[float, float, float, float, float, float]
    ) -> tuple[int, int, int, int]:
        """Return `base`'s bounding box after applying the 6-tuple affine `transform`."""
        xx, xy, yx, yy, dx, dy = transform
        corners = (
            (base.x_min, base.y_min),
            (base.x_min, base.y_max),
            (base.x_max, base.y_min),
            (base.x_max, base.y_max),
        )
        x_values = [xx * cx + yx * cy + dx for cx, cy in corners]
        y_values = [xy * cx + yy * cy + dy for cx, cy in corners]
        return (round(min(x_values)), round(min(y_values)), round(max(x_values)), round(max(y_values)))

    def _placed_component_boxes(
        self, placements: Sequence[ComponentPlacement], spec: CompositeSpec
    ) -> list[ComponentBox]:
        """Compute per-component boxes from placements without requiring installation."""
        if self._gen is None:
            return []
        roles = [SUB_CONSONANT]
        if spec.below_uni:
            roles.append(SUB_BELOW_VOWEL)
        if spec.above_uni:
            roles.append(SUB_ABOVE_VOWEL)
        if spec.tone_uni:
            roles.append(SUB_TONE_MARK)
        boxes = []
        for index, placement in enumerate(placements):
            base = self._gen.bbox.get_bounding_box(placement.glyph_name)
            if base is None:
                continue
            role = roles[index] if index < len(roles) else roles[-1]
            boxes.append(
                ComponentBox(
                    role=role,
                    glyph_name=placement.glyph_name,
                    bbox=self._transform_bbox(base, placement.transform),
                )
            )
        return boxes

    def render_composite_path(
        self, spec: CompositeSpec, settings: PlacementSettings, path: PathLike
    ) -> GlyphRender | None:
        """Preview a composed spec into `path` without modifying the font.

        Return `None` when the consonant glyph is missing from the font.
        """
        if self._gen is None or self._gen.font is None:
            return None
        placements = self._gen.compose_components(
            spec.cons_uni,
            spec.below_uni,
            spec.above_uni,
            spec.tone_uni,
            settings=settings,
            pua_code=spec.pua_code,
        )
        if placements is None:
            return None
        font = self._gen.font
        upem = _units_per_em(font)
        asc, desc, cap, xh = _font_metrics(font, upem)
        render_placed_components(font, [(c.glyph_name, c.transform) for c in placements], path)
        boxes = self._placed_component_boxes(placements, spec)
        bbox = (
            (
                min(b.bbox[0] for b in boxes),
                min(b.bbox[1] for b in boxes),
                max(b.bbox[2] for b in boxes),
                max(b.bbox[3] for b in boxes),
            )
            if boxes
            else None
        )
        return GlyphRender(
            codepoint=spec.pua_code,
            glyph_name=f"uni{spec.pua_code:04X}",
            units_per_em=upem,
            advance_width=self.advance_width_for(placements[0].glyph_name),
            bbox=bbox,
            ascender=asc,
            descender=desc,
            cap_height=cap,
            x_height=xh,
            component_boxes=boxes,
        )

    def regenerate_composite(
        self, spec: CompositeSpec, settings: PlacementSettings, path: PathLike | None
    ) -> GlyphRender:
        """Rebuild the composite at its PUA codepoint and render the current occupant."""
        if self._gen is None:
            raise RuntimeError("Cannot regenerate composites without a loaded font.")
        result = self._gen.install_composite(
            spec.pua_code,
            spec.cons_uni,
            spec.below_uni,
            spec.above_uni,
            spec.tone_uni,
            settings=settings,
        )
        logger.debug("Regenerated U+%04X: %s", spec.pua_code, result.status.value)
        if path is None:
            return self.render_glyph(spec.pua_code, _NullPath(), spec=spec)
        return self.render_glyph(spec.pua_code, path, spec=spec)

    def regenerate_all(self, settings: PlacementSettings, pua_map: dict[str, str]) -> list[InstallResult]:
        """Rebuild every composite in the map, returning one result per spec."""
        if self._gen is None:
            raise RuntimeError("Cannot regenerate composites without a loaded font.")
        return [
            self._gen.install_composite(
                spec.pua_code,
                spec.cons_uni,
                spec.below_uni,
                spec.above_uni,
                spec.tone_uni,
                settings=settings,
            )
            for spec in iter_composite_specs(pua_map)
        ]

    def save_font(self, output_path: str | Path | None, settings: PlacementSettings, pua_map: dict[str, str]) -> str:
        """Rebuild all composites, write the font to `output_path`, and persist the settings profile."""
        if self._gen is None:
            raise RuntimeError("Cannot save: no font loaded.")
        target = str(output_path) if output_path is not None else self._output_path
        if target is None:
            raise RuntimeError("Cannot save: no output path available.")
        results = self.regenerate_all(settings, pua_map)
        locked = sum(1 for result in results if result.status is InstallStatus.SKIPPED_LOCKED)
        if locked:
            logger.warning("Saved font keeps %d locked PUA slot(s) untouched (unrecognized content)", locked)
        self._gen.font.save(target)
        self._output_path = target
        self._persist_profile(settings)
        logger.info("Saved generated font to %s", target)
        return target

    def _persist_profile(self, settings: PlacementSettings) -> Path | None:
        """Save `settings` to the stem-tier profile so edits survive a reload.

        Family- and default-tier profiles are left untouched.
        """
        if self._src_path is None:
            return None
        profile_path = Path(self._profiles_dir) / f"{self._src_path.stem}.json"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        save_placement_settings(settings, profile_path)
        return profile_path

    def find_substitutions(self) -> dict[str, list[GlyphSubstitution]]:
        """Return the per-category GSUB substitution catalog for the live font."""
        if self._gen is None or self._gen.font is None:
            return {}
        return find_glyph_substitutions(self._gen.font)

    def close(self) -> None:
        """Close the underlying `TTFont` if one is open; safe to call repeatedly."""
        if self._gen is not None and self._gen.font is not None:
            try:
                self._gen.font.close()
            except Exception:
                logger.debug("Ignoring font close failure", exc_info=True)
        self._gen = None
        self._src_path = None
        self._output_path = None
        self._profiles_dir = DEFAULT_PROFILES_DIR


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


class _NullPath:
    """No-op path sink for regeneration without rendering."""

    def moveTo(self, x: float, y: float) -> None:
        return

    def lineTo(self, x: float, y: float) -> None:
        return

    def quadTo(self, x1: float, y1: float, x2: float, y2: float) -> None:
        return

    def cubicTo(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> None:
        return

    def closeSubpath(self) -> None:
        return


__all__ = ["ComponentBox", "FontService", "GlyphRender"]
