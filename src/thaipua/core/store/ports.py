"""Abstract persistence ports; core logic talks to stores, never to disk directly."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class JsonStore(Protocol):
    """JSON document storage behind two verbs; missing documents raise `FileNotFoundError`."""

    def load(self, path: str | Path) -> Any:
        """Return the decoded document; raise `FileNotFoundError` when absent."""
        ...

    def save(self, path: str | Path, payload: Any) -> None:
        """Persist an encodable document, creating parent locations as needed."""
        ...
