"""Wall-clock helpers shared across the daemons and the store.

A single home for "now" so that timestamp formatting is consistent everywhere
the codebase records a time — the store's ``indexed_at`` columns and the
indexer's reconciliation meta keys both go through :func:`utc_now_iso`.

The clock is read directly here rather than injected: the call sites that use
it record an audit timestamp as a side effect, never branch on it, so there is
nothing to make deterministic.  Tests that need a fixed time patch this
function at its single definition site.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Return the current UTC time as a normalised ISO-8601 string.

    The returned string is timezone-aware (it carries the ``+00:00`` offset),
    so values produced here sort and compare correctly against one another.
    """
    return datetime.now(timezone.utc).isoformat()
