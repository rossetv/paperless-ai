"""Daemon heartbeat state in the application database — ``daemon_status``.

Each of the four daemons (ocr, classifier, indexer, search) upserts a
heartbeat row into the ``daemon_status`` table on every work cycle via
:func:`record_heartbeat`. The search server reads every row via
:func:`read_statuses` to render the Index dashboard (web-redesign spec §5,
Wave 6).

The dashboard's running/idle/stopped *state* is **not stored** — it is
derived here, at read time, from how recently the daemon last wrote:

- **stopped** — the last heartbeat is older than the staleness window. The
  process is gone; whatever it last claimed to be doing is irrelevant. This
  is the whole point of deriving rather than storing: a crashed daemon
  cannot write ``stopped``, so a stored state would lie forever.
- **idle** — a fresh heartbeat whose ``detail`` is the literal ``"idle"``.
- **running** — a fresh heartbeat with any other ``detail``.

The activity signal therefore travels inside the ``detail`` string the
daemon writes: a daemon with no work writes ``detail="idle"``; a working
daemon writes a real one-liner.

Allowed deps: sqlite3, structlog, datetime. Forbidden: store, search, daemon
packages, FastAPI, common (this module sits below common in the import
graph).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import structlog

from appdb.connection import utc_now_iso

log = structlog.get_logger(__name__)

# The default heartbeat-staleness window, in seconds. A daemon whose last
# heartbeat is older than this is reported "stopped". It is generously larger
# than any daemon's poll/cycle interval so a merely-busy daemon between
# heartbeats is never mistaken for a dead one; the daemons heartbeat at least
# this often even when idle (see common.heartbeat / the daemon wiring).
DEFAULT_STALE_AFTER_SECONDS: int = 90

# The detail string a daemon writes when it has no work. read_statuses maps a
# fresh heartbeat carrying exactly this string to the "idle" state.
IDLE_DETAIL: str = "idle"

#: The three derived dashboard states.
DaemonState = Literal["running", "idle", "stopped"]


@dataclass(frozen=True, slots=True)
class DaemonStatus:
    """One daemon's heartbeat row plus its derived dashboard state.

    Attributes:
        name: The daemon name — ocr / classifier / indexer / search.
        state: The derived state — running / idle / stopped (see the module
            docstring). Not a stored column; computed by :func:`read_statuses`.
        detail: The short human string the daemon last wrote.
        processed_count: The daemon's monotonic throughput counter.
        last_heartbeat: ISO-8601 UTC timestamp of the daemon's last write.
    """

    name: str
    state: DaemonState
    detail: str
    processed_count: int
    last_heartbeat: str


def record_heartbeat(
    conn: sqlite3.Connection,
    *,
    name: str,
    detail: str,
    processed_count: int,
) -> None:
    """Insert or update one daemon's heartbeat row, then commit.

    Upserts on the ``name`` primary key — calling it again for the same
    daemon overwrites the row rather than failing. ``last_heartbeat`` and
    ``updated_at`` are both stamped with the current UTC time; the freshness
    of ``last_heartbeat`` is what :func:`read_statuses` derives state from.

    Args:
        conn: An open, migrated ``app.db`` connection.
        name: The daemon name (ocr / classifier / indexer / search).
        detail: A short human string — ``"idle"`` when the daemon has no
            work, otherwise a one-liner describing the current activity.
        processed_count: The daemon's monotonic throughput counter.
    """
    now = utc_now_iso()
    with conn:
        conn.execute(
            "INSERT INTO daemon_status "
            "(name, detail, processed_count, last_heartbeat, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "detail = excluded.detail, "
            "processed_count = excluded.processed_count, "
            "last_heartbeat = excluded.last_heartbeat, "
            "updated_at = excluded.updated_at",
            (name, detail, processed_count, now, now),
        )


def _derive_state(
    *, last_heartbeat: str, detail: str, now: datetime, stale_after: int
) -> DaemonState:
    """Derive the dashboard state from a row's heartbeat recency and detail.

    An unparseable ``last_heartbeat`` is treated as stale → ``stopped``: a
    row we cannot date is one we cannot trust is fresh.
    """
    try:
        beat = datetime.fromisoformat(last_heartbeat)
    except ValueError:
        return "stopped"
    if beat.tzinfo is None:
        beat = beat.replace(tzinfo=timezone.utc)
    age_seconds = (now - beat).total_seconds()
    if age_seconds > stale_after:
        return "stopped"
    if detail.strip() == IDLE_DETAIL:
        return "idle"
    return "running"


def read_statuses(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> list[DaemonStatus]:
    """Return every daemon's heartbeat row with its derived state.

    Args:
        conn: An open ``app.db`` connection.
        now: The reference time for the staleness check. Defaults to the
            current UTC time; tests inject a fixed value.
        stale_after_seconds: A heartbeat older than this many seconds makes
            the daemon ``stopped``.

    Returns:
        A list of :class:`DaemonStatus`, one per row present in the table,
        ordered by daemon name. A daemon that has never written a row simply
        does not appear — the caller (the Index service) fills missing
        daemons in as ``stopped``.
    """
    reference = now if now is not None else datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT name, detail, processed_count, last_heartbeat "
        "FROM daemon_status ORDER BY name"
    ).fetchall()
    return [
        DaemonStatus(
            name=row["name"],
            state=_derive_state(
                last_heartbeat=row["last_heartbeat"],
                detail=row["detail"],
                now=reference,
                stale_after=stale_after_seconds,
            ),
            detail=row["detail"],
            processed_count=row["processed_count"],
            last_heartbeat=row["last_heartbeat"],
        )
        for row in rows
    ]
