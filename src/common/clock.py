"""Wall-clock and Paperless-timestamp helpers, so every recorded time is formatted
the same way.

Tests that need a fixed time patch :func:`utc_now_iso`.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``+00:00`` offset."""
    return datetime.now(timezone.utc).isoformat()


def parse_paperless_timestamp(value: str) -> datetime | None:
    """Parse a Paperless date or datetime string into a UTC-aware ``datetime``.

    Paperless returns bare ``YYYY-MM-DD`` dates and ISO-8601 datetimes with or
    without an offset; a naive value is taken as UTC, which Paperless stores.
    Returns ``None`` when the value does not parse.
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

    The store compares dates lexicographically, so every stored date must be
    normalised. An unparseable value is returned verbatim for the caller to log.
    """
    if value is None:
        return None
    parsed = parse_paperless_timestamp(value)
    if parsed is None:
        return value
    return parsed.isoformat()
