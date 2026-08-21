"""Composite PUA glyph assembly from a source font via advance-width composition.

`ThaiPuaFontGenerator` stacks the consonant, vowel, and tone-mark glyphs as components
shifted by the consonant's advance width (`dx = cons_advance`, `dy = 0`), preserving the
source font's vertical mark placement. Per-axis offsets and snap deltas from
`PlacementSettings` layer on top of that base — the offset tiering lives in
`ConsonantSettings.offset_for`, the snap math in the `_place_*` methods, the
ownership-aware install in `install_composite`, and the read-only preview path in
`compose_components`.

`install_composite` replaces glyphs **in place under a stable prefixed name**
(`thaipua_XXXX`) after consulting `classify_pua_slot`: owned slots are rebuilt freely,
foreign composites are replaced with an info log, and locked slots (unrecognized
non-composite content) are skipped and reported via `InstallResult` — no silent drops,
and callers never need to evict first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from thaipua.core.fonttools.bounding_box import BoundingBox, BoundingBoxCache
from thaipua.core.fonttools.ownership import TOOL_GLYPH_PREFIX, SlotOwnership, classify_pua_slot
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
    """A placed above-vowel's translation and pre-translation bounding box.

    The bounding box is retained so a tone mark stacked on the vowel can compute its
    target height.

    Attributes:
        bounding_box: The vowel's original (pre-translation) bounding box, or `None`
            when the vowel glyph has no drawable contour.
    """

    dx: int
    dy: int
    bounding_box: BoundingBox | None


@dataclass(slots=True, frozen=True)
class ComponentPlacement:
    """One resolved composite part: a glyph name and its fontTools 6-tuple affine.

    `compose_components` yields these without installing anything, so callers can
    replay the exact layout `install_composite` would produce (offsets, substitutions,
    snaps included) into their own pen or path.
    """

    glyph_name: str
    transform: tuple[int, int, int, int, int, int]


class InstallStatus(Enum):
    """Outcome of one `install_composite` call."""

    INSTALLED = "installed"
    """Fresh install onto a previously unmapped PUA codepoint."""

    REPLACED_OWNED = "replaced_owned"
    """A prefixed glyph at this slot was rebuilt in place."""

    REPLACED_FOREIGN_COMPOSITE = "replaced_foreign_composite"
    """An unreferenced foreign composite was replaced."""

    SKIPPED_LOCKED = "skipped_locked"
    """Slot is locked (unrecognized non-composite content); nothing was written."""

    SKIPPED_MISSING_CONSONANT = "skipped_missing_consonant"
    """The resolved consonant glyph is absent from the font; nothing was written."""


@dataclass(slots=True, frozen=True)
class InstallResult:
    """Report of one composite install attempt, surfaced to callers and UI."""

    status: InstallStatus
    glyph_name: str | None


_INSTALL_STATUS_BY_OWNERSHIP: dict[SlotOwnership, InstallStatus] = {
    SlotOwnership.FREE: InstallStatus.INSTALLED,
    SlotOwnership.OWNED: InstallStatus.REPLACED_OWNED,
    SlotOwnership.REPLACEABLE: InstallStatus.REPLACED_FOREIGN_COMPOSITE,
}
"""Ownership verdict to install-outcome mapping; LOCKED never reaches an install."""


class ThaiPuaFontGenerator:
    """Owns a loaded TTFont, its bounding-box cache, and the active `PlacementSettings`.

    Installs composite PUA glyphs into the font in place; build a fresh instance per
    output font. `compose_components` performs the same layout read-only for preview.
    """

    def __init__(self, font_path: str, settings: PlacementSettings | None) -> None:
        """Load the source font and its bounding-box reader.

        Profile resolution is the caller's responsibility (see
        `thaipua.core.profiles.resolve_settings_profile`). `settings=None` falls back
        to `default_placement_settings()` (pure advance-width composition, no overrides
        or snaps).
        """
        self.font = TTFont(font_path)
        self.bbox = BoundingBoxCache(self.font)
        self.settings = settings if settings is not None else default_placement_settings()
        self._glyph_names: set[str] = set(self.font.getGlyphOrder())
        self._cmap: dict[int, str] = self.font.getBestCmap()

    def has_glyph(self, glyph_name: str | None) -> bool:
        """Return whether `glyph_name` exists in the font.

        Returns `False` if `glyph_name` is `None` or empty.
        """
        return bool(glyph_name) and glyph_name in self._glyph_names

    def get_glyph_name(self, unicode_point: int | None) -> str | None:
        """Return the font's glyph name for `unicode_point`.

        Falls back to a synthetic `uniXXXX` name when the codepoint has no cmap entry.
        Returns `None` for `None` or codepoint `0`.
        """
        if not unicode_point:
            return None
        return self._cmap.get(unicode_point) or f"uni{unicode_point:04X}"

    @staticmethod
    def _combo_key(below_uni: int | None, above_uni: int | None, tone_uni: int | None) -> str | None:
        """Return the canonical cluster-key for `combo_offsets` lookups.

        The cluster key is the cluster's mark characters concatenated in ascending-
        codepoint order, so settings overrides apply to a specific mark set regardless
        of the user's input ordering. Returns `None` when the cluster has no marks.
        """
        cps = [c for c in [below_uni, above_uni, tone_uni] if c]
        return combo_key_from_codepoints(cps)

    def resolve_consonant(
        self, cons_uni: int, cons_settings: ConsonantSettings, *, present_roles: frozenset[str]
    ) -> str:
        """Resolve the consonant glyph via the per-consonant self-substitution override.

        This is a self-substitution: the rule's codepoint is `cons_uni` itself, scoped
        to this consonant's entry and gated on `present_roles`. When the override names
        an absent glyph, the miss is logged and the default glyph is used. With no
        override, the default glyph is returned unchanged. Returns an empty string when
        the consonant glyph is missing from the font.
        """
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
        """Resolve a below-base vowel glyph via the per-consonant substitution override.

        Returns `None` when no below vowel was requested (`below_uni` falsy).
        """
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
        """Resolve an above-base vowel glyph via the per-consonant substitution override.

        Returns `None` when no above vowel was requested (`above_uni` falsy).
        """
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
        """Resolve a tone-mark glyph via the per-consonant substitution override.

        Returns `None` when no tone was requested (`tone_uni` falsy).
        """
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
        cons_settings: ConsonantSettings,
        cons_advance: int,
        cons_bbox: BoundingBox | None,
        below_uni: int | None,
        vowel_name: str,
        combo_key: str | None,
    ) -> None:
        """Place a below-base vowel component.

        Base Y is `0` (font-design height) unless the `below_vowel_to_consonant` snap is
        on, in which case the vowel's `y_max` snaps to the consonant's `y_min` plus
        `gap`. A missing bounding box falls back to `dy=0` with a warning.
        """
        snap_cfg = cons_settings.snap_for(SNAP_BELOW_TO_CONS)
        do_snap = snap_cfg.enabled if snap_cfg is not None else False
        gap = snap_cfg.gap if snap_cfg is not None else 0
        offset = cons_settings.offset_for(ROLE_BELOW_VOWEL, mark_uni=below_uni, combo_key=combo_key)
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
        cons_settings: ConsonantSettings,
        cons_advance: int,
        cons_bbox: BoundingBox | None,
        above_uni: int | None,
        vowel_name: str,
        combo_key: str | None,
    ) -> _AboveVowelPlacement:
        """Place an above-base vowel component.

        Base Y is `0` (font-design height) unless the `above_vowel_to_consonant` snap is
        on, in which case the vowel's `y_min` snaps to the consonant's `y_max` plus
        `gap`. Returns the final translation and the vowel's pre-translation bounding
        box so a tone stacked on it can compute its own target height.
        """
        snap_cfg = cons_settings.snap_for(SNAP_ABOVE_TO_CONS)
        do_snap = snap_cfg.enabled if snap_cfg is not None else False
        gap = snap_cfg.gap if snap_cfg is not None else 0
        offset = cons_settings.offset_for(ROLE_ABOVE_VOWEL, mark_uni=above_uni, combo_key=combo_key)
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
        cons_settings: ConsonantSettings,
        cons_advance: int,
        tone_uni: int | None,
        tone_name: str,
        above_placement: _AboveVowelPlacement | None,
        combo_key: str | None,
    ) -> None:
        """Place a tone-mark component.

        When stacked on an above vowel (`above_placement` not `None`), base Y snaps the
        tone's `y_min` to the vowel's effective `y_max` (pre-translation `y_max` + final
        `dy` + `gap`) when `tone_mark_to_above_vowel` is on. Otherwise base Y is `0`.
        When stacked, the base-offset fallback tier resolves against
        `ROLE_TONE_MARK_ON_ABOVE_VOWEL` so the stack gets an independent base offset.
        Combo/mark overrides still key on `ROLE_TONE_MARK`.
        """
        base_role = ROLE_TONE_MARK_ON_ABOVE_VOWEL if above_placement is not None else None
        offset = cons_settings.offset_for(ROLE_TONE_MARK, mark_uni=tone_uni, combo_key=combo_key, base_role=base_role)
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
        """Resolve and lay out the `cons_uni` + marks components under `settings`.

        Pure read-only computation — resolves substitutions and computes the exact
        offset/snap placements `install_composite` would install, but returns the
        `ComponentPlacement` list instead of touching `glyf`/`hmtx`/`cmap`, so callers
        can replay the layout into their own pen or path for any codepoint without
        mutating the font. `settings=None` uses the generator's current settings.
        Returns `None` when the resolved consonant glyph is missing from the font.
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
    ) -> InstallResult:
        """Resolve, assemble, and install a composite PUA glyph at `pua_code`.

        The slot's current occupant is classified via `classify_pua_slot`:

        - FREE / OWNED / REPLACEABLE slots proceed; the composite is installed under
          the stable prefixed name `thaipua_XXXX`, **replacing any existing glyph in
          place** — the glyph order entry and cmap mapping stay intact across rebuilds,
          so anything referencing the previous glyph by name keeps resolving.
        - LOCKED slots (unrecognized non-composite content, dangling cmap entries, or
          non-glyf fonts) are skipped and reported as `InstallStatus.SKIPPED_LOCKED`;
          nothing is written.
        - A missing consonant glyph yields `SKIPPED_MISSING_CONSONANT`.

        Returns an `InstallResult` describing exactly what happened; callers surface
        skip statuses rather than discovering them from logs. `settings=None` uses the
        generator's current settings.
        """
        existing = self._cmap.get(pua_code)
        ownership = classify_pua_slot(existing, self.font.get("glyf"))
        if ownership is SlotOwnership.LOCKED:
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
        status = _INSTALL_STATUS_BY_OWNERSHIP[ownership]
        if ownership is SlotOwnership.REPLACEABLE:
            logger.info(
                "[REPLACE-FOREIGN] U+%04X: replaced foreign composite '%s' with '%s'", pua_code, existing, glyph_name
            )
        else:
            logger.info("[OK] U+%04X = %s (%s)", pua_code, " ".join(parts), glyph_name)
        return InstallResult(status, glyph_name)

    def _install_composite_glyph(self, glyph_name: str, glyph: Any, unicode_point: int, width_from: str) -> bool:
        """Register `glyph` under `glyph_name` in `glyf`, `hmtx`, `cmap`, and the glyph-name set.

        Appends `glyph_name` to the glyph order when new, otherwise replaces the stored
        glyph object in place (same name → GSUB/GPOS references remain valid). Copies
        the advance width from `width_from` (using the LSB from the glyph's own
        `xMin`), maps `unicode_point` on every Unicode cmap subtable, and invalidates
        the bounding-box cache so stale geometry is never served. Returns `True` when
        an existing glyph was replaced.
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


__all__ = [
    "ComponentPlacement",
    "InstallResult",
    "InstallStatus",
    "ThaiPuaFontGenerator",
]
