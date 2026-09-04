"""GUI-free backend for Thai-to-PUA encoding and composite PUA font generation."""

from __future__ import annotations

from typing import Any

from thaipua.core._reexports import CORE_EXPORTS, resolve_lazy_export

__all__ = list(CORE_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve a legacy symbol from its owning submodule on first use, then cache it."""
    try:
        return resolve_lazy_export(CORE_EXPORTS, globals(), name)
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None


def __dir__() -> list[str]:
    """List every lazily available legacy symbol."""
    return sorted(__all__)
