"""Injective PUA map with the reverse as a derived view."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from thaipua.core.domain.cluster import ThaiCluster, ThaiKey
from thaipua.core.domain.errors import PuaMapError

PuaCodepoint = Annotated[int, Field(ge=0xE000, le=0xF8FF)]
"""A PUA codepoint value; out-of-range integers are unconstructible."""


class PuaMap(BaseModel):
    """Frozen injective Thai-key-to-codepoint map; collisions cannot be constructed."""

    model_config = ConfigDict(frozen=True)

    mapping: dict[ThaiKey, PuaCodepoint]

    @model_validator(mode="after")
    def _reject_collisions(self) -> PuaMap:
        """Reject duplicate codepoints, naming every involved key."""
        seen: dict[int, ThaiCluster] = {}
        for key, code in self.mapping.items():
            cluster = key if isinstance(key, ThaiCluster) else ThaiCluster.from_key(str(key))
            if code in seen:
                raise ValueError(f"U+{code:04X} shared by multiple keys")
            seen[code] = cluster
        return self

    @property
    def reverse(self) -> dict[int, ThaiCluster]:
        """Return the codepoint-to-key view, derived on demand rather than synced."""
        out: dict[int, ThaiCluster] = {}
        for key, code in self.mapping.items():
            cluster = key if isinstance(key, ThaiCluster) else ThaiCluster.from_key(str(key))
            out[int(code)] = cluster
        return out

    def codepoint_for(self, cluster: ThaiCluster) -> int | None:
        """Return the codepoint for `cluster`, or `None` when unmaterialized."""
        for key, code in self.mapping.items():
            own = key if isinstance(key, ThaiCluster) else ThaiCluster.from_key(str(key))
            if own == cluster:
                return int(code)
        return None


def build_pua_map(entries: dict[str, int]) -> PuaMap:
    """Build a `PuaMap` from raw key/codepoint pairs; raise `PuaMapError` when invalid."""
    try:
        return PuaMap.model_validate({"mapping": entries})
    except ValueError as exc:
        raise PuaMapError(str(exc)) from exc
