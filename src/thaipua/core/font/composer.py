"""Compose and install composite PUA glyphs from Thai clusters onto a loaded font."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from thaipua.core.font.bounding_box import BoundingBox, BoundingBoxCache
from thaipua.core.font.cff_convert import convert_cff_to_truetype, has_cff_outlines
from thaipua.core.font.ownership import TOOL_GLYPH_PREFIX, SlotOwnership, classify_pua_slot
from thaipua.core.fonttools.settings import (
    ROLE_ABOVE_VOWEL,
    ROLE_BELOW_VOWEL,
    ROLE_TONE_MARK,
    ROLE_TONE_MARK_ON_ABOVE_VOWEL,
    SNAP_ABOVE_TO_CONS,
    SNAP_BELOW_TO_CONS,
    SNAP_TONE_TO_ABOVE,
    SUB_ABOVE_VOWEL,
    SUB_BELOW_VOWEL,
    SUB_TONE_MARK,
    ConsonantSettings,
    PlacementSettings,
    combo_key_from_codepoints,
    default_placement_settings,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class _AboveVowelPlacement:
    """Placement of an above-base vowel, retaining its untranslated bounds for tone stacking."""

    dx: int
    dy: int
    bounding_box: BoundingBox | None


@dataclass(slots=True, frozen=True)
class ComponentPlacement:
    """One resolved composite component: a glyph name plus its affine transform."""

    glyph_name: str
    transform: tuple[int, int, int, int, int, int]


class InstallStatus(Enum):
    """Outcome categories for a single composite install."""

    INSTALLED = "installed"
    REPLACED_OWNED = "replaced_owned"
    REPLACED_FOREIGN_COMPOSITE = "replaced_foreign_composite"
    OVERRIDDEN_LOCKED = "overridden_locked"
    SKIPPED_LOCKED = "skipped_locked"
    SKIPPED_MISSING_CONSONANT = "skipped_missing_consonant"


@dataclass(slots=True, frozen=True)
class InstallResult:
    """Outcome of one install attempt: the status and the affected glyph name."""

    status: InstallStatus
    glyph_name: str | None


_INSTALL_STATUS_BY_OWNERSHIP: dict[SlotOwnership, InstallStatus] = {
    SlotOwnership.FREE: InstallStatus.INSTALLED,
    SlotOwnership.OWNED: InstallStatus.REPLACED_OWNED,
    SlotOwnership.REPLACEABLE: InstallStatus.REPLACED_FOREIGN_COMPOSITE,
}
"""Map slot ownership verdicts to install outcomes; locked slots never reach an install."""


class ThaiPuaFontGenerator:
    """Generate and install composite PUA glyphs into a single loaded font."""

    def __init__(self, font_path: str, settings: PlacementSettings | None) -> None:
        """Load the font for editing, converting CFF sources to TrueType outlines in memory."""
        self.font = TTFont(font_path)
        self.source_is_cff = has_cff_outlines(self.font)
        if self.source_is_cff:
            convert_cff_to_truetype(self.font)
        self.bbox = BoundingBoxCache(self.font)
        self.settings = settings if settings is not None else default_placement_settings()
        self._glyph_names: set[str] = set(self.font.getGlyphOrder())
        self._cmap: dict[int, str] = self.font.getBestCmap()

    def has_glyph(self, glyph_name: str | None) -> bool:
        """Return whether `glyph_name` exists in the font."""
        return bool(glyph_name) and glyph_name in self._glyph_names

    def get_glyph_name(self, unicode_point: int | None) -> str | None:
        """Return the glyph name for `unicode_point`; fall back to a synthetic `uniXXXX` name when unmapped."""
        if not unicode_point:
            return None
        return self._cmap.get(unicode_point) or f"uni{unicode_point:04X}"

    def glyph_name_for(self, codepoint: int) -> str | None:
        """Return the raw cmap glyph name for `codepoint`, or `None` when unmapped."""
        return self._cmap.get(codepoint)

    def bounding_box(self, glyph_name: str) -> BoundingBox | None:
        """Return the cached bounding box for `glyph_name`, or `None` when unavailable."""
        return self.bbox.get_bounding_box(glyph_name)

    @staticmethod
    def _combo_key(below_uni: int | None, above_uni: int | None, tone_uni: int | None) -> str | None:
        """Return the canonical combination key for a multi-mark cluster, or `None` for single marks."""
        cps = [c for c in [below_uni, above_uni, tone_uni] if c]
        if len(cps) < 2:
            return None
        return combo_key_from_codepoints(cps)

    def resolve_consonant(
        self, cons_uni: int, cons_settings: ConsonantSettings, *, present_roles: frozenset[str]
    ) -> str:
        """Resolve the consonant glyph under its substitution override; return `""` when absent from the font."""
        default_name = self.get_glyph_name(cons_uni)
        if default_name is None:
            return ""
        explicit = cons_settings.substitution_for(cons_uni, present_roles=present_roles)
        if explicit:
            if self.has_glyph(explicit):
                logger.info("[ALT-EXPLICIT] %s -> %s (consonant)", default_name, explicit)
                return explicit
            logger.info(
                "[ALT-EXPLICIT-MISSED] %s -> %s: glyph not in font; using the default consonant glyph",
                default_name,
                explicit,
            )
        return default_name

    def resolve_below_vowel(
        self, below_uni: int | None, cons_settings: ConsonantSettings, *, present_roles: frozenset[str]
    ) -> str | None:
        """Resolve the below-vowel glyph under its substitution override; return `None` when none is requested."""
        if not below_uni:
            return None
        default_name = self.get_glyph_name(below_uni)
        explicit = cons_settings.substitution_for(below_uni, present_roles=present_roles)
        if explicit and self.has_glyph(explicit):
            logger.info("[ALT-EXPLICIT] %s -> %s (below_vowel)", default_name, explicit)
            return explicit
        if explicit:
            logger.info(
                "[ALT-EXPLICIT-MISSED] %s -> %s: glyph not in font; using the default below-vowel glyph",
                default_name,
                explicit,
            )
        return default_name

    def resolve_vowel(
        self, above_uni: int | None, cons_settings: ConsonantSettings, *, present_roles: frozenset[str]
    ) -> str | None:
        """Resolve the above-vowel glyph under its substitution override; return `None` when none is requested."""
        if not above_uni:
            return None
        default_name = self.get_glyph_name(above_uni)
        explicit = cons_settings.substitution_for(above_uni, present_roles=present_roles)
        if explicit and self.has_glyph(explicit):
            logger.info("[ALT-EXPLICIT] %s -> %s (above_vowel)", default_name, explicit)
            return explicit
        if explicit:
            logger.info(
                "[ALT-EXPLICIT-MISSED] %s -> %s: glyph not in font; using the default above-vowel glyph",
                default_name,
                explicit,
            )
        return default_name

    def resolve_tone(
        self, tone_uni: int | None, cons_settings: ConsonantSettings, *, present_roles: frozenset[str]
    ) -> str | None:
        """Resolve the tone-mark glyph under its substitution override; return `None` when none is requested."""
        if not tone_uni:
            return None
        default_name = self.get_glyph_name(tone_uni)
        explicit = cons_settings.substitution_for(tone_uni, present_roles=present_roles)
        if explicit and self.has_glyph(explicit):
            logger.info("[ALT-EXPLICIT] %s -> %s (tone_mark)", default_name, explicit)
            return explicit
        if explicit:
            logger.info(
                "[ALT-EXPLICIT-MISSED] %s -> %s: glyph not in font; using the default tone-mark glyph",
                default_name,
                explicit,
            )
        return default_name

    def _place_below_vowel(
        self,
        components: list[ComponentPlacement],
        *,
        effective: PlacementSettings,
        cons_uni: int,
        cons_settings: ConsonantSettings,
        cons_advance: int,
        cons_bbox: BoundingBox | None,
        below_uni: int | None,
        vowel_name: str,
        combo_key: str | None,
    ) -> None:
        """Place the below vowel against the consonant, snapping its top edge to the consonant when configured."""
        snap_cfg = cons_settings.snap_for(SNAP_BELOW_TO_CONS)
        do_snap = snap_cfg.enabled if snap_cfg is not None else False
        gap = snap_cfg.gap if snap_cfg is not None else 0
        offset = effective.mark_offset_for(cons_uni, ROLE_BELOW_VOWEL, mark_uni=below_uni, combo_key=combo_key)
        dx = cons_advance + offset.x
        if do_snap:
            vowel_box = self.bbox.get_bounding_box(vowel_name)
            if vowel_box is None or cons_bbox is None:
                base_dy = 0
                logger.warning(
                    "[BBOX-MISSING] %s: missing bounding box; below-vowel snap falls back to dy=0", vowel_name
                )
            else:
                base_dy = cons_bbox.y_min - vowel_box.y_max + gap
                logger.info("[PLACE-BELOW-SNAP] %s: base_dy=%d", vowel_name, base_dy)
        else:
            base_dy = 0
            logger.info("[PLACE-BELOW-DEFAULT] %s: base_dy=%d", vowel_name, base_dy)
        dy = base_dy + offset.y
        logger.info("[PLACE-BELOW] %s: dx=%d dy=%d", vowel_name, dx, dy)
        components.append(ComponentPlacement(vowel_name, (1, 0, 0, 1, dx, dy)))

    def _place_above_vowel(
        self,
        components: list[ComponentPlacement],
        *,
        effective: PlacementSettings,
        cons_uni: int,
        cons_settings: ConsonantSettings,
        cons_advance: int,
        cons_bbox: BoundingBox | None,
        above_uni: int | None,
        vowel_name: str,
        combo_key: str | None,
    ) -> _AboveVowelPlacement:
        """Place the above vowel against the consonant, snapping its bottom edge when configured."""
        snap_cfg = cons_settings.snap_for(SNAP_ABOVE_TO_CONS)
        do_snap = snap_cfg.enabled if snap_cfg is not None else False
        gap = snap_cfg.gap if snap_cfg is not None else 0
        offset = effective.mark_offset_for(cons_uni, ROLE_ABOVE_VOWEL, mark_uni=above_uni, combo_key=combo_key)
        dx = cons_advance + offset.x
        vowel_box = self.bbox.get_bounding_box(vowel_name)
        if do_snap:
            if vowel_box is None or cons_bbox is None:
                base_dy = 0
                logger.warning(
                    "[BBOX-MISSING] %s: missing bounding box; above-vowel snap falls back to dy=0", vowel_name
                )
            else:
                base_dy = cons_bbox.y_max - vowel_box.y_min + gap
                logger.info("[PLACE-ABOVE-SNAP] %s: base_dy=%d", vowel_name, base_dy)
        else:
            base_dy = 0
            logger.info("[PLACE-ABOVE-DEFAULT] %s: base_dy=%d", vowel_name, base_dy)
        dy = base_dy + offset.y
        logger.info("[PLACE-ABOVE] %s: dx=%d dy=%d", vowel_name, dx, dy)
        components.append(ComponentPlacement(vowel_name, (1, 0, 0, 1, dx, dy)))
        return _AboveVowelPlacement(dx, dy, vowel_box)

    def _place_tone(
        self,
        components: list[ComponentPlacement],
        *,
        effective: PlacementSettings,
        cons_uni: int,
        cons_settings: ConsonantSettings,
        cons_advance: int,
        tone_uni: int | None,
        tone_name: str,
        above_placement: _AboveVowelPlacement | None,
        combo_key: str | None,
    ) -> None:
        """Place the tone mark, snapping it onto the above vowel when one is stacked."""
        base_role = ROLE_TONE_MARK_ON_ABOVE_VOWEL if above_placement is not None else None
        offset = effective.mark_offset_for(
            cons_uni, ROLE_TONE_MARK, mark_uni=tone_uni, combo_key=combo_key, base_role=base_role
        )
        dx = cons_advance + offset.x
        if above_placement is not None:
            snap_cfg = cons_settings.snap_for(SNAP_TONE_TO_ABOVE)
            do_snap = snap_cfg.enabled if snap_cfg is not None else False
            gap = snap_cfg.gap if snap_cfg is not None else 0
            if do_snap:
                tone_box = self.bbox.get_bounding_box(tone_name)
                if tone_box is None or above_placement.bounding_box is None:
                    base_dy = 0
                    logger.warning(
                        "[BBOX-MISSING] %s: missing bounding box; tone-on-vowel snap falls back to dy=0", tone_name
                    )
                else:
                    effective_vowel_y_max = above_placement.bounding_box.y_max + above_placement.dy
                    base_dy = effective_vowel_y_max - tone_box.y_min + gap
                    logger.info("[PLACE-TONE-STACK-SNAP] %s: base_dy=%d", tone_name, base_dy)
            else:
                base_dy = 0
                logger.info("[PLACE-TONE-STACK-DEFAULT] %s: base_dy=%d", tone_name, base_dy)
        else:
            base_dy = 0
            logger.info("[PLACE-TONE-DEFAULT] %s: base_dy=%d", tone_name, base_dy)
        dy = base_dy + offset.y
        logger.info("[PLACE-TONE] %s: dx=%d dy=%d", tone_name, dx, dy)
        components.append(ComponentPlacement(tone_name, (1, 0, 0, 1, dx, dy)))

    def compose_components(
        self,
        cons_uni: int,
        below_uni: int | None,
        above_uni: int | None,
        tone_uni: int | None,
        settings: PlacementSettings | None = None,
        *,
        pua_code: int | None = None,
    ) -> list[ComponentPlacement] | None:
        """Compute component placements for a cluster without modifying the font.

        Apply substitutions, offsets, and snaps exactly as an install would; return
        `None` when the consonant glyph is missing from the font.
        """
        effective = settings if settings is not None else self.settings
        mark_roles = set()
        if below_uni:
            mark_roles.add(SUB_BELOW_VOWEL)
        if above_uni:
            mark_roles.add(SUB_ABOVE_VOWEL)
        if tone_uni:
            mark_roles.add(SUB_TONE_MARK)
        present_roles = frozenset(mark_roles)
        cons_settings = effective.for_consonant(cons_uni)
        actual_cons = self.resolve_consonant(cons_uni, cons_settings, present_roles=present_roles)
        if not self.has_glyph(actual_cons):
            logger.warning(
                "[SKIP] U+%04X: consonant glyph '%s' (U+%04X) not found in font",
                pua_code or 0,
                actual_cons,
                cons_uni,
            )
            return None
        below_name = self.resolve_below_vowel(below_uni, cons_settings, present_roles=present_roles)
        above_name = self.resolve_vowel(above_uni, cons_settings, present_roles=present_roles)
        actual_tone_name = self.resolve_tone(tone_uni, cons_settings, present_roles=present_roles)
        components: list[ComponentPlacement] = [ComponentPlacement(actual_cons, (1, 0, 0, 1, 0, 0))]
        cons_advance, _cons_lsb = self.font["hmtx"][actual_cons]
        cons_box = self.bbox.get_bounding_box(actual_cons)
        combo_key = self._combo_key(below_uni, above_uni, tone_uni)
        if below_name:
            self._place_below_vowel(
                components,
                effective=effective,
                cons_uni=cons_uni,
                cons_settings=cons_settings,
                cons_advance=cons_advance,
                cons_bbox=cons_box,
                below_uni=below_uni,
                vowel_name=below_name,
                combo_key=combo_key,
            )
        above_placement = None
        if above_name:
            above_placement = self._place_above_vowel(
                components,
                effective=effective,
                cons_uni=cons_uni,
                cons_settings=cons_settings,
                cons_advance=cons_advance,
                cons_bbox=cons_box,
                above_uni=above_uni,
                vowel_name=above_name,
                combo_key=combo_key,
            )
        if actual_tone_name:
            self._place_tone(
                components,
                effective=effective,
                cons_uni=cons_uni,
                cons_settings=cons_settings,
                cons_advance=cons_advance,
                tone_uni=tone_uni,
                tone_name=actual_tone_name,
                above_placement=above_placement,
                combo_key=combo_key,
            )
        return components

    def install_composite(
        self,
        pua_code: int,
        cons_uni: int,
        below_uni: int | None = None,
        above_uni: int | None = None,
        tone_uni: int | None = None,
        *,
        settings: PlacementSettings | None = None,
        allowed_locked: frozenset[int] | None = None,
    ) -> InstallResult:
        """Install a composite glyph at `pua_code` and report the outcome.

        Free, owned, and replaceable slots are rebuilt in place under the stable
        `thaipua_XXXX` name, keeping glyph order and cmap mapping intact. Locked slots
        and missing consonants are skipped without writing anything, except locked
        slots listed in `allowed_locked`, which install with `OVERRIDDEN_LOCKED`.
        """
        existing = self._cmap.get(pua_code)
        ownership = classify_pua_slot(existing, self.font.get("glyf"))
        overridden = ownership is SlotOwnership.LOCKED and allowed_locked is not None and pua_code in allowed_locked
        if ownership is SlotOwnership.LOCKED and not overridden:
            logger.warning(
                "[LOCKED] U+%04X: mapped to '%s' (unrecognized content); slot not overwritten",
                pua_code,
                existing,
            )
            return InstallResult(InstallStatus.SKIPPED_LOCKED, existing)
        components = self.compose_components(
            cons_uni, below_uni, above_uni, tone_uni, settings=settings, pua_code=pua_code
        )
        if components is None:
            return InstallResult(InstallStatus.SKIPPED_MISSING_CONSONANT, None)
        pen = TTGlyphPen(self.font.getGlyphSet())
        for placement in components:
            pen.addComponent(placement.glyph_name, placement.transform)
        new_glyph = pen.glyph()
        new_glyph.recalcBounds(self.font["glyf"])
        glyph_name = f"{TOOL_GLYPH_PREFIX}{pua_code:04X}"
        self._install_composite_glyph(glyph_name, new_glyph, pua_code, width_from=components[0].glyph_name)
        parts = [components[0].glyph_name] + [f"+{c.glyph_name}" for c in components[1:]]
        status = InstallStatus.OVERRIDDEN_LOCKED if overridden else _INSTALL_STATUS_BY_OWNERSHIP[ownership]
        if overridden:
            logger.info("[OVERRIDE-LOCKED] U+%04X: replaced locked glyph '%s' per user override", pua_code, existing)
        elif ownership is SlotOwnership.REPLACEABLE:
            logger.info(
                "[REPLACE-FOREIGN] U+%04X: replaced foreign composite '%s' with '%s'", pua_code, existing, glyph_name
            )
        else:
            logger.info("[OK] U+%04X = %s (%s)", pua_code, " ".join(parts), glyph_name)
        return InstallResult(status, glyph_name)

    def _install_composite_glyph(self, glyph_name: str, glyph: Any, unicode_point: int, width_from: str) -> bool:
        """Store the glyph and map `unicode_point` on every Unicode cmap subtable.

        Append the name to the glyph order when new; otherwise replace the stored glyph
        in place so existing references stay valid. Copy the advance width from
        `width_from` and report whether an existing glyph was replaced.
        """
        replaced = glyph_name in self._glyph_names
        if not replaced:
            order = self.font.getGlyphOrder()
            order.append(glyph_name)
            self.font.setGlyphOrder(order)
            self._glyph_names.add(glyph_name)
        self.font["glyf"][glyph_name] = glyph
        width, _unused_lsb = self.font["hmtx"][width_from]
        lsb = getattr(glyph, "xMin", 0)
        self.font["hmtx"][glyph_name] = (width, lsb)
        for table in self.font["cmap"].tables:
            if table.isUnicode():
                table.cmap[unicode_point] = glyph_name
        self._cmap[unicode_point] = glyph_name
        self.bbox.invalidate(glyph_name)
        return replaced
