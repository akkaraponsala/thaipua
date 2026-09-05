"""Single slot-policy source: one table plus an exhaustiveness assertion."""

from enum import StrEnum


class SlotOwnership(StrEnum):
    """Ownership verdict for the glyph currently mapped at a PUA codepoint."""

    FREE = "free"
    OWNED = "owned"
    REPLACEABLE = "replaceable"
    LOCKED = "locked"


class Decision(StrEnum):
    """Operational answer: what the installer should do with the slot."""

    INSTALL = "install"
    REINSTALL_OWNED = "reinstall_owned"
    REPLACE_FOREIGN = "replace_foreign"
    OVERRIDE_LOCKED = "override_locked"
    SKIP_LOCKED = "skip_locked"


class Severity(StrEnum):
    """UI answer: how loudly the slot should be surfaced."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


PolicyKey = tuple[SlotOwnership, bool]
"""`(ownership, approved)`; approval is the per-font-session override bit."""

DECISION: dict[PolicyKey, Decision] = {
    (SlotOwnership.FREE, False): Decision.INSTALL,
    (SlotOwnership.FREE, True): Decision.INSTALL,
    (SlotOwnership.OWNED, False): Decision.REINSTALL_OWNED,
    (SlotOwnership.OWNED, True): Decision.REINSTALL_OWNED,
    (SlotOwnership.REPLACEABLE, False): Decision.REPLACE_FOREIGN,
    (SlotOwnership.REPLACEABLE, True): Decision.REPLACE_FOREIGN,
    (SlotOwnership.LOCKED, False): Decision.SKIP_LOCKED,
    (SlotOwnership.LOCKED, True): Decision.OVERRIDE_LOCKED,
}

SEVERITY: dict[PolicyKey, Severity] = {
    (SlotOwnership.FREE, False): Severity.OK,
    (SlotOwnership.FREE, True): Severity.OK,
    (SlotOwnership.OWNED, False): Severity.OK,
    (SlotOwnership.OWNED, True): Severity.OK,
    (SlotOwnership.REPLACEABLE, False): Severity.WARNING,
    (SlotOwnership.REPLACEABLE, True): Severity.WARNING,
    (SlotOwnership.LOCKED, False): Severity.ERROR,
    (SlotOwnership.LOCKED, True): Severity.WARNING,
}

IS_CONFLICT: dict[PolicyKey, bool] = {
    (SlotOwnership.FREE, False): False,
    (SlotOwnership.FREE, True): False,
    (SlotOwnership.OWNED, False): False,
    (SlotOwnership.OWNED, True): False,
    (SlotOwnership.REPLACEABLE, False): True,
    (SlotOwnership.REPLACEABLE, True): False,
    (SlotOwnership.LOCKED, False): True,
    (SlotOwnership.LOCKED, True): False,
}

_EXPECTED_KEYS: frozenset[PolicyKey] = frozenset(
    (ownership, approved) for ownership in SlotOwnership for approved in (False, True)
)
for _table_name, _table in (("DECISION", DECISION), ("SEVERITY", SEVERITY), ("IS_CONFLICT", IS_CONFLICT)):
    if frozenset(_table) != _EXPECTED_KEYS:
        raise AssertionError(f"{_table_name} must answer every (ownership, approval) pair")


def decide(ownership: SlotOwnership, *, approved: bool) -> Decision:
    """Return the install decision for a slot state."""
    return DECISION[(ownership, approved)]


def severity(ownership: SlotOwnership, *, approved: bool) -> Severity:
    """Return the UI severity for a slot state."""
    return SEVERITY[(ownership, approved)]


def is_conflict(ownership: SlotOwnership, *, approved: bool) -> bool:
    """Return whether a slot state blocks a clean save."""
    return IS_CONFLICT[(ownership, approved)]
