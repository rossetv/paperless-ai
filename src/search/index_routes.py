"""The Index operations-dashboard ``/api`` router.

- ``GET  /api/index/status``   — per-daemon status + overall health.
- ``GET  /api/index/activity`` — recent reconcile/sweep cycles.
- ``GET  /api/index/failed``   — documents the indexer has failed to index.
- ``POST /api/index/rebuild``  — the destructive index rebuild (admin only).

The rebuild never touches ``index.db``, which the indexer holds an exclusive
flock on; it drops sentinel files the indexer consumes (see
:mod:`search.index_sentinel`).
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends

from appdb import daemon_status, reconcile_activity
from search.deps import get_app_db, require_admin, require_api_scope
from search.index_sentinel import request_index_rebuild
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

_ACTIVITY_LIMIT = 50


def build_index_router(settings: Settings, store_reader: StoreReader) -> APIRouter:
    """Build the Index dashboard ``/api`` router."""
    router = APIRouter()
    read_access = Depends(require_api_scope)

    @router.get("/api/index/status", dependencies=[read_access])
    def index_status(
        app_db: sqlite3.Connection = Depends(get_app_db),
    ) -> IndexStatusResponse:
        """Return every daemon's status and the overall health verdict."""
        return _index_status(app_db)

    @router.get("/api/index/activity", dependencies=[read_access])
    def index_activity(
        app_db: sqlite3.Connection = Depends(get_app_db),
    ) -> IndexActivityResponse:
        """Return the most recent reconcile/sweep cycles."""
        return _index_activity(app_db)

    @router.get("/api/index/failed", dependencies=[read_access])
    def index_failed() -> IndexFailedResponse:
        """Return the documents the indexer has failed to index."""
        return _index_failed(store_reader)

    @router.post("/api/index/rebuild", dependencies=[Depends(require_admin)])
    def index_rebuild() -> RebuildResponse:
        """Trigger the destructive index rebuild (admin-only)."""
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

    An index that has never been built raises
    :class:`~store.SchemaNotReadyError`; nothing has failed yet, so that is an
    empty list.
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
    """Write the rebuild sentinels beside index.db.

    An unwritable sentinel directory means a misconfigured ``INDEX_DB_PATH``,
    not a transient fault, so it is a 503 with a useful message rather than a
    generic 500.
    """
    from fastapi import HTTPException

    try:
        request_index_rebuild(settings.INDEX_DB_PATH)
    except OSError as exc:
        log.error(
            "api.index_rebuild_sentinel_write_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="cannot write sentinel: index data directory not writable",
        ) from exc
    return RebuildResponse(
        accepted=True,
        detail=(
            "Index rebuild triggered. The indexer will wipe and re-index "
            "the whole archive on its next cycle."
        ),
    )
