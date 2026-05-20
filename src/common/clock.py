"""Wall-clock and timestamp helpers shared across the daemons and the store.

A single home for "now" and for Paperless-timestamp normalisation, so that
timestamp formatting is consistent everywhere the codebase records or compares
a time — the store's ``indexed_at`` columns, the indexer's reconciliation meta
keys, and the document-metadata ``created`` / ``modified`` fields all go
through this module.

The wall clock is read directly in :func:`utc_now_iso` rather than injected:
the call sites that use it record an audit timestamp as a side effect, never
branch on it, so there is nothing to make deterministic.  Tests that need a
fixed time patch :func:`utc_now_iso` at its single definition site.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Return the current UTC time as a normalised ISO-8601 string.

    The returned string is timezone-aware (it carries the ``+00:00`` offset),
    so values produced here sort and compare correctly against one another.
    """
    return datetime.now(timezone.utc).isoformat()


def parse_paperless_timestamp(value: str) -> datetime | None:
    """Parse a Paperless date or datetime string into a UTC-aware ``datetime``.

    Paperless-ngx returns dates in two shapes: a bare ``"YYYY-MM-DD"`` date and
    a full ISO-8601 datetime that may or may not carry a timezone offset.  This
    is the single normaliser for both: a naive value is assumed to be UTC
    (Paperless stores UTC), an offset-aware value is converted to UTC.

    Args:
        value: A Paperless ``created`` / ``modified`` field value.

    Returns:
        The value as a UTC-aware ``datetime``, or ``None`` when *value* is not
        a timestamp :func:`datetime.fromisoformat` accepts — the caller decides
        how to treat an unparseable value (the store-boundary normaliser keeps
        it verbatim; the watermark advance skips it).
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalise_paperless_timestamp(value: str | None) -> str | None:
    """Normalise a Paperless date/datetime string to a UTC ISO-8601 string.

    The store compares dates lexicographically, so every date crossing the
    store boundary must first be normalised to UTC ISO-8601 (SPEC §4.1).  This
    wraps :func:`parse_paperless_timestamp` and re-serialises.

    Handles:

    - ``None`` → ``None``.
    - A parseable date or datetime → its UTC ISO-8601 form.
    - An unparseable value → returned verbatim; the store persists it as-is
      rather than dropping the field.  An unparseable Paperless timestamp is an
      upstream anomaly the caller is expected to log.
    """
    if value is None:
        return None
    parsed = parse_paperless_timestamp(value)
    if parsed is None:
        return value
    return parsed.isoformat()
