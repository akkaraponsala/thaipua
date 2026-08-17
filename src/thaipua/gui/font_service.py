"""Backend facade for the ThaiPUA desktop GUI.

`FontService` owns the live `ThaiPuaFontGenerator` and isolates every fontTools call:
panes ask for opaque `(codepoint, glyph name, metrics)` results and never touch `TTFont`
directly. The service is PySide6-free so its composite-regeneration and rendering logic
stays unit-testable with a lightweight path-like sink (see
`thaipua.gui.glyph_pen.PathLike`).

The preview/rebuild flow evicts and re-creates a composite at the same PUA codepoint
every time offset sliders move, so the canvas reflects whatever `PlacementSettings` the
main window currently holds — including snapping — without ever committing to disk until
*Save Font* is invoked.
"""

from __future__ import annotations

import contextlib
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
from thaipua.core.fonttools.composer import ComponentPlacement, ThaiPuaFontGenerator
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
from thaipua.core.pua_allocator import THAI_SUFFIXES
from thaipua.gui.glyph_pen import PathLike, render_glyph_path, render_placed_components

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ComponentBox:
    """Bounding box of a single composite component for the *Glyph Preview*.

    The canvas draws one colored box per component so each part (consonant / below vowel
    / above vowel / tone mark) is outlined independently. The `glyph_name` may differ
    from the codepoint's cmap glyph under a substitution.
    """

    role: str
    glyph_name: str
    bbox: tuple[int, int, int, int]


@dataclass(slots=True)
class GlyphRender:
    """Metrics the preview canvas needs to lay out a single glyph.

    `glyph_name` is `None` when the codepoint is unmapped (canvas draws nothing); `bbox`
    is `None` when the glyph has no drawable contour; `component_boxes` is empty for
    simple glyphs and unmapped codepoints.
    """

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
    """Backend glue: owns the live generator and the font's mutable state.

    The service keeps the source path so it can also rebuild the generator (or persist
    it) when settings change, and exposes the composer's placement-resolution surface
    through GUI-friendly method names.
    """

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
        """Return the path to the on-disk PUA map mutated by `extend_pua_mapping`."""
        return self._pua_map_path

    def set_pua_map_path(self, path: str) -> None:
        """Change the on-disk PUA map path consulted by `load`/`extend`/`save`."""
        self._pua_map_path = path

    def load_font(
        self, path: str | Path, settings: PlacementSettings | None = None, profiles_dir: str | Path | None = None
    ) -> None:
        """Open the font at `path` for composite editing.

        When `settings` is `None`, a profile is resolved via `resolve_settings_profile`
        against `profiles_dir` (default `"profiles"`).
        """
        src = Path(path)
        self._profiles_dir = str(profiles_dir) if profiles_dir is not None else DEFAULT_PROFILES_DIR
        if settings is None:
            resolved = resolve_settings_profile(src, profiles_dir=profiles_dir)
            settings = resolved.settings
        out_path = self._default_output_path(src)
        self._gen = ThaiPuaFontGenerator(str(src), settings)
        self._src_path = src
        self._output_path = out_path
        logger.info("Loaded font %s (output target %s)", src, out_path)

    @staticmethod
    def _default_output_path(src: Path) -> str:
        """Return the Save-Font default `<stem>_pua.<ext>` beside the source."""
        return str(src.with_name(f"{src.stem}_pua{src.suffix}"))

    def load_pua_map(self, path: str | Path | None = None) -> dict[str, str]:
        """Read the Thai-to-PUA map from `path` (defaults to the stored path)."""
        target = str(path) if path is not None else self._pua_map_path
        self._pua_map_path = target
        self._pua_map = load_pua_map_dict(target)
        return self._pua_map

    def ensure_pua_map(self) -> dict[str, str]:
        """Load the Thai-to-PUA map from the stored path, returning it ready for use.

        Allocates a full mapping when the file is missing or empty. A pre-existing
        mapping whose entries collide with the loaded font's cmap is repaired and
        persisted.
        """
        mapping = self.load_pua_map()
        if not mapping:
            logger.info("PUA map empty at %s; allocating full mapping", self._pua_map_path)
            mapping = self.extend_pua_mapping()
        else:
            mapping = self._repair_pua_map(mapping)
        return mapping

    def save_pua_map(self, mapping: dict[str, str]) -> None:
        """Persist `mapping` back to the stored PUA-map path as UTF-8 JSON."""
        from thaipua.core.pua_allocator import save_pua_map

        save_pua_map(mapping, self._pua_map_path)

    def extend_pua_mapping(self) -> dict[str, str]:
        """Allocate PUA codepoints for every consonant/suffix combination.

        Codepoints mapped in the live font's cmap are reserved, so allocations never
        collide with the font. Returns the freshly reloaded map.
        """
        from thaipua.core.pua_allocator import extend_pua_mapping

        extend_pua_mapping(
            THAI_SUFFIXES,
            filename=self._pua_map_path,
            start_pua=PUA_RANGE_START,
            reserved_pua_chars=self._occupied_pua_chars(),
        )
        return self.load_pua_map()

    def _occupied_pua_chars(self) -> set[str]:
        """Return PUA characters mapped in the live font's cmap.

        Returns an empty set when no font is loaded.
        """
        if self._gen is None or self._gen.font is None:
            return set()
        return {chr(cp) for cp in self._gen.font.getBestCmap() if PUA_RANGE_START <= cp <= PUA_RANGE_END}

    def _foreign_pua_chars(self) -> set[str]:
        """Return PUA characters the loaded font maps to non-composite glyphs.

        Composite glyphs are excluded (presumed generated earlier by this tool) and
        only counted in a log line, so a third-party composite squatting on a PUA slot
        stays observable. Cmap entries whose glyph is absent from `glyf` still count
        as foreign: `create_composite`'s skip guard consults the cmap, not `glyf`.
        Returns an empty set when no font is loaded, and every occupied PUA character
        when the font has no `glyf` table.
        """
        if self._gen is None or self._gen.font is None:
            return set()
        font = self._gen.font
        glyf = font.get("glyf")
        if glyf is None:
            return self._occupied_pua_chars()
        occupied = set()
        owned_composites = 0
        for cp, glyph_name in font.getBestCmap().items():
            if not (PUA_RANGE_START <= cp <= PUA_RANGE_END):
                continue
            if glyph_name in glyf and glyf[glyph_name].isComposite():
                owned_composites += 1
                continue
            occupied.add(chr(cp))
        if owned_composites:
            logger.info(
                "Treating %d PUA codepoint(s) mapped to composite glyphs as owned by this tool", owned_composites
            )
        return occupied

    def _repair_pua_map(self, mapping: dict[str, str]) -> dict[str, str]:
        """Reallocate entries colliding with the live font's cmap and persist the result.

        Returns the repaired (possibly unchanged) map.
        """
        from thaipua.core.pua_allocator import reallocate_colliding_entries

        repaired = reallocate_colliding_entries(mapping, self._foreign_pua_chars())
        if repaired != mapping:
            moved = sum(1 for key, old in mapping.items() if repaired.get(key) != old)
            self.save_pua_map(repaired)
            self._pua_map = repaired
            logger.warning("PUA map repaired: reallocated %d entry(ies) in %s", moved, self._pua_map_path)
        return repaired

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

    def render_glyph(self, codepoint: int, path: PathLike, spec: CompositeSpec | None = None) -> GlyphRender:
        """Draw `codepoint`'s glyph into `path` and return its metrics.

        When `spec` is provided, per-component bounding boxes are populated on the
        returned `GlyphRender`; `None` (a plain cmap codepoint) yields none.
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
        """Compute each placed component's transformed bounding box.

        Reads the top-level component list of the installed composite at `glyph_name`
        and categorizes each entry by the composer's fixed add order — consonant first,
        then below/above/tone marks in their spec slot order — so roles stay correct
        even when a glyph substitution swapped in an alternate glyph name. `[]` is
        returned for non-composite glyphs, or when `spec` is `None` (a plain cmap
        codepoint).
        """
        if spec is None or self._gen is None or self._gen.font is None:
            return []
        glyf = self._gen.font["glyf"]
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
        """Compute each uninstalled placement's transformed bounding box and role.

        Mirrors `_component_boxes` for the pure `compose_components` placements, so a
        preview drawn without installing the composite still gets per-part boxes with
        the composer's fixed add order (consonant first, then marks in spec slot order).
        """
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
        """Draw `spec` composed under `settings` into `path` without mutating the font.

        Non-mutating: placements come from the generator's read-only
        `compose_components`, so the grid can preview live offsets/substitutions/snaps
        for any codepoint — installed or not — with no eviction, no `[SKIP-OWNED]`
        guard interaction, and no change to the installed-composite bookkeeping.
        Returns `None` when the consonant glyph is missing from the font (nothing
        drawn).
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
        """Rebuild `spec` at its PUA codepoint under `settings` and optionally draw it.

        The composite is evicted and re-installed so successive edits on the same
        codepoint reflect new offsets instead of being skipped by `create_composite`'s
        "owned PUA" guard.
        """
        if self._gen is None:
            raise RuntimeError("Cannot regenerate composites without a loaded font.")
        font = self._gen.font
        self._evict_composite(spec.pua_code, font)
        self._gen.settings = settings
        self._gen.create_composite(spec.pua_code, spec.cons_uni, spec.below_uni, spec.above_uni, spec.tone_uni)
        if path is None:
            return self.render_glyph(spec.pua_code, _NullPath(), spec=spec)
        return self.render_glyph(spec.pua_code, path, spec=spec)

    def regenerate_all(self, settings: PlacementSettings, pua_map: dict[str, str]) -> None:
        """Rebuild every composite in `pua_map` after applying `settings`."""
        if self._gen is None:
            raise RuntimeError("Cannot regenerate composites without a loaded font.")
        self._gen.settings = settings
        font = self._gen.font
        for spec in iter_composite_specs(pua_map):
            self._evict_composite(spec.pua_code, font)
            self._gen.create_composite(spec.pua_code, spec.cons_uni, spec.below_uni, spec.above_uni, spec.tone_uni)

    def save_font(self, output_path: str | Path | None, settings: PlacementSettings, pua_map: dict[str, str]) -> str:
        """Rebuild all composites and write the resulting font to `output_path`.

        After the font is written, `settings` are persisted to the stem-tier profile
        (`<profiles_dir>/<stem>.json`) so edits survive a reload. `output_path=None`
        falls back to the default `<stem>_pua.<ext>`; returns the path actually written
        to.
        """
        if self._gen is None:
            raise RuntimeError("Cannot save: no font loaded.")
        target = str(output_path) if output_path is not None else self._output_path
        if target is None:
            raise RuntimeError("Cannot save: no output path available.")
        self.regenerate_all(settings, pua_map)
        self._gen.font.save(target)
        self._output_path = target
        self._persist_profile(settings)
        logger.info("Saved generated font to %s", target)
        return target

    def _persist_profile(self, settings: PlacementSettings) -> Path | None:
        """Persist `settings` to the stem-tier profile so edits survive a reload.

        Writes to `<profiles_dir>/<stem>.json` (the highest-priority resolution tier),
        creating or overwriting it; hand-authored family/`default.json` profiles are
        left untouched. Returns the profile path, or `None` when no source font is
        loaded (nothing to derive a stem from).
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

    def _evict_composite(self, pua_code: int, font: TTFont) -> None:
        """Remove any glyph currently mapped to `pua_code` from the live font.

        Mutation surface:
        - drops the cmap entry from every Unicode subtable and the generator's private
          dict copy (its `[SKIP-OWNED]` guard consults that copy),
        - deletes the glyph from `glyf`/`hmtx` and prunes `glyphSet` order,
        - invalidates the bounding-box cache entry for the evicted name, since
          `create_composite` reinstalls the composite at the same name and a stale
          cached bbox would otherwise feed the preview's viewport fit.

        A no-op when `pua_code` is free.
        """
        if self._gen is None:
            return
        cmap_copy = self._gen._cmap
        existing = cmap_copy.pop(pua_code, None)
        if existing is None and not _glyph_present_in_cmap(font, pua_code):
            return
        if existing is None:
            existing = font.getBestCmap().get(pua_code)
        if existing is None:
            return
        self._gen.bbox.invalidate(existing)
        for table in font["cmap"].tables:
            if table.isUnicode():
                table.cmap.pop(pua_code, None)
        with contextlib.suppress(KeyError):
            del font["glyf"][existing]
        metrics = font["hmtx"].metrics
        metrics.pop(existing, None)
        order = list(font.getGlyphOrder())
        if existing in order:
            order.remove(existing)
            font.setGlyphOrder(order)
        self._gen._glyph_names.discard(existing)


def _glyph_present_in_cmap(font: TTFont, codepoint: int) -> bool:
    """Return `True` when any Unicode cmap subtable maps `codepoint`."""
    return any(table.isUnicode() and codepoint in table.cmap for table in font["cmap"].tables)


def _units_per_em(font: TTFont) -> int:
    """Return the font's `head.unitsPerEm` as an `int` (default 1000 on absence)."""
    head = font.get("head")
    if head is None:
        return 1000
    return int(getattr(head, "unitsPerEm", 1000))


def _font_metrics(font: TTFont, upem: int) -> tuple[int, int, int, int]:
    """Return `(ascender, descender, cap_height, x_height)` smart-from-OS/2.

    Falls back to typographic OS/2 fields, then `hhea`, then rational fractions of
    `upem` so canvas guides still draw on older fonts.
    """
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
    """No-op `PathLike` so `regenerate_composite` can run without rendering."""

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
