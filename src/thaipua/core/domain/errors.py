"""Error hierarchy for the domain layer."""

from __future__ import annotations


class ThaiPuaError(Exception):
    """Base error for all domain failures."""


class ClusterError(ThaiPuaError):
    """Raised when a Thai key cannot form a legal cluster."""


class GridError(ThaiPuaError):
    """Raised when grid geometry is inconsistent."""


class PuaMapError(ThaiPuaError):
    """Raised when a PUA map violates injectivity or range invariants."""


class LayoutError(ThaiPuaError):
    """Raised when a layout document has an unsupported version or bad pin."""


class SettingsError(ThaiPuaError):
    """Raised when a settings document has an unsupported version or bad value."""
