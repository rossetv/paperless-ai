"""Reconcile-activity log and heartbeat for the indexer daemon, both in ``app.db``.

Both writes are best-effort: a failure must never crash the indexer. A recorded
cycle's ``ok`` means the cycle completed, not that every document succeeded; only
an aborted sweep is ``ok=False``.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import structlog

from appdb import reconcile_activity
from common.heartbeat import Heartbeat

if TYPE_CHECKING:
    from appdb.reconcile_activity import CycleKind
    from indexer.reconciler import SyncReport
    from indexer.reconciler._sweep import SweepReport

log = structlog.get_logger(__name__)

_DAEMON_NAME = "indexer"

# Errors a best-effort reconcile_activity write swallows. A genuine bug
# (wrong arguments → TypeError) is not in this set and still surfaces.
_ACTIVITY_WRITE_EXCEPTIONS: tuple[type[Exception], ...] = (
    sqlite3.Error,
    OSError,
)


class IndexerActivityRecorder:
    """Records the indexer's reconcile cycles and beats its heartbeat.

    The recorder does not own *conn*; the daemon opens and closes it.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._heartbeat = Heartbeat(name=_DAEMON_NAME, conn=conn)

    def record_sync(
        self,
        report: SyncReport,
        *,
        started_at: str,
        finished_at: str,
    ) -> None:
        """Record one incremental-sync cycle and beat the heartbeat.

        Always ``ok=True``: per-document failures are counted in the summary,
        not treated as a cycle failure.
        """
        summary = {
            "indexed": report.indexed,
            "metadata_only": report.metadata_only,
            "skipped": report.skipped,
            "failed": report.failed,
            "given_up": report.given_up,
        }
        detail = (
            f"indexed {report.indexed}, {report.failed} failed"
            if report.failed
            else f"indexed {report.indexed} document(s)"
        )
        self._record(
            kind="sync",
            started_at=started_at,
            finished_at=finished_at,
            ok=True,
            summary=summary,
            detail=detail,
        )
        self._heartbeat.beat(detail=detail)

    def record_sweep(
        self,
        report: SweepReport,
        *,
        started_at: str,
        finished_at: str,
    ) -> None:
        """Record one deletion-sweep cycle and beat the heartbeat.

        ``ok=False`` only when the sweep aborted (its Paperless enumeration
        failed, so it pruned nothing).
        """
        summary = {
            "pruned": report.pruned,
            "aborted": 1 if report.aborted else 0,
            "candidates": report.candidates,
        }
        detail = (
            "sweep aborted: Paperless enumeration failed"
            if report.aborted
            else f"pruned {report.pruned} deleted document(s)"
        )
        self._record(
            kind="sweep",
            started_at=started_at,
            finished_at=finished_at,
            ok=not report.aborted,
            summary=summary,
            detail=detail,
        )
        self._heartbeat.beat(detail=detail)

    def record_rebuild(self, *, started_at: str, finished_at: str) -> None:
        """Record an index rebuild and beat the heartbeat.

        The rebuild only wipes the index; the re-index happens in the sync that
        follows, so the row is recorded as ``kind="sync"``.
        """
        detail = "index rebuilt — re-indexing the whole archive"
        self._record(
            kind="sync",
            started_at=started_at,
            finished_at=finished_at,
            ok=True,
            summary={"rebuilt": 1},
            detail=detail,
        )
        self._heartbeat.beat(detail=detail)

    def beat_idle(self) -> None:
        """Beat an idle heartbeat while the loop is between cycles."""
        self._heartbeat.beat_idle()

    def _record(
        self,
        *,
        kind: CycleKind,
        started_at: str,
        finished_at: str,
        ok: bool,
        summary: dict[str, int],
        detail: str,
    ) -> None:
        """Append a reconcile_activity row — best-effort; never raises."""
        try:
            reconcile_activity.record_cycle(
                self._conn,
                kind=kind,
                started_at=started_at,
                finished_at=finished_at,
                ok=ok,
                summary=summary,
                detail=detail,
            )
        except _ACTIVITY_WRITE_EXCEPTIONS as exc:
            # Only the dashboard's activity history misses this row; the index
            # itself is unaffected.
            log.warning(
                "indexer.activity_write_failed",
                kind=kind,
                error=str(exc),
                error_type=type(exc).__name__,
            )
