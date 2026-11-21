"""Daemon heartbeats in the ``daemon_status`` table.

The running/idle/stopped state is derived at read time, not stored, because a
crashed daemon cannot write ``stopped``:

- **stopped**: the last heartbeat is older than the staleness window.
- **idle**: a fresh heartbeat whose ``detail`` is exactly ``"idle"``.
- **running**: a fresh heartbeat with any other ``detail``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import structlog

from appdb.connection import utc_now_iso

log = structlog.get_logger(__name__)

# A daemon whose last heartbeat is older than this is "stopped". Well above any
# poll interval so a busy daemon between heartbeats is not mistaken for a dead
# one; daemons heartbeat at least this often even when idle.
DEFAULT_STALE_AFTER_SECONDS: int = 90

# The detail a daemon writes when it has no work.
IDLE_DETAIL: str = "idle"

DaemonState = Literal["running", "idle", "stopped"]


@dataclass(frozen=True, slots=True)
class DaemonStatus:
    """One daemon's heartbeat row plus its derived dashboard state.

    ``state`` is derived by :func:`read_statuses`, not a stored column.
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
    """Upsert one daemon's heartbeat row, stamped with the current time.

    *detail* is ``"idle"`` when the daemon has no work, otherwise a one-liner
    describing the current activity.
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


def touch_heartbeat(
    conn: sqlite3.Connection,
    *,
    name: str,
    detail: str,
) -> None:
    """Refresh a daemon's detail and freshness without touching its count.

    For a secondary writer (the tag daemons' stall ticker) whose
    :class:`~common.heartbeat.Heartbeat` does not hold the real running total;
    :func:`record_heartbeat` from it would reset ``processed_count`` to zero.
    """
    now = utc_now_iso()
    with conn:
        conn.execute(
            "INSERT INTO daemon_status "
            "(name, detail, processed_count, last_heartbeat, updated_at) "
            "VALUES (?, ?, 0, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "detail = excluded.detail, "
            "last_heartbeat = excluded.last_heartbeat, "
            "updated_at = excluded.updated_at",
            (name, detail, now, now),
        )


def _derive_state(
    *, last_heartbeat: str, detail: str, now: datetime, stale_after_seconds: int
) -> DaemonState:
    """Derive the dashboard state from a row's heartbeat recency and detail.

    An unparseable ``last_heartbeat`` counts as stale: a row we cannot date
    cannot be trusted as fresh.
    """
    try:
        beat = datetime.fromisoformat(last_heartbeat)
    except ValueError:
        return "stopped"
    if beat.tzinfo is None:
        beat = beat.replace(tzinfo=timezone.utc)
    age_seconds = (now - beat).total_seconds()
    if age_seconds > stale_after_seconds:
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
    """Return every daemon's heartbeat row with its derived state, by name.

    A daemon that has never written a row does not appear; the caller fills it
    in as ``stopped``.
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
                stale_after_seconds=stale_after_seconds,
            ),
            detail=row["detail"],
            processed_count=row["processed_count"],
            last_heartbeat=row["last_heartbeat"],
        )
        for row in rows
    ]
