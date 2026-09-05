"""A4: installer gate, validator, and conflict scan answer from the single policy table."""

import pytest
from conftest import FakeGlyf, FakeGlyph

from thaipua.core.domain.cluster import try_key
from thaipua.core.domain.errors import LayoutError
from thaipua.core.domain.layout import fresh_engine
from thaipua.core.domain.resolution import OverrideApproval, OverrideRevocation, RelocatePin, resolve
from thaipua.core.domain.slots import Decision, Severity, SlotOwnership, decide, is_conflict, severity
from thaipua.core.font.composer import _INSTALL_STATUS_BY_DECISION
from thaipua.core.font.map_validation import IssueSeverity, PuaSlotContext, validate_pua_map
from thaipua.core.font.occupancy import PuaOccupant
from thaipua.core.layout import find_conflicts

CP = 0xE001


def _context(ownership: SlotOwnership) -> PuaSlotContext:
    """Build a slot context classifying `CP` with `ownership`."""
    if ownership is SlotOwnership.FREE:
        return PuaSlotContext(cmap={}, glyf=None)
    if ownership is SlotOwnership.OWNED:
        return PuaSlotContext(cmap={CP: "thaipua_E001"}, glyf=None)
    if ownership is SlotOwnership.REPLACEABLE:
        return PuaSlotContext(cmap={CP: "foreign"}, glyf=FakeGlyf({"foreign": FakeGlyph(composite=True)}))
    return PuaSlotContext(cmap={CP: "logo"}, glyf=FakeGlyf({"logo": FakeGlyph(composite=False)}))


def test_install_status_covers_every_proceeding_decision() -> None:
    assert set(_INSTALL_STATUS_BY_DECISION) == set(Decision) - {Decision.SKIP_LOCKED}


def test_decide_routes_locked_and_foreign_slots() -> None:
    assert decide(SlotOwnership.LOCKED, approved=False) is Decision.SKIP_LOCKED
    assert decide(SlotOwnership.LOCKED, approved=True) is Decision.OVERRIDE_LOCKED
    assert decide(SlotOwnership.REPLACEABLE, approved=True) is Decision.REPLACE_FOREIGN


def test_validator_and_conflict_scan_agree_with_the_policy_table() -> None:
    for ownership in SlotOwnership:
        for approved in (False, True):
            allowed = frozenset({CP}) if approved else frozenset()
            issues = validate_pua_map({"ก": chr(CP)}, _context(ownership), allowed_locked=allowed)
            conflicts = find_conflicts(
                {"ก": chr(CP)},
                [PuaOccupant(CP, "occupant", ownership, "detail")],
                approved=allowed,
            )
            expected_severity = severity(ownership, approved=approved)
            if expected_severity is Severity.OK:
                assert issues == []
            else:
                assert len(issues) == 1
                assert issues[0].severity is (
                    IssueSeverity.WARNING if expected_severity is Severity.WARNING else IssueSeverity.ERROR
                )
            assert (len(conflicts) == 1) == is_conflict(ownership, approved=approved)


def test_resolve_approves_and_revokes_per_session() -> None:
    engine = fresh_engine()
    approved = resolve(engine, OverrideApproval(font_id="font-A", codepoint=CP))
    assert approved.allowed_locked("font-A") == frozenset({CP})
    assert approved.allowed_locked("font-B") == frozenset()
    assert engine.allowed_locked("font-A") == frozenset()
    revoked = resolve(approved, OverrideRevocation(font_id="font-A", codepoint=CP))
    assert revoked.allowed_locked("font-A") == frozenset()
    assert "font-A" not in revoked.approvals


def test_resolve_pins_in_range_and_rejects_out_of_range() -> None:
    cluster = try_key("ก่")
    assert cluster is not None
    pinned = resolve(fresh_engine(), RelocatePin(cluster=cluster, codepoint=0xE900))
    assert pinned.map["ก่"] == 0xE900
    with pytest.raises(LayoutError):
        resolve(fresh_engine(), RelocatePin(cluster=cluster, codepoint=0x1000))
