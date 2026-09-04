"""Preview and install rendering against a `FontWorkspace` without touching layout state."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from thaipua.core.domain.settings import (
    SUB_ABOVE_VOWEL,
    SUB_BELOW_VOWEL,
    SUB_CONSONANT,
    SUB_TONE_MARK,
    PlacementSettings,
)
from thaipua.core.font.bounding_box import BoundingBox
from thaipua.core.font.composer import ComponentPlacement, InstallResult, InstallStatus
from thaipua.core.font.specs import CompositeSpec, iter_composite_specs
from thaipua.core.font.workspace import FontWorkspace, _font_metrics, _units_per_em
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
    install_status: InstallStatus | None = None


class FontRenderer:
    """Draw previews and install composites into the workspace's live font."""

    def __init__(self, workspace: FontWorkspace) -> None:
        """Bind the renderer to `workspace` without taking font ownership."""
        self._workspace = workspace

    def render_glyph(self, codepoint: int, path: PathLike, spec: CompositeSpec | None = None) -> GlyphRender:
        """Draw a codepoint's installed glyph into `path` and return its metrics.

        When `spec` is provided, the result carries per-component bounding boxes.
        """
        gen = self._workspace.generator
        if gen is None or gen.font is None:
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
        font = gen.font
        glyph_name = gen.glyph_name_for(codepoint)
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
        advance = self._advance_width(glyph_name)
        bbox = gen.bounding_box(glyph_name)
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

    def _advance_width(self, glyph_name: str) -> int:
        """Return the typed advance width of `glyph_name` in font units, or 0 without a font."""
        font = self._workspace.font
        if font is None:
            return 0
        width, _lsb = font["hmtx"][glyph_name]
        return int(width)

    def _component_boxes(self, glyph_name: str, spec: CompositeSpec | None) -> list[ComponentBox]:
        """Compute per-component boxes for an installed composite, ordered consonant first.

        Return an empty list for non-composite glyphs or fonts without `glyf`.
        """
        gen = self._workspace.generator
        if spec is None or gen is None or gen.font is None:
            return []
        glyf = gen.font.get("glyf")
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
            base = gen.bounding_box(component.glyphName)
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
        gen = self._workspace.generator
        if gen is None:
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
            base = gen.bounding_box(placement.glyph_name)
            if base is None:
                continue
            role = roles[index] if index < len(roles) else roles[-1]
            dx, dy = placement.transform
            boxes.append(
                ComponentBox(
                    role=role,
                    glyph_name=placement.glyph_name,
                    bbox=(base.x_min + dx, base.y_min + dy, base.x_max + dx, base.y_max + dy),
                )
            )
        return boxes

    def render_composite_path(
        self, spec: CompositeSpec, settings: PlacementSettings, path: PathLike
    ) -> GlyphRender | None:
        """Preview a composed spec into `path` without modifying the font.

        Return `None` when the consonant glyph is missing from the font.
        """
        gen = self._workspace.generator
        if gen is None or gen.font is None:
            return None
        placements = gen.compose_components(
            spec.cons_uni,
            spec.below_uni,
            spec.above_uni,
            spec.tone_uni,
            settings=settings,
            pua_code=spec.pua_code,
        )
        if placements is None:
            return None
        font = gen.font
        upem = _units_per_em(font)
        asc, desc, cap, xh = _font_metrics(font, upem)
        render_placed_components(font, [(c.glyph_name, (1, 0, 0, 1, *c.transform)) for c in placements], path)
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
            advance_width=self._advance_width(placements[0].glyph_name),
            bbox=bbox,
            ascender=asc,
            descender=desc,
            cap_height=cap,
            x_height=xh,
            component_boxes=boxes,
        )

    def regenerate_composite(
        self,
        spec: CompositeSpec,
        settings: PlacementSettings,
        path: PathLike | None,
        *,
        allowed_locked: frozenset[int] | None,
    ) -> GlyphRender:
        """Rebuild the composite at its PUA codepoint and render the current occupant.

        The returned render carries `install_status` so callers can distinguish a
        real install from a skip that left the slot untouched.
        """
        gen = self._workspace.generator
        if gen is None:
            raise RuntimeError("Cannot regenerate composites without a loaded font.")
        result = gen.install_composite(
            spec.pua_code,
            spec.cons_uni,
            spec.below_uni,
            spec.above_uni,
            spec.tone_uni,
            settings=settings,
            allowed_locked=allowed_locked,
        )
        logger.debug("Regenerated U+%04X: %s", spec.pua_code, result.status.value)
        render = self.render_glyph(spec.pua_code, path if path is not None else _NullPath(), spec=spec)
        render.install_status = result.status
        return render

    def regenerate_all(
        self,
        settings: PlacementSettings,
        pua_map: dict[str, str],
        allowed_locked: frozenset[int] | None,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[InstallResult]:
        """Rebuild every composite in the map, returning one result per spec.

        `progress(done, total)` is invoked after each install so a GUI can update
        a progress indicator during a full rebuild.
        """
        gen = self._workspace.generator
        if gen is None:
            raise RuntimeError("Cannot regenerate composites without a loaded font.")
        specs = list(iter_composite_specs(pua_map))
        total = len(specs)
        results: list[InstallResult] = []
        for index, spec in enumerate(specs):
            results.append(
                gen.install_composite(
                    spec.pua_code,
                    spec.cons_uni,
                    spec.below_uni,
                    spec.above_uni,
                    spec.tone_uni,
                    settings=settings,
                    allowed_locked=allowed_locked,
                )
            )
            if progress is not None:
                progress(index + 1, total)
        return results


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
