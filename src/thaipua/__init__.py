"""Thai-to-PUA encoding and composite PUA font generation, with a PySide6 desktop frontend."""

from __future__ import annotations

from typing import Any

from thaipua.core._reexports import APP_EXPORTS, resolve_lazy_export

__version__ = "0.1.5"
__all__ = [
    *APP_EXPORTS,
    "__version__",
]


def __getattr__(name: str) -> Any:
    """Resolve a legacy symbol through the lazy `thaipua.core` package on first use."""
    try:
        return resolve_lazy_export(APP_EXPORTS, globals(), name)
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None


def __dir__() -> list[str]:
    """List every lazily available legacy symbol."""
    return sorted(__all__)
