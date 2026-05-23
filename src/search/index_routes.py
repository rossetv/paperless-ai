"""The Index operations-dashboard ``/api`` router for the search server.

Four endpoints (web-redesign spec §5, Wave 6):

- ``GET  /api/index/status``   — per-daemon status + overall health.
- ``GET  /api/index/activity`` — recent reconcile/sweep cycles.
- ``GET  /api/index/failed``   — documents the indexer has failed to index.
- ``POST /api/index/rebuild``  — the destructive index rebuild.

RBAC (spec §4.3): the three reads require Read-only or above — viewing
operational state is a read capability; the rebuild requires admin — it is
destructive. The dependencies are Wave 1's :mod:`search.deps`.

The handlers are thin: status/health shaping is :mod:`search.index_service`,
``daemon_status`` / ``reconcile_activity`` I/O is :mod:`appdb`, the
failed-document list is the injected :class:`~store.reader.StoreReader`, and
the ``app.db`` connection is opened per request via
:func:`~search.deps.get_app_db` — a ``sqlite3.Connection`` is never shared
across requests.

The rebuild never touches ``index.db`` — the indexer holds an exclusive
flock on it. The handler writes a ``rebuild.request`` sentinel beside the
index file; the indexer consumes it and performs the wipe. This is exactly
the mechanism ``POST /api/reconcile`` uses for ``reconcile.request``.

Allowed deps: fastapi, structlog, pathlib, appdb (daemon_status,
reconcile_activity), common.config, search (deps, wire, index_service),
store, store.reader.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends

from appdb import daemon_status, reconcile_activity
from search.deps import get_app_db, require_admin, require_api_scope
from search.index_service import overall_health, resolve_daemon_statuses
from search.wire import (
    DaemonStatusResponse,
    FailedDocumentResponse,
    IndexActivityResponse,
    IndexFailedResponse,
    IndexStatusResponse,
    RebuildResponse,
    ReconcileCycleResponse,
)

if TYPE_CHECKING:
    from common.config import Settings
    from store.reader import StoreReader

log = structlog.get_logger(__name__)

# How many reconcile-activity rows GET /api/index/activity returns.
_ACTIVITY_LIMIT = 50

# The rebuild sentinel file name — written beside index.db, consumed by the
# indexer's polling loop (web-redesign spec §5, Wave 6).
_REBUILD_SENTINEL_NAME = "rebuild.request"

# The reconcile sentinel file name — touching it wakes the indexer's
# _interruptible_wait immediately so the rebuild sentinel is acted upon
# within the wake-check interval rather than waiting a full RECONCILE_INTERVAL.
_RECONCILE_SENTINEL_NAME = "reconcile.request"


def build_index_router(settings: Settings, store_reader: StoreReader) -> APIRouter:
    """Build the Index dashboard ``/api`` router (web-redesign spec §5).

    Args:
        settings: Application settings — ``INDEX_DB_PATH`` locates where the
            rebuild sentinel is written.
        store_reader: The read-side store, backing the failed-document list.

    Returns:
        A configured :class:`~fastapi.APIRouter`. The three GETs require
        Read-only+, the rebuild POST requires admin.
    """
    router = APIRouter()
    read_access = Depends(require_api_scope)

    @router.get("/api/index/status", dependencies=[read_access])
    async def index_status(
        app_db: sqlite3.Connection = Depends(get_app_db),
    ) -> IndexStatusResponse:
        """Return every daemon's status and the overall health verdict."""
        return _index_status(app_db)

    @router.get("/api/index/activity", dependencies=[read_access])
    async def index_activity(
        app_db: sqlite3.Connection = Depends(get_app_db),
    ) -> IndexActivityResponse:
        """Return the most recent reconcile/sweep cycles."""
        return _index_activity(app_db)

    @router.get("/api/index/failed", dependencies=[read_access])
    async def index_failed() -> IndexFailedResponse:
        """Return the documents the indexer has failed to index."""
        return _index_failed(store_reader)

    @router.post("/api/index/rebuild", dependencies=[Depends(require_admin)])
    async def index_rebuild() -> RebuildResponse:
        """Trigger the destructive index rebuild (admin-only).

        Writes the ``rebuild.request`` sentinel; the indexer consumes it and
        wipes the index. Writes ONLY the sentinel — never ``index.db``.
        """
        return _index_rebuild(settings)

    return router


def _index_status(app_db: sqlite3.Connection) -> IndexStatusResponse:
    """Build the GET /api/index/status payload."""
    rows = daemon_status.read_statuses(app_db)
    resolved = resolve_daemon_statuses(rows)
    return IndexStatusResponse(
        health=overall_health(resolved),
        daemons=[
            DaemonStatusResponse(
                name=s.name,
                state=s.state,
                detail=s.detail,
                processed_count=s.processed_count,
                last_heartbeat=s.last_heartbeat,
            )
            for s in resolved
        ],
    )


def _index_activity(app_db: sqlite3.Connection) -> IndexActivityResponse:
    """Build the GET /api/index/activity payload."""
    cycles = reconcile_activity.read_recent(app_db, limit=_ACTIVITY_LIMIT)
    return IndexActivityResponse(
        cycles=[
            ReconcileCycleResponse(
                id=c.id,
                kind=c.kind,
                started_at=c.started_at,
                finished_at=c.finished_at,
                ok=c.ok,
                summary=c.summary,
                detail=c.detail,
            )
            for c in cycles
        ]
    )


def _index_failed(store_reader: StoreReader) -> IndexFailedResponse:
    """Build the GET /api/index/failed payload.

    A not-yet-built index (the indexer has never run) has no schema; the
    store raises :class:`~store.SchemaNotReadyError`. That is not an error
    for this endpoint — a missing index simply means nothing has failed, so
    it is reported as an empty list.
    """
    from store import SchemaNotReadyError

    try:
        failed = store_reader.get_failed_documents()
    except SchemaNotReadyError:
        failed = []
    return IndexFailedResponse(
        documents=[
            FailedDocumentResponse(
                document_id=f.document_id,
                title=f.title,
                failure_count=f.failure_count,
            )
            for f in failed
        ]
    )


def _index_rebuild(settings: Settings) -> RebuildResponse:
    """Rebuild handler body: write the rebuild + reconcile sentinels beside index.db.

    Writing ``rebuild.request`` schedules the destructive wipe; writing
    ``reconcile.request`` at the same time wakes the indexer's
    ``_interruptible_wait`` early so the rebuild is acted upon within the
    wake-check interval rather than waiting a full ``RECONCILE_INTERVAL``
    (up to 5 minutes by default).

    Security: writes ONLY the two sentinel files — never the index database.
    The indexer holds the exclusive writer flock and is the sole process that
    mutates ``index.db``; it consumes the sentinels and performs the wipe.

    Raises :class:`fastapi.HTTPException` (503) when the sentinel directory
    does not exist or is not writable — which indicates a misconfigured
    ``INDEX_DB_PATH`` rather than a transient error, so the admin needs a
    useful message rather than a generic 500.
    """
    from fastapi import HTTPException

    db_dir = Path(settings.INDEX_DB_PATH).parent
    sentinel = db_dir / _REBUILD_SENTINEL_NAME
    reconcile_sentinel = db_dir / _RECONCILE_SENTINEL_NAME
    try:
        sentinel.touch()
        reconcile_sentinel.touch()
    except OSError as exc:
        log.error(
            "api.index_rebuild_sentinel_write_failed",
            sentinel=str(sentinel),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="cannot write sentinel: index data directory not writable",
        ) from exc
    log.warning("api.index_rebuild_triggered", sentinel=str(sentinel))
    return RebuildResponse(
        accepted=True,
        detail=(
            "Index rebuild triggered. The indexer will wipe and re-index "
            "the whole archive on its next cycle."
        ),
    )
