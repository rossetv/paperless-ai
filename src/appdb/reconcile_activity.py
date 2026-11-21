"""The indexer's append-only log of sync and sweep cycles, for the dashboard.

Kept in ``app.db`` rather than ``index.db`` because "Rebuild" deletes
``index.db`` and the history must survive it.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Literal

import structlog

log = structlog.get_logger(__name__)

CycleKind = Literal["sync", "sweep"]

# The dashboard shows ~50 rows; a generous cap keeps support history while
# bounding the table over a months-long lifetime.
_ACTIVITY_CAP = 500


@dataclass(frozen=True, slots=True)
class ReconcileCycle:
    """One recorded reconcile or sweep cycle.

    Attributes:
        id: Autoincrement id, which is also the append order.
        ok: True when the cycle completed without aborting or erroring.
        summary: The ``SyncReport`` / ``SweepReport`` counts, e.g.
            ``{"indexed": 3, "failed": 0}``.
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
    """Append one cycle to the activity log, trim it to the cap, and commit."""
    with conn:
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
        # id is monotonic, so one indexed DELETE is cheaper than a NOT IN/LIMIT
        # subquery.
        conn.execute(
            "DELETE FROM reconcile_activity "
            "WHERE id <= (SELECT MAX(id) FROM reconcile_activity) - ?",
            (_ACTIVITY_CAP,),
        )


def _parse_summary(raw: str) -> dict[str, int]:
    """Decode a stored summary JSON string into a count map.

    Never raises: a malformed history entry must not break the dashboard read.
    Undecodable blobs yield ``{}`` and non-integer values are skipped.
    """
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # A corrupt blob is a write-side anomaly worth surfacing. Counts carry no
        # secret, so logging the raw value is safe.
        log.warning("appdb.reconcile_activity.summary_undecodable", raw=raw)
        return {}
    if not isinstance(decoded, dict):
        log.warning("appdb.reconcile_activity.summary_not_object", raw=raw)
        return {}
    result: dict[str, int] = {}
    for k, v in decoded.items():
        try:
            result[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return result


def read_recent(conn: sqlite3.Connection, *, limit: int) -> list[ReconcileCycle]:
    """Return up to *limit* recorded cycles, newest first."""
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
