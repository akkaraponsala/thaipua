"""Verified per-font profile auto-load: an identity match applies, everything else falls back to defaults."""

import json
from pathlib import Path

from conftest import SAMPLE_FONT_PATH
from fontTools.ttLib import TTFont

from thaipua.core.domain.settings import (
    ConsonantSettings,
    Metadata,
    Offset,
    PlacementSettings,
    default_placement_settings,
    settings_to_dict,
)
from thaipua.core.fonttools.settings import (
    save_placement_settings,
)
from thaipua.gui.font_service import FontService, ProfileAutoLoad


def _sarabun_identity() -> tuple[str, int]:
    """Read Sarabun's (family name, units-per-em) straight from the font binary."""
    font = TTFont(str(SAMPLE_FONT_PATH))
    try:
        name_table = font["name"]
        family = name_table.getDebugName(16) or name_table.getDebugName(1)
        units = int(font["head"].unitsPerEm)
    finally:
        font.close()
    assert family is not None
    return (family, units)


def _overrides() -> PlacementSettings:
    """Build settings with one tuned offset, unstamped."""
    settings = default_placement_settings()
    settings.consonants[0x0E01] = ConsonantSettings(base_offsets={"tone_mark": Offset(x=3, y=4)})
    return settings


def _open(service: FontService, profiles_dir: Path) -> ProfileAutoLoad:
    """Open the sample font against `profiles_dir`, returning the auto-load outcome."""
    return service.load_font(SAMPLE_FONT_PATH, profiles_dir=profiles_dir)


def test_missing_profile_starts_from_defaults(tmp_path: Path) -> None:
    service = FontService()
    assert _open(service, tmp_path / "profiles") is ProfileAutoLoad.MISSING
    assert settings_to_dict(service.settings) == settings_to_dict(default_placement_settings())
    assert not service.can_undo


def test_stamped_save_roundtrips_through_reopen(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    first = FontService()
    first.load_font(SAMPLE_FONT_PATH, profiles_dir=profiles)
    target = first.save_profile(str(first.default_profile_path()), _overrides())

    second = FontService()
    assert _open(second, profiles) is ProfileAutoLoad.APPLIED
    family, units = _sarabun_identity()
    assert second.settings.consonants == _overrides().consonants
    assert second.settings.metadata.family_name == family
    assert second.settings.metadata.units_per_em == units
    assert not second.can_undo
    assert target.is_file()


def test_legacy_unstamped_profile_is_skipped(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    save_placement_settings(_overrides(), profiles / "Sarabun-Regular.json")

    service = FontService()
    assert _open(service, profiles) is ProfileAutoLoad.LEGACY
    assert settings_to_dict(service.settings) == settings_to_dict(default_placement_settings())


def test_mismatched_family_is_skipped(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    settings = _overrides().with_metadata(
        Metadata(font_name="No Such Font", family_name="No Such Family", units_per_em=2048)
    )
    save_placement_settings(settings, profiles / "Sarabun-Regular.json")

    service = FontService()
    assert _open(service, profiles) is ProfileAutoLoad.MISMATCH
    assert settings_to_dict(service.settings) == settings_to_dict(default_placement_settings())


def test_upm_mismatch_is_skipped(tmp_path: Path) -> None:
    family, _units = _sarabun_identity()
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    settings = _overrides().with_metadata(Metadata(font_name=family, family_name=family, units_per_em=1))
    save_placement_settings(settings, profiles / "Sarabun-Regular.json")

    service = FontService()
    assert _open(service, profiles) is ProfileAutoLoad.MISMATCH
    assert settings_to_dict(service.settings) == settings_to_dict(default_placement_settings())


def test_corrupt_and_unsupported_profiles_fall_back(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    target = profiles / "Sarabun-Regular.json"
    for payload in ("{not json", "[1, 2]", json.dumps({"version": 99})):
        target.write_text(payload, encoding="utf-8")
        service = FontService()
        assert _open(service, profiles) is ProfileAutoLoad.UNREADABLE
        assert settings_to_dict(service.settings) == settings_to_dict(default_placement_settings())


def test_save_stamps_live_font_identity_without_touching_live_settings(tmp_path: Path) -> None:
    family, units = _sarabun_identity()
    service = FontService()
    service.load_font(SAMPLE_FONT_PATH, profiles_dir=tmp_path / "profiles")
    live = _overrides()
    target = service.save_profile(tmp_path / "profiles" / "Sarabun-Regular.json", live)

    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored["metadata"]["family_name"] == family
    assert stored["metadata"]["units_per_em"] == units
    assert live.metadata == Metadata()


def test_save_without_font_leaves_settings_untouched(tmp_path: Path) -> None:
    service = FontService()
    live = _overrides()
    target = service.save_profile(tmp_path / "plain.json", live)
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert "metadata" not in stored
    assert live.metadata == Metadata()


def test_manual_load_still_applies_unconditionally(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    settings = _overrides().with_metadata(
        Metadata(font_name="No Such Font", family_name="No Such Family", units_per_em=2048)
    )
    save_placement_settings(settings, profiles / "foreign.json")

    assert settings_to_dict(FontService().load_profile(profiles / "foreign.json")) == settings_to_dict(settings)
