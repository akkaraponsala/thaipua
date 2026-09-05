"""Disk and in-memory `JsonStore` implementations."""

import copy
import json
from pathlib import Path
from typing import Any

from thaipua.core.store.ports import JsonStore


class DiskJsonStore(JsonStore):
    """Filesystem `JsonStore`, encoding documents as UTF-8 JSON with 4-space indent."""

    def load(self, path: str | Path) -> Any:
        """Read and decode a document; `FileNotFoundError` when absent, `ValueError` when corrupt."""
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def save(self, path: str | Path, payload: Any) -> None:
        """Encode a document, creating parent directories first."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")


class MemoryJsonStore(JsonStore):
    """In-memory `JsonStore` for tests; nothing touches the filesystem."""

    def __init__(self) -> None:
        """Start with an empty document table."""
        self._documents: dict[str, Any] = {}

    def load(self, path: str | Path) -> Any:
        """Return a copy of the stored document; raise `FileNotFoundError` when absent."""
        try:
            return copy.deepcopy(self._documents[str(path)])
        except KeyError:
            raise FileNotFoundError(f"No such document: {path}") from None

    def save(self, path: str | Path, payload: Any) -> None:
        """Store a JSON-round-tripped copy, rejecting non-serializable payloads."""
        self._documents[str(path)] = json.loads(json.dumps(payload, ensure_ascii=False))
