"""Per-font placement-profile resolution.

A profile is a JSON file in the same shape as a `PlacementSettings` payload (see
`thaipua.core.fonttools.settings`), resolved against the font being generated rather
than supplied as a single shared file. For an input font at <...>/<stem>.ttf, tiers are
checked in priority order:

1. <profiles_dir>/<stem>.json
2. <profiles_dir>/<family>.json, where <family> is the first hyphen-separated segment
   of <stem>
3. <profiles_dir>/default.json
4. In-source empty defaults (`default_placement_settings`)

The first tier whose file exists is used. A missing file at any tier is not treated as
an error. An existing but malformed profile falls back to `load_placement_settings`'s
own default behavior.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from thaipua.core.constants import DEFAULT_PROFILE_FILE_NAME, DEFAULT_PROFILES_DIR
from thaipua.core.fonttools.settings import PlacementSettings, default_placement_settings, load_placement_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ResolvedProfile:
    """The outcome of a per-font placement-profile lookup.

    Attributes:
        source: The profile file selected by the tiered lookup — the file the deltas
            were loaded from when it parsed cleanly, or the matched-but-unreadable file
            when `load_placement_settings` fell back to the in-source defaults. `None`
            when no profile file matched.
    """

    settings: PlacementSettings
    source: Path | None


def resolve_settings_profile(font_path: str | Path, *, profiles_dir: str | Path | None) -> ResolvedProfile:
    """Resolve the placement profile for `font_path` via the tiered lookup.

    Returns:
        A `ResolvedProfile`. `source` stays set even when the matched file was
        unreadable (`settings` then holds the in-source defaults) and is `None` only
        when no tier matched.
    """
    base_dir = Path(profiles_dir) if profiles_dir is not None else Path(DEFAULT_PROFILES_DIR)
    stem = Path(font_path).stem
    family = _extract_family(stem)
    candidates = [base_dir / f"{stem}.json", base_dir / f"{family}.json", base_dir / DEFAULT_PROFILE_FILE_NAME]
    for candidate in candidates:
        if not candidate.is_file():
            logger.debug("Profile tier miss: %s", candidate)
            continue
        logger.info("Profile matched: %s", candidate)
        return ResolvedProfile(settings=load_placement_settings(candidate), source=candidate)
    logger.info("No profile found under %s for font '%s'; using in-source defaults", base_dir, stem)
    return ResolvedProfile(settings=default_placement_settings(), source=None)


def _extract_family(stem: str) -> str:
    """Return the font-family segment of a font file stem.

    A stem with a hyphen (e.g. Sarabun-Regular) yields the segment before the first
    hyphen (Sarabun). A stem without one is returned unchanged.
    """
    if "-" in stem:
        return stem.split("-", 1)[0]
    return stem
