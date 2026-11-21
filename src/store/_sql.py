"""SQL-construction helpers private to the store."""

from __future__ import annotations


def placeholders(count: int) -> str:
    """Return *count* ``?`` placeholders joined by commas, e.g. ``"?,?,?"``.

    Only the count is interpolated, never a value, so the result cannot carry an
    injection; callers still bind every value as a parameter. ``0`` yields ``""``,
    so callers must guard against an empty id list.
    """
    if count < 0:
        raise ValueError(f"placeholder count must be non-negative, got {count}")
    return ",".join("?" * count)
