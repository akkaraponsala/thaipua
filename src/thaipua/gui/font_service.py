"""Backend facade over the workspace, renderer, and layout store; the sole bridge between GUI and core."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from enum import Enum
from pathlib import Path

from thaipua.core.constants import PUA_RANGE_START
from thaipua.core.domain.cluster import canonical_cluster_key, try_key
from thaipua.core.domain.errors import LayoutError, SettingsError
from thaipua.core.domain.resolution import OverrideApproval, OverrideRevocation, RelocatePin, ResolveCommand
from thaipua.core.domain.settings import (
    Metadata,
    PlacementSettings,
    default_placement_settings,
)
from thaipua.core.font.alternates import GlyphSubstitution, find_glyph_substitutions
from thaipua.core.font.composer import InstallResult, InstallStatus, ThaiPuaFontGenerator
from thaipua.core.font.map_validation import (
    PuaMapIssue,
    PuaSlotContext,
    slot_context_from_font,
    validate_pua_map,
)
from thaipua.core.font.occupancy import PuaOccupant, scan_pua_occupants
from thaipua.core.font.specs import CompositeSpec
from thaipua.core.font.workspace import FontWorkspace
from thaipua.core.fonttools.settings import (
    load_placement_settings,
    save_placement_settings,
)
from thaipua.core.layout import (
    DEFAULT_BASE_CODEPOINT,
    LayoutConflict,
    LayoutState,
    canonical_tail_start,
    find_conflicts,
    find_relocation_target,
    is_valid_base,
    load_layout_state,
    max_base_codepoint,
    save_layout_state,
)
from thaipua.core.paths import RuntimeRoot
from thaipua.core.pua_map import save_pua_map
from thaipua.core.session import ProjectSession
from thaipua.gui.glyph_pen import PathLike
from thaipua.gui.rendering import FontRenderer, GlyphRender

logger = logging.getLogger(__name__)


class ProfileAutoLoad(Enum):
    """Outcome of the stem-profile auto-load attempt during font open."""

    MISSING = "missing"
    """No stem profile on disk; defaults adopted."""
    APPLIED = "applied"
    """Identity-verified profile adopted."""
    MISMATCH = "mismatch"
    """Profile stamped for a different font; defaults adopted quietly."""
    LEGACY = "legacy"
    """Unstamped profile; defaults adopted, manual adoption offered."""
    UNREADABLE = "unreadable"
    """Corrupt or unsupported profile; defaults adopted with a warning."""


class FontService:
    """Own the workspace, renderer, and project session, and expose font operations to the GUI."""

    def __init__(self, root: RuntimeRoot | None = None) -> None:
        """Initialize an empty service with no loaded font, rooted at `root` or the default."""
        self._workspace = FontWorkspace(root)
        self._renderer = FontRenderer(self._workspace)
        self._profiles_dir = str(self._workspace.root.profiles_dir)
        self._pua_map_path = str(self._workspace.root.pua_map_path)
        self._layout_path = str(self._workspace.root.layout_path)
        self._session = ProjectSession()
        self._document_open = False

    @property
    def _layout(self) -> LayoutState | None:
        """Return the live layout state, or `None` before a layout load."""
        return self._session.layout if self._document_open else None

    @property
    def settings(self) -> PlacementSettings:
        """Return the live placement settings owned by the project session."""
        return self._session.settings

    @property
    def can_undo(self) -> bool:
        """Return whether an undo step is available."""
        return self._session.can_undo

    @property
    def can_redo(self) -> bool:
        """Return whether a redo step is available."""
        return self._session.can_redo

    @property
    def undo_label(self) -> str | None:
        """Return the top undo step's label, or `None` when empty."""
        return self._session.undo_label

    @property
    def redo_label(self) -> str | None:
        """Return the top redo step's label, or `None` when empty."""
        return self._session.redo_label

    def execute_settings(
        self,
        label: str,
        mutate: Callable[[PlacementSettings], PlacementSettings],
        *,
        coalesce_key: str | None = None,
    ) -> bool:
        """Run a settings transform as one undo step; return `True` when anything changed."""
        return self._session.execute(
            label, lambda: self._session.replace_settings(mutate(self._session.settings)), coalesce_key=coalesce_key
        )

    def replace_settings(self, settings: PlacementSettings, *, label: str) -> None:
        """Adopt `settings` as one undo step (profile load, reset defaults)."""
        self._session.execute(label, lambda: self._session.replace_settings(settings))

    def undo(self) -> str | None:
        """Undo one project step, persisting layout files when layout state moved.

        Return the undone step's label, or `None` when history is empty or no
        layout is loaded.
        """
        if self._layout is None:
            return None
        before = self._layout_fingerprint()
        label = self._session.undo()
        if label is None:
            return None
        if self._layout_fingerprint() != before:
            self._persist_layout()
        return label

    def redo(self) -> str | None:
        """Re-apply the latest undone step, persisting layout files when layout state moved.

        Return the redone step's label, or `None` when history is empty or no
        layout is loaded.
        """
        if self._layout is None:
            return None
        before = self._layout_fingerprint()
        label = self._session.redo()
        if label is None:
            return None
        if self._layout_fingerprint() != before:
            self._persist_layout()
        return label

    def _layout_fingerprint(self) -> tuple[int, dict[str, str], dict[str, frozenset[int]]]:
        """Capture the layout part of the document for change comparison."""
        layout = self._session.layout
        return (layout.base, dict(layout.relocations), dict(layout.approvals))

    @property
    def _gen(self) -> ThaiPuaFontGenerator | None:
        """Alias of the workspace's live generator (kept for test fakes)."""
        return self._workspace.gen

    @_gen.setter
    def _gen(self, value: ThaiPuaFontGenerator | None) -> None:
        self._workspace.gen = value

    @property
    def root(self) -> RuntimeRoot:
        """Return the injectable filesystem root this service resolves data paths from."""
        return self._workspace.root

    @property
    def is_loaded(self) -> bool:
        """Return `True` once a source font has been loaded via `load_font`."""
        return self._workspace.is_loaded

    @property
    def generator(self) -> ThaiPuaFontGenerator | None:
        """Return the live `ThaiPuaFontGenerator`, or `None` before a load."""
        return self._workspace.generator

    @property
    def output_path(self) -> str | None:
        """Return the default output path, set when a font is loaded."""
        return self._workspace.output_path

    @property
    def pua_map(self) -> dict[str, str]:
        """Compute the effective Thai-to-PUA map on demand; the layout state is the single owner."""
        if self._layout is None:
            return {}
        return self._layout.effective_map()

    @property
    def pua_map_path(self) -> str:
        """Return the path to the on-disk PUA map cache."""
        return self._pua_map_path

    def set_pua_map_path(self, path: str) -> None:
        """Change the on-disk PUA map cache path used by `save_pua_map`."""
        self._pua_map_path = path

    def _session_id(self) -> str:
        """Return the current font session id (`""` with no loaded font)."""
        font_path = self._workspace.font_path
        return str(font_path) if font_path is not None else ""

    def allowed_locked(self) -> frozenset[int]:
        """Return the PUA codepoints approved for overwrite in the current font session."""
        if self._layout is None:
            return frozenset()
        return self._layout.approvals.get(self._session_id(), frozenset())

    def override_slot(self, codepoint: int) -> None:
        """Approve overwriting the locked slot at `codepoint` and persist it with the layout.

        No-op with a warning before a layout is loaded — approvals are part of layout state.
        """
        if self._layout is None:
            logger.warning("Ignoring override for U+%04X: no layout loaded", codepoint)
            return
        self.override_slots([codepoint])

    def resolve_commands(
        self, commands: Iterable[ResolveCommand], *, label: str, coalesce_key: str | None = None
    ) -> bool:
        """Fold domain slot decisions into layout state as one undo step.

        Return `True` when anything changed; no-ops push nothing. This is the
        single entry point for user slot decisions (override, relocate, remap).
        """
        pending = list(commands)
        if not pending:
            return False

        def mutate() -> None:
            for command in pending:
                self._session.layout.apply_resolution(command)

        return self._session.execute(label, mutate, coalesce_key=coalesce_key)

    def override_slots(self, codepoints: Iterable[int]) -> int:
        """Approve overwriting several locked slots with a single layout persist.

        Return the number of newly approved slots; no-op when nothing is new
        or no layout is loaded.
        """
        if self._layout is None:
            logger.warning("Ignoring bulk override: no layout loaded")
            return 0
        session = self._session_id()
        seen = set(self._layout.approvals.get(session, frozenset()))
        fresh: list[int] = []
        for codepoint in codepoints:
            if codepoint not in seen:
                seen.add(codepoint)
                fresh.append(codepoint)
        if self.resolve_commands(
            (OverrideApproval(font_id=session, codepoint=codepoint) for codepoint in fresh),
            label="Override slots",
            coalesce_key="approvals",
        ):
            logger.info("Approved overwrite of %d locked slot(s)", len(fresh))
            self._persist_layout()
        return len(fresh)

    def clear_override(self, codepoint: int) -> None:
        """Revoke the current session's overwrite approval for `codepoint`; no-op when absent or unloaded."""
        if self._layout is None:
            return
        session = self._session_id()
        approved = self._layout.approvals.get(session, frozenset())
        if codepoint not in approved:
            return
        if self.resolve_commands(
            [OverrideRevocation(font_id=session, codepoint=codepoint)],
            label="Revoke slot override",
            coalesce_key="approvals",
        ):
            logger.info("Revoked overwrite approval for U+%04X", codepoint)
            self._persist_layout()

    def load_font(
        self, path: str | Path, settings: PlacementSettings | None = None, profiles_dir: str | Path | None = None
    ) -> ProfileAutoLoad:
        """Open a font for editing with `settings`, closing any previously loaded font first.

        Ends by adopting the stem profile when it identifies the live font, else
        resetting to defaults; return which outcome applied. Profile problems
        never fail the open — they fall back to defaults.
        """
        self.close()
        self._profiles_dir = str(profiles_dir) if profiles_dir is not None else str(self._workspace.root.profiles_dir)
        self._workspace.load_font(path, settings)
        if self._layout is not None:
            src = str(self._workspace.font_path)
            self._layout.gc_approvals(frozenset({src}))
            self._persist_layout()
        self._session.clear_history()
        return self._adopt_default_profile()

    def _adopt_default_profile(self) -> ProfileAutoLoad:
        """Adopt the stem profile when it identifies the live font; else reset to defaults.

        History stays empty either way — this runs on the session boundary.
        """
        target = self.default_profile_path()
        if target is None or not target.is_file():
            self._session.replace_settings(default_placement_settings())
            return ProfileAutoLoad.MISSING
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Ignoring unreadable profile %s: %s; using defaults", target, exc)
            self._session.replace_settings(default_placement_settings())
            return ProfileAutoLoad.UNREADABLE
        if not isinstance(raw, dict):
            logger.warning("Ignoring non-object profile %s; using defaults", target)
            self._session.replace_settings(default_placement_settings())
            return ProfileAutoLoad.UNREADABLE
        try:
            profile = load_placement_settings(target)
        except SettingsError as exc:
            logger.warning("Ignoring unsupported profile %s: %s; using defaults", target, exc)
            self._session.replace_settings(default_placement_settings())
            return ProfileAutoLoad.UNREADABLE
        family, units = self._live_font_identity()
        meta = profile.metadata
        if not meta.family_name:
            logger.info("Skipping unstamped profile %s; load it manually once, then save to stamp it", target)
            self._session.replace_settings(default_placement_settings())
            return ProfileAutoLoad.LEGACY
        if meta.family_name != family or (
            meta.units_per_em is not None and units is not None and meta.units_per_em != units
        ):
            logger.info("Skipping profile %s stamped for %r; using defaults", target, meta.family_name)
            self._session.replace_settings(default_placement_settings())
            return ProfileAutoLoad.MISMATCH
        self._session.replace_settings(profile)
        logger.info("Auto-loaded profile %s", target)
        return ProfileAutoLoad.APPLIED

    def _live_font_identity(self) -> tuple[str | None, int | None]:
        """Return the live font's (family name, units-per-em) for profile identity checks."""
        font = self._workspace.font
        if font is None:
            return (None, None)
        family: str | None = None
        try:
            name_table = font["name"]
        except KeyError:
            name_table = None
        if name_table is not None:
            family = name_table.getDebugName(16) or name_table.getDebugName(1)
        units: int | None = None
        try:
            units = int(font["head"].unitsPerEm)
        except (KeyError, AttributeError, TypeError, ValueError):
            units = None
        return (family, units)

    @staticmethod
    def _default_output_path(src: Path, *, ttf_suffix: bool = False) -> str:
        """Return the Save-Font default `<stem>_pua.<ext>` beside the source.

        A CFF source is converted to a TrueType working copy at load time, so its
        saved output always carries the `.ttf` extension.
        """
        suffix = ".ttf" if ttf_suffix else src.suffix
        return str(src.with_name(f"{src.stem}_pua{suffix}"))

    def set_layout_path(self, path: str) -> None:
        """Change the on-disk layout path, closing the document; it is re-read on `load_layout`."""
        self._layout_path = path
        self._document_open = False
        self._session.clear_history()

    def load_layout(self) -> dict[str, str]:
        """Load layout configuration, bootstrapping the canonical default when missing.

        Materialize the PUA-map cache file so text encode/decode works before any
        font is loaded; return the effective Thai→PUA map. Replacing the whole
        document clears the undo history.
        """
        state = None
        try:
            state = load_layout_state(self._layout_path)
        except LayoutError as exc:
            logger.warning("Ignoring unsupported layout %s: %s; bootstrapping canonical", self._layout_path, exc)
        if state is None:
            state = LayoutState()
            logger.info("Bootstrapped canonical layout (base U+%04X)", state.base)
        self._session.open_document(state, self._session.settings)
        self._document_open = True
        return self._persist_layout()

    def layout_base(self) -> int:
        """Return the current canonical origin; the default when no layout is loaded."""
        return self._layout.base if self._layout is not None else DEFAULT_BASE_CODEPOINT

    def layout_tail_start(self) -> int | None:
        """Return the first relocation-zone codepoint, or `None` before a layout load."""
        return canonical_tail_start(self._layout.base) if self._layout is not None else None

    def set_base_codepoint(self, base: int) -> dict[str, str]:
        """Change the canonical layout origin and rematerialize; return the updated map.

        Every relocation pin shifts by the same delta the base moved by, so pins
        keep pointing at their cluster's slot; pins pushed outside the PUA range
        are dropped, never clamped. Raises `ValueError` when `base` would push
        the canonical block outside the PUA range.
        """
        if self._layout is None:
            raise RuntimeError("Cannot set the base codepoint before loading a layout.")
        if not is_valid_base(base):
            raise ValueError(
                f"Base U+{base:04X} outside the PUA range (U+{PUA_RANGE_START:04X}..U+{max_base_codepoint():04X})"
            )
        self._session.execute(f"Set base U+{base:04X}", lambda: self._session.layout.set_base(base))
        return self._persist_layout()

    def relocate_key(self, thai_key: str) -> int | None:
        """Move `thai_key` to the first free tail-zone slot; return its new codepoint.

        Return `None` when no layout is loaded, the key is not a legal cluster,
        or the PUA range is exhausted.
        """
        canonical = canonical_cluster_key(thai_key)
        if canonical is None:
            return None
        return self.relocate_keys([canonical]).get(canonical)

    def relocate_keys(self, thai_keys: Iterable[str]) -> dict[str, int]:
        """Move several keys into the tail zone with a single layout persist.

        Targets are assigned sequentially past the canonical block; iteration
        stops when the range is exhausted. Keys canonicalize to stored form
        before pinning, so reordered-but-valid input lands on the same pin.
        Illegal keys are skipped with a warning instead of pinning dead
        strings. Return the succeeded canonical-key→codepoint moves.
        """
        if self._layout is None:
            return {}
        font_cps = {cp for cp in self._gen.font.getBestCmap()} if self._gen is not None and self._gen.font else None
        used = set(self._layout.effective_map().values())
        moved: dict[str, int] = {}
        for thai_key in thai_keys:
            canonical = canonical_cluster_key(thai_key)
            if canonical is None:
                logger.warning("Skipping relocation of illegal key %r", thai_key)
                continue
            try:
                target = find_relocation_target(canonical_tail_start(self._layout.base), used, font_cps)
            except RuntimeError:
                logger.error("Ran out of free slots relocating %r (%d key(s) already moved)", canonical, len(moved))
                break
            used.add(chr(target))
            logger.debug("Relocated %r to U+%04X", canonical, target)
            moved[canonical] = target
        if not moved:
            return {}
        pins: list[RelocatePin] = []
        for thai_key, code in moved.items():
            cluster = try_key(thai_key)
            if cluster is None:
                logger.warning("Skipping relocation of illegal key %r", thai_key)
                continue
            pins.append(RelocatePin(cluster=cluster, codepoint=code))
        self.resolve_commands(pins, label=f"Relocate {len(moved)} key(s)")
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
        return find_conflicts(self._layout.effective_map(), self.pua_occupants(), approved=self.allowed_locked())

    def apply_manual_edits(self, new_map: dict[str, str]) -> dict[str, str]:
        """Fold hand-edited mapping values into relocation deltas and return the updated map.

        Only values differing from the current effective map are recorded; anything
        else is untouched input, not intent. An explicit placement is always kept —
        even when it equals the canonical codepoint — so the record of intent
        survives later rebases instead of being popped.
        """
        if self._layout is None:
            raise RuntimeError("Cannot apply manual edits before loading a layout.")
        self._session.execute("Edit PUA mapping", lambda: self._session.layout.apply_edits(new_map))
        return self._persist_layout()

    def _persist_layout(self) -> dict[str, str]:
        """Write layout state and the materialized map cache; return the effective map."""
        if self._layout is None:
            raise RuntimeError("Cannot persist a layout before loading one.")
        save_layout_state(self._layout, self._layout_path)
        mapping = self._layout.effective_map()
        save_pua_map(mapping, self._pua_map_path)
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

    def display_extents(self) -> tuple[float, float]:
        """Return the font's (ascent, descent) line box in font units for uniform glyph scaling."""
        return self._workspace.display_extents()

    def render_glyph(self, codepoint: int, path: PathLike, spec: CompositeSpec | None = None) -> GlyphRender:
        """Draw a codepoint's installed glyph into `path` and return its metrics.

        When `spec` is provided, the result carries per-component bounding boxes.
        """
        return self._renderer.render_glyph(codepoint, path, spec)

    def render_composite_path(
        self, spec: CompositeSpec, settings: PlacementSettings, path: PathLike
    ) -> GlyphRender | None:
        """Preview a composed spec into `path` without modifying the font.

        Return `None` when the consonant glyph is missing from the font.
        """
        return self._renderer.render_composite_path(spec, settings, path)

    def regenerate_composite(
        self, spec: CompositeSpec, settings: PlacementSettings, path: PathLike | None
    ) -> GlyphRender:
        """Rebuild the composite at its PUA codepoint and render the current occupant.

        The returned render carries `install_status` so callers can distinguish a
        real install from a skip that left the slot untouched.
        """
        return self._renderer.regenerate_composite(spec, settings, path, allowed_locked=self.allowed_locked())

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
        return self._renderer.regenerate_all(settings, pua_map, self.allowed_locked(), progress)

    def save_font(
        self,
        output_path: str | Path | None,
        settings: PlacementSettings,
        pua_map: dict[str, str],
        progress: Callable[[int, int], None] | None = None,
    ) -> str:
        """Rebuild all composites and write the font to `output_path`."""
        gen = self._workspace.generator
        if gen is None or gen.font is None:
            raise RuntimeError("Cannot save: no font loaded.")
        target = str(output_path) if output_path is not None else self._workspace.output_path
        if target is None:
            raise RuntimeError("Cannot save: no output path available.")
        results = self.regenerate_all(settings, pua_map, progress=progress)
        locked = sum(1 for result in results if result.status is InstallStatus.SKIPPED_LOCKED)
        if locked:
            logger.warning("Saved font keeps %d locked PUA slot(s) untouched (unrecognized content)", locked)
        gen.font.save(target)
        self._workspace.output_path = target
        logger.info("Saved generated font to %s", target)
        return target

    def default_profile_path(self) -> Path | None:
        """Return the suggested `<stem>.json` path under the profiles dir, or `None` before a load."""
        font_path = self._workspace.font_path
        if font_path is None:
            return None
        return Path(self._profiles_dir) / f"{font_path.stem}.json"

    def load_profile(self, path: str | Path) -> PlacementSettings:
        """Read placement settings from `path`, falling back to defaults on unreadable content.

        Unsupported profile versions raise `SettingsError` instead of returning defaults.
        """
        settings = load_placement_settings(path)
        logger.info("Loaded profile %s", path)
        return settings

    def save_profile(self, path: str | Path, settings: PlacementSettings) -> Path:
        """Write `settings` to `path` as JSON, stamping the live font's identity first.

        The stamp lets a later font open verify the profile belongs to it before
        auto-loading; the live settings object is left untouched.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        save_placement_settings(self._stamped_for_save(settings), target)
        return target

    def _stamped_for_save(self, settings: PlacementSettings) -> PlacementSettings:
        """Copy `settings` with the live font's identity stamped into its metadata."""
        family, units = self._live_font_identity()
        if family is None and units is None:
            return settings
        font = self._workspace.font
        full_name: str | None = None
        if font is not None:
            try:
                name_table = font["name"]
            except KeyError:
                name_table = None
            if name_table is not None:
                full_name = name_table.getDebugName(4) or family
        return settings.with_metadata(Metadata(font_name=full_name, family_name=family, units_per_em=units))

    def find_substitutions(self) -> dict[str, list[GlyphSubstitution]]:
        """Return the per-category GSUB substitution catalog for the live font."""
        font = self._workspace.font
        if font is None:
            return {}
        return find_glyph_substitutions(font)

    def close(self) -> None:
        """Close the underlying `TTFont` if one is open; safe to call repeatedly.

        Only font ownership is released — the layout configuration, which is
        independent of the loaded font, is left in place. Approvals for the
        closed session are garbage-collected from memory.
        """
        self._workspace.close()
        self._profiles_dir = str(self._workspace.root.profiles_dir)
        if self._layout is not None:
            self._layout.gc_approvals(frozenset())
        self._session.clear_history()
