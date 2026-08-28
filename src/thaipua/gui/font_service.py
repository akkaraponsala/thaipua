"""Backend facade owning the live font generator; the sole bridge between GUI and `fontTools`."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont

from thaipua.core.constants import PUA_RANGE_START
from thaipua.core.fonttools.alternates import GlyphSubstitution, find_glyph_substitutions
from thaipua.core.fonttools.bounding_box import BoundingBox
from thaipua.core.fonttools.composer import (
    ComponentPlacement,
    InstallResult,
    InstallStatus,
    ThaiPuaFontGenerator,
)
from thaipua.core.fonttools.map_validation import (
    PuaMapIssue,
    PuaSlotContext,
    slot_context_from_font,
    validate_pua_map,
)
from thaipua.core.fonttools.occupancy import PuaOccupant, scan_pua_occupants
from thaipua.core.fonttools.settings import (
    SUB_ABOVE_VOWEL,
    SUB_BELOW_VOWEL,
    SUB_CONSONANT,
    SUB_TONE_MARK,
    PlacementSettings,
    default_placement_settings,
    load_placement_settings,
    save_placement_settings,
)
from thaipua.core.fonttools.specs import CompositeSpec, iter_composite_specs
from thaipua.core.layout import (
    DEFAULT_BASE_CODEPOINT,
    LayoutConflict,
    LayoutState,
    canonical_codepoint,
    canonical_tail_start,
    find_conflicts,
    find_relocation_target,
    is_valid_base,
    load_layout_state,
    max_base_codepoint,
    save_layout_state,
)
from thaipua.core.paths import (
    DEFAULT_LAYOUT_PATH,
    DEFAULT_PROFILES_DIR,
    DEFAULT_PUA_MAP_PATH,
)
from thaipua.core.pua_map import load_pua_map_dict, save_pua_map
from thaipua.gui.glyph_pen import PathLike, render_glyph_path, render_placed_components

logger = logging.getLogger(__name__)

_OCCUPANCY_VISIBLE_STATUSES: frozenset[InstallStatus] = frozenset(
    {
        InstallStatus.INSTALLED,
        InstallStatus.REPLACED_FOREIGN_COMPOSITE,
        InstallStatus.OVERRIDDEN_LOCKED,
    }
)
"""Install outcomes that change what occupies a PUA slot, invalidating occupancy caches."""


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
        self._layout_path = DEFAULT_LAYOUT_PATH
        self._layout: LayoutState | None = None
        self._state_version = 0

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
        """Return the path to the on-disk PUA map cache."""
        return self._pua_map_path

    @property
    def state_version(self) -> int:
        """Return a counter bumped on every layout or font-occupancy mutation."""
        return self._state_version

    def set_pua_map_path(self, path: str) -> None:
        """Change the on-disk PUA map cache path used by `load_pua_map`/`save_pua_map`."""
        self._pua_map_path = path

    def allowed_locked(self) -> frozenset[int]:
        """Return the PUA codepoints whose locked slots the user approved for overwrite."""
        return self._layout.overrides if self._layout is not None else frozenset()

    def override_slot(self, codepoint: int) -> None:
        """Approve overwriting the locked slot at `codepoint` and persist it with the layout.

        No-op with a warning before a layout is loaded — approvals are part of layout state.
        """
        if self._layout is None:
            logger.warning("Ignoring override for U+%04X: no layout loaded", codepoint)
            return
        self.override_slots([codepoint])

    def override_slots(self, codepoints: Iterable[int]) -> int:
        """Approve overwriting several locked slots with a single layout persist.

        Return the number of newly approved slots; no-op when nothing is new
        or no layout is loaded.
        """
        if self._layout is None:
            logger.warning("Ignoring bulk override: no layout loaded")
            return 0
        added = 0
        for codepoint in codepoints:
            if codepoint not in self._layout.overrides:
                self._layout.overrides |= {codepoint}
                added += 1
        if not added:
            return 0
        logger.info("Approved overwrite of %d locked slot(s)", added)
        self._persist_layout()
        return added

    def clear_override(self, codepoint: int) -> None:
        """Revoke the overwrite approval for `codepoint`; no-op when absent or unloaded."""
        if self._layout is None or codepoint not in self._layout.overrides:
            return
        self._layout.overrides -= {codepoint}
        logger.info("Revoked overwrite approval for U+%04X", codepoint)
        self._persist_layout()

    def load_font(
        self, path: str | Path, settings: PlacementSettings | None = None, profiles_dir: str | Path | None = None
    ) -> None:
        """Open a font for editing with `settings`, closing any previously loaded font first."""
        self.close()
        src = Path(path)
        self._profiles_dir = str(profiles_dir) if profiles_dir is not None else DEFAULT_PROFILES_DIR
        self._gen = ThaiPuaFontGenerator(str(src), settings if settings is not None else default_placement_settings())
        self._src_path = src
        self._output_path = self._default_output_path(src, ttf_suffix=self._gen.source_is_cff)
        self._state_version += 1
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

    def set_layout_path(self, path: str) -> None:
        """Change the on-disk layout path; the cached state is re-read on next use."""
        self._layout_path = path
        self._layout = None

    def load_layout(self) -> dict[str, str]:
        """Load layout configuration, bootstrapping the canonical default when missing.

        Materialize the PUA-map cache file so text encode/decode works before any
        font is loaded; return the effective Thai→PUA map.
        """
        self._layout = load_layout_state(self._layout_path)
        if self._layout is None:
            self._layout = LayoutState()
            logger.info("Bootstrapped canonical layout (base U+%04X)", self._layout.base)
        return self._persist_layout()

    def layout_base(self) -> int:
        """Return the current canonical origin; the default when no layout is loaded."""
        return self._layout.base if self._layout is not None else DEFAULT_BASE_CODEPOINT

    def layout_tail_start(self) -> int | None:
        """Return the first relocation-zone codepoint, or `None` before a layout load."""
        return canonical_tail_start(self._layout.base) if self._layout is not None else None

    def set_base_codepoint(self, base: int) -> dict[str, str]:
        """Change the canonical layout origin and rematerialize; return the updated map.

        Existing relocations are kept verbatim; targets that now collide with
        canonical assignments surface as validator errors in the mapping editor.
        Raises `ValueError` when `base` would push the canonical block outside
        the PUA range.
        """
        if self._layout is None:
            raise RuntimeError("Cannot set the base codepoint before loading a layout.")
        if not is_valid_base(base):
            raise ValueError(
                f"Base U+{base:04X} outside the PUA range (U+{PUA_RANGE_START:04X}..U+{max_base_codepoint():04X})"
            )
        self._layout.base = base
        logger.info("Layout base moved to U+%04X", base)
        return self._persist_layout()

    def relocate_key(self, thai_key: str) -> int | None:
        """Move `thai_key` to the first free tail-zone slot; return its new codepoint.

        Return `None` when no layout is loaded or the PUA range is exhausted.
        """
        return self.relocate_keys([thai_key]).get(thai_key)

    def relocate_keys(self, thai_keys: Iterable[str]) -> dict[str, int]:
        """Move several keys into the tail zone with a single layout persist.

        Targets are assigned sequentially past the canonical block; iteration
        stops when the range is exhausted. Return the succeeded key→codepoint
        moves.
        """
        if self._layout is None:
            return {}
        font_cps = {cp for cp in self._gen.font.getBestCmap()} if self._gen is not None and self._gen.font else None
        moved: dict[str, int] = {}
        for thai_key in thai_keys:
            try:
                target = find_relocation_target(
                    canonical_tail_start(self._layout.base), set(self._layout.effective_map().values()), font_cps
                )
            except RuntimeError:
                logger.error("Ran out of free slots relocating %r (%d key(s) already moved)", thai_key, len(moved))
                break
            self._layout.relocations[thai_key] = chr(target)
            logger.debug("Relocated %r to U+%04X", thai_key, target)
            moved[thai_key] = target
        if not moved:
            return {}
        logger.info("Relocated %d key(s)", len(moved))
        self._persist_layout()
        return moved

    def layout_conflicts(self) -> list[LayoutConflict]:
        """Return conflicts between the effective map and the live font's slots.

        Slots the user already overrode are not reported. Empty without a loaded
        font — reconciliation needs real occupants.
        """
        if self._gen is None or self._gen.font is None or self._layout is None:
            return []
        return find_conflicts(self._layout.effective_map(), self.pua_occupants(), resolved=self.allowed_locked())

    def apply_manual_edits(self, new_map: dict[str, str]) -> dict[str, str]:
        """Fold hand-edited mapping values into relocation deltas and return the updated map.

        Values matching their canonical codepoint clear the key's relocation; any
        other single-character value records an explicit relocation.
        """
        if self._layout is None:
            raise RuntimeError("Cannot apply manual edits before loading a layout.")
        for thai_key, pua_char in new_map.items():
            canonical = canonical_codepoint(thai_key, self._layout.base)
            if canonical is not None and len(pua_char) == 1 and ord(pua_char) == canonical:
                self._layout.relocations.pop(thai_key, None)
            else:
                self._layout.relocations[thai_key] = pua_char
        logger.info("Applied %d relocation(s) after manual edit", len(self._layout.relocations))
        return self._persist_layout()

    def _persist_layout(self) -> dict[str, str]:
        """Write layout state and the materialized map cache; return the effective map."""
        if self._layout is None:
            raise RuntimeError("Cannot persist a layout before loading one.")
        save_layout_state(self._layout, self._layout_path)
        mapping = self._layout.effective_map()
        save_pua_map(mapping, self._pua_map_path)
        self._pua_map = mapping
        self._state_version += 1
        return mapping

    def validation_issues(self, pua_map: dict[str, str]) -> list[PuaMapIssue]:
        """Validate `pua_map` against the live font's slots; an empty list means clean.

        User-approved overrides downgrade their locked-slot verdicts to warnings.
        Structural checks still run without a loaded font; font-aware slot checks
        are skipped until one is loaded.
        """
        return validate_pua_map(pua_map, self.pua_slot_context(), allowed_locked=self.allowed_locked())

    def pua_occupants(self) -> list[PuaOccupant]:
        """Scan the live font's PUA range; empty without a loaded font."""
        if self._gen is None or self._gen.font is None:
            return []
        return scan_pua_occupants(self._gen.font)

    def pua_slot_context(self) -> PuaSlotContext | None:
        """Snapshot the font's slot facts for mapping validation, or `None` without a font."""
        if self._gen is None or self._gen.font is None:
            return None
        return slot_context_from_font(self._gen.font)

    def glyph_name_for(self, codepoint: int) -> str | None:
        """Return the font's glyph name for `codepoint`, or `None` when unmapped."""
        if self._gen is None:
            return None
        return self._gen.glyph_name_for(codepoint)

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
        Return (0, 0) without a font.
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
        glyph_name = self._gen.glyph_name_for(codepoint)
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
        bbox = self._gen.bounding_box(glyph_name)
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

        Return an empty list for non-composite glyphs or fonts without `glyf`.
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
            base = self._gen.bounding_box(component.glyphName)
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
            base = self._gen.bounding_box(placement.glyph_name)
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
        """Rebuild the composite at its PUA codepoint and render the current occupant.

        The returned render carries `install_status` so callers can distinguish a
        real install from a skip that left the slot untouched. The state version only
        moves when occupancy-visible state changed; reinstalling an owned slot or a
        skip leaves caches keyed on it valid.
        """
        if self._gen is None:
            raise RuntimeError("Cannot regenerate composites without a loaded font.")
        result = self._gen.install_composite(
            spec.pua_code,
            spec.cons_uni,
            spec.below_uni,
            spec.above_uni,
            spec.tone_uni,
            settings=settings,
            allowed_locked=self.allowed_locked(),
        )
        logger.debug("Regenerated U+%04X: %s", spec.pua_code, result.status.value)
        if result.status in _OCCUPANCY_VISIBLE_STATUSES:
            self._state_version += 1
        render = self.render_glyph(spec.pua_code, path if path is not None else _NullPath(), spec=spec)
        render.install_status = result.status
        return render

    def regenerate_all(
        self,
        settings: PlacementSettings,
        pua_map: dict[str, str],
        progress: Callable[[int, int], None] | None = None,
    ) -> list[InstallResult]:
        """Rebuild every composite in the map, returning one result per spec.

        `progress(done, total)` is invoked after each install so a GUI can update
        a progress indicator during a full rebuild.
        """
        if self._gen is None:
            raise RuntimeError("Cannot regenerate composites without a loaded font.")
        allowed = self.allowed_locked()
        specs = list(iter_composite_specs(pua_map))
        total = len(specs)
        results: list[InstallResult] = []
        for index, spec in enumerate(specs):
            results.append(
                self._gen.install_composite(
                    spec.pua_code,
                    spec.cons_uni,
                    spec.below_uni,
                    spec.above_uni,
                    spec.tone_uni,
                    settings=settings,
                    allowed_locked=allowed,
                )
            )
            if progress is not None:
                progress(index + 1, total)
        self._state_version += 1
        return results

    def save_font(
        self,
        output_path: str | Path | None,
        settings: PlacementSettings,
        pua_map: dict[str, str],
        progress: Callable[[int, int], None] | None = None,
    ) -> str:
        """Rebuild all composites and write the font to `output_path`."""
        if self._gen is None:
            raise RuntimeError("Cannot save: no font loaded.")
        target = str(output_path) if output_path is not None else self._output_path
        if target is None:
            raise RuntimeError("Cannot save: no output path available.")
        results = self.regenerate_all(settings, pua_map, progress=progress)
        locked = sum(1 for result in results if result.status is InstallStatus.SKIPPED_LOCKED)
        if locked:
            logger.warning("Saved font keeps %d locked PUA slot(s) untouched (unrecognized content)", locked)
        self._gen.font.save(target)
        self._output_path = target
        logger.info("Saved generated font to %s", target)
        return target

    def default_profile_path(self) -> Path | None:
        """Return the suggested `<stem>.json` path under the profiles dir, or `None` before a load."""
        if self._src_path is None:
            return None
        return Path(self._profiles_dir) / f"{self._src_path.stem}.json"

    def load_profile(self, path: str | Path) -> PlacementSettings:
        """Read placement settings from `path`, falling back to defaults on unreadable content."""
        settings = load_placement_settings(path)
        logger.info("Loaded profile %s", path)
        return settings

    def save_profile(self, path: str | Path, settings: PlacementSettings) -> Path:
        """Write `settings` to `path` as JSON, creating parent directories."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        save_placement_settings(settings, target)
        return target

    def find_substitutions(self) -> dict[str, list[GlyphSubstitution]]:
        """Return the per-category GSUB substitution catalog for the live font."""
        if self._gen is None or self._gen.font is None:
            return {}
        return find_glyph_substitutions(self._gen.font)

    def close(self) -> None:
        """Close the underlying `TTFont` if one is open; safe to call repeatedly.

        Only font ownership is released — the layout and PUA-map configuration,
        which are independent of the loaded font, are left in place.
        """
        if self._gen is not None and self._gen.font is not None:
            try:
                self._gen.font.close()
            except Exception:
                logger.debug("Ignoring font close failure", exc_info=True)
        self._gen = None
        self._src_path = None
        self._output_path = None
        self._profiles_dir = DEFAULT_PROFILES_DIR
        self._state_version += 1


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
