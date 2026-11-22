"""Indexer boot: writer flock, preflight, client construction, loop entry."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import structlog

from appdb.connection import connect as connect_app_db
from appdb.schema import ensure_schema
from common.config import Settings, app_db_path_from_env, current_settings
from common.embeddings import EMBEDDING_FAILURE_EXCEPTIONS, EmbeddingClient
from common.library_setup import setup_libraries
from common.logging_config import configure_logging
from common.paperless import PAPERLESS_CALL_EXCEPTIONS, PaperlessClient
from common.shutdown import register_signal_handlers
from indexer.activity import IndexerActivityRecorder
from indexer.daemon._loop import _run_loop
from indexer.lock import IndexerLockError, acquire_writer_lock
from indexer.reconciler import Reconciler
from store import StoreError
from store.writer import StoreWriter

log = structlog.get_logger(__name__)

# Embedded once at preflight to verify the embedding model responds.
_PREFLIGHT_EMBED_TEXT = "ping"

_PREFLIGHT_EXCEPTIONS: tuple[type[Exception], ...] = (
    *PAPERLESS_CALL_EXCEPTIONS,
    *EMBEDDING_FAILURE_EXCEPTIONS,
)


def main() -> None:
    """Daemon entry point.

    Exits non-zero if the writer lock is already held (another indexer running)
    or if preflight fails fatally.  Normal daemon operation never returns;
    it runs until SIGTERM / SIGINT.
    """
    # _run_loop re-reads settings every cycle, so later config changes hot-load.
    settings = current_settings()
    configure_logging(settings)
    setup_libraries(settings)

    lock_path = settings.INDEX_DB_PATH
    try:
        lock_handle = acquire_writer_lock(lock_path)
    except IndexerLockError as exc:
        log.critical(
            "indexer.lock_contended",
            error=str(exc),
            advice="Another indexer process is already running; exiting.",
        )
        sys.exit(1)

    # Resolved once and threaded down so the loop never re-reads os.environ.
    app_db_path = app_db_path_from_env()

    # For the heartbeat and activity log. Best-effort: without app.db the
    # indexer still runs and the dashboard's indexer tile goes stale.
    app_db = _open_app_db(app_db_path)

    # Holding lock_handle open keeps the flock for the daemon's lifetime.
    try:
        _start_daemon(settings, app_db_path, app_db)
    finally:
        lock_handle.close()
        if app_db is not None:
            app_db.close()


def _start_daemon(
    settings: Settings,
    app_db_path: str,
    app_db: sqlite3.Connection | None = None,
) -> None:
    """Run signal registration, preflight, and the reconciliation loop.

    Separated from main() so tests can run it without a real flock on disk.
    *settings* is only the initial snapshot; *app_db* is ``None`` when app.db
    is unavailable.
    """
    register_signal_handlers()

    # Preflight checks the same client instances the daemon goes on to use.
    paperless = PaperlessClient(settings)
    embedding_client = EmbeddingClient(settings)
    try:
        _run_preflight(paperless, embedding_client)
    except _PREFLIGHT_EXCEPTIONS:
        # Fail closed before indexing begins.
        log.critical("indexer.preflight_failed", exc_info=True)
        paperless.close()
        sys.exit(2)

    store_writer = StoreWriter(settings)

    try:
        rebuild = store_writer.check_embedding_model()
        if rebuild:
            log.warning(
                "indexer.embedding_model_rebuild_triggered",
                advice="All chunks wiped; next reconciliation re-embeds everything.",
            )
    except StoreError:
        # A store that cannot open, migrate or apply a model change is fatal.
        log.critical("indexer.store_preflight_failed", exc_info=True)
        paperless.close()
        store_writer.close()
        sys.exit(3)

    reconciler = Reconciler(
        settings=settings,
        paperless=paperless,
        store_writer=store_writer,
        embedding_client=embedding_client,
    )

    sentinel_path = Path(settings.INDEX_DB_PATH).parent / "reconcile.request"

    log.info(
        "indexer.started",
        reconcile_interval=settings.RECONCILE_INTERVAL,
        deletion_sweep_interval=settings.DELETION_SWEEP_INTERVAL,
        embedding_model=settings.EMBEDDING_MODEL,
    )

    cycle_recorder = IndexerActivityRecorder(app_db) if app_db is not None else None

    try:
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=app_db_path,
            sentinel_path=sentinel_path,
            cycle_recorder=cycle_recorder,
        )
    finally:
        # A config change replaces the reconciler and its Paperless client,
        # leaving the old one to GC. This closes the startup client, which is
        # held here so it can be closed deterministically.
        paperless.close()
        store_writer.close()

    log.info("indexer.stopped")


def _open_app_db(app_db_path: str) -> sqlite3.Connection | None:
    """Open and migrate app.db, or return ``None`` if it cannot be opened.

    The dashboard is never worth crashing the daemon over.
    """
    try:
        conn = connect_app_db(app_db_path)
        ensure_schema(conn)
        return conn
    except (sqlite3.Error, OSError) as exc:
        log.warning("indexer.app_db_unavailable", error=str(exc))
        return None


def _run_preflight(
    paperless: PaperlessClient,
    embedding_client: EmbeddingClient,
) -> None:
    """Verify Paperless is reachable and the embedding model responds.

    Raises on any fatal condition; the caller logs it and exits non-zero.
    """
    log.info("indexer.preflight_started")

    paperless.ping()
    log.info("indexer.preflight_paperless_ok")

    embedding_client.embed([_PREFLIGHT_EMBED_TEXT])
    log.info("indexer.preflight_embedding_ok")
