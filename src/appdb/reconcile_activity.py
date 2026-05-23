"""The indexer's reconcile-cycle activity log — ``reconcile_activity``.

An append-only record of every incremental-sync and deletion-sweep cycle the
indexer runs, so the Index dashboard can show "Recent activity"
(web-redesign spec §5, Wave 6).

This log lives in ``app.db``, not ``index.db``, for two reasons: ``index.db``
keeps only the *latest* reconcile timestamp (a single overwritten value, no
history), and the destructive "Rebuild" action deletes ``index.db`` outright
— the operations history must survive that.

The indexer calls :func:`record_cycle` at the end of each cycle; the search
server calls :func:`read_recent` to render the dashboard. The per-cycle
count maps (``SyncReport`` / ``SweepReport``) are passed as a plain
``dict[str, int]`` and stored as a JSON string — this module owns the
(de)serialisation so callers always see typed counts.

Allowed deps: sqlite3, structlog, json. Forbidden: store, search, daemon
packages, FastAPI, common.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Literal

import structlog

log = structlog.get_logger(__name__)

#: The two kinds of reconcile cycle the indexer runs.
CycleKind = Literal["sync", "sweep"]


@dataclass(frozen=True, slots=True)
class ReconcileCycle:
    """One recorded reconcile or sweep cycle.

    Attributes:
        id: The row's autoincrement id — also its append order.
        kind: ``sync`` (an incremental sync) or ``sweep`` (a deletion sweep).
        started_at: ISO-8601 UTC timestamp the cycle began.
        finished_at: ISO-8601 UTC timestamp the cycle ended.
        ok: True when the cycle completed without aborting or erroring.
        summary: The cycle's count map — the ``SyncReport`` /
            ``SweepReport`` fields, e.g. ``{"indexed": 3, "failed": 0}``.
        detail: A short human one-liner describing the cycle's outcome.
    """

    id: int
    kind: CycleKind
    started_at: str
    finished_at: str
    ok: bool
    summary: dict[str, int]
    detail: str


def record_cycle(
    conn: sqlite3.Connection,
    *,
    kind: CycleKind,
    started_at: str,
    finished_at: str,
    ok: bool,
    summary: dict[str, int],
    detail: str,
) -> None:
    """Append one reconcile/sweep cycle to the activity log, then commit.

    Args:
        conn: An open, migrated ``app.db`` connection.
        kind: ``sync`` or ``sweep``.
        started_at: ISO-8601 UTC timestamp the cycle began.
        finished_at: ISO-8601 UTC timestamp the cycle ended.
        ok: Whether the cycle completed without aborting or erroring.
        summary: The cycle's count map; stored as a JSON object.
        detail: A short human one-liner.
    """
    conn.execute(
        "INSERT INTO reconcile_activity "
        "(kind, started_at, finished_at, ok, summary, detail) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            kind,
            started_at,
            finished_at,
            1 if ok else 0,
            json.dumps(summary),
            detail,
        ),
    )
    conn.commit()


def _parse_summary(raw: str) -> dict[str, int]:
    """Decode a stored summary JSON string into a count map.

    A row whose summary is somehow not a JSON object decodes to an empty
    map rather than raising — a malformed history entry must not break the
    whole dashboard read.
    """
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {str(k): int(v) for k, v in decoded.items()}


def read_recent(conn: sqlite3.Connection, *, limit: int) -> list[ReconcileCycle]:
    """Return the most recent reconcile/sweep cycles, newest first.

    Args:
        conn: An open ``app.db`` connection.
        limit: The maximum number of rows to return.

    Returns:
        Up to *limit* :class:`ReconcileCycle` rows, ordered newest-first by
        insertion order (the ``id`` primary key). Empty when nothing has
        been recorded yet.
    """
    rows = conn.execute(
        "SELECT id, kind, started_at, finished_at, ok, summary, detail "
        "FROM reconcile_activity ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        ReconcileCycle(
            id=row["id"],
            kind=row["kind"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            ok=bool(row["ok"]),
            summary=_parse_summary(row["summary"]),
            detail=row["detail"],
        )
        for row in rows
    ]
