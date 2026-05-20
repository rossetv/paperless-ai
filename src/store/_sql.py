"""SQL-construction helpers private to the store.

The store is the only package that builds SQL (CODE_GUIDELINES.md §9.1), so
this module lives inside ``store/`` and is prefixed ``_`` — it is an internal
helper, not part of the store's public API.

It exists for exactly one job: building the ``?`` placeholder run for the
``IN (...)`` batch query, the single sanctioned dynamic-SQL pattern
(CODE_GUIDELINES.md §9.5).
"""

from __future__ import annotations


def placeholders(count: int) -> str:
    """Return a comma-separated run of *count* SQL ``?`` placeholders.

    For ``count == 3`` this returns ``"?,?,?"`` — ready to splat into an
    ``IN ({...})`` clause.

    rationale: ``IN (...)`` with a dynamic count of placeholders is the only
    sanctioned dynamic-SQL pattern (CODE_GUIDELINES.md §9.5).  Only the count
    of ``?`` characters is interpolated — never any value — so the result can
    never carry an injection.  Every value is still bound through parameter
    substitution by the caller.

    Args:
        count: The number of placeholders required; must be non-negative.
            ``0`` yields an empty string (an ``IN ()`` clause matches nothing,
            so callers guard against an empty id list before reaching here).

    Returns:
        A string of *count* ``?`` characters joined by commas.

    Raises:
        ValueError: If *count* is negative.
    """
    if count < 0:
        raise ValueError(f"placeholder count must be non-negative, got {count}")
    return ",".join("?" * count)
