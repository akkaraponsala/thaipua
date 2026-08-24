"""Resolve per-font placement profiles through a tiered directory lookup."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from thaipua.core.fonttools.settings import (
    PlacementSettings,
    default_placement_settings,
    load_placement_settings,
    settings_to_dict,
)
from thaipua.core.paths import DEFAULT_PROFILE_FILE_NAME, DEFAULT_PROFILES_DIR

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ResolvedProfile:
    """Profile outcome: the resolved settings and the matched file, when any."""

    settings: PlacementSettings
    source: Path | None


def resolve_settings_profile(font_path: str | Path, *, profiles_dir: str | Path | None) -> ResolvedProfile:
    """Resolve the highest-priority profile for `font_path`, falling back to in-source defaults.

    Tiers check `<stem>.json`, then `<family>.json`, then `default.json`; `source` is
    set even when a matched file was unreadable.
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


def seed_default_profile(profiles_dir: str | Path | None = None) -> Path:
    """Write the starter `default.json` profile when missing, returning its path."""
    base_dir = Path(profiles_dir) if profiles_dir is not None else Path(DEFAULT_PROFILES_DIR)
    target = base_dir / DEFAULT_PROFILE_FILE_NAME
    if target.is_file():
        return target
    payload = settings_to_dict(default_placement_settings())
    base_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
    logger.info("Seeded default profile at %s", target)
    return target


def _extract_family(stem: str) -> str:
    """Return the family segment of a font-file stem, stripping any style suffix."""
    if "-" in stem:
        return stem.split("-", 1)[0]
    return stem
