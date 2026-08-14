"""Shared GSUB lookup-type constants and helpers for the PUA font generator."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

SINGLE_SUBST = 1
ALTERNATE_SUBST = 3
EXTENSION_SUBST = 7


def iter_subtables(lookup: Any, extension_type: int) -> Iterator[tuple[int, Any]]:
    """Yield each subtable of a GSUB/GPOS lookup as (effective_type, subtable).

    An extension lookup wraps its real subtable in an `ExtSubTable`, where the lookup's
    declared `LookupType` equals `extension_type` and the inner `ExtensionLookupType`
    carries the true type. This function unwraps that indirection so callers always
    receive the effective type.
    """
    for st in lookup.SubTable:
        if lookup.LookupType == extension_type:
            yield (st.ExtensionLookupType, st.ExtSubTable)
        else:
            yield (lookup.LookupType, st)
