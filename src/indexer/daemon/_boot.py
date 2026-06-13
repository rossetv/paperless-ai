"""Daemon boot sequence — flock, preflight, client construction, loop entry.

The startup half of the indexer daemon (CODE_GUIDELINES §3.3): acquire the
exclusive writer flock, run preflight (Paperless reachable, store writable,
embedding model responds, embedding-model check), construct the long-lived
clients and the Reconciler, and hand off to :func:`._loop._run_loop`.  The
run-loop itself lives in :mod:`._loop`.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import structlog

from appdb.connection import connect as connect_app_db
from appdb.schema import ensure_schema
from common.config import Settings, current_settings
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

# Key used to embed a single token to verify the embedding model is reachable.
_PREFLIGHT_EMBED_TEXT = "ping"

# Combined exception tuple for the preflight boundary — covers both Paperless
# transport errors and embedding model failures so the except clause is typed.
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
    # The hot-load accessor reads APP_DB_PATH from the environment and layers
    # the config table over it. _run_loop re-checks it every cycle, so a
    # later config change is picked up with no restart (web-redesign §5).
    settings = current_settings()
    configure_logging(settings)
    setup_libraries(settings)

    # --- Acquire exclusive writer flock (SPEC §3.2, CODE_GUIDELINES §1.12) ---
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

    # APP_DB_PATH is the location the hot-load accessor watches every cycle.
    # Resolved here and threaded down so the loop never re-reads os.environ.
    app_db_path = os.environ.get("APP_DB_PATH", "/data/app.db")

    # The Index dashboard's app.db connection — for the heartbeat and the
    # reconcile-activity log (web-redesign spec §5, Wave 6). Opened best-
    # effort: if app.db is unreachable the indexer still runs; the recorder
    # is simply None and the dashboard's indexer tile goes stale.
    app_db = _open_app_db(app_db_path)

    # lock_handle is held open by this stack frame until finally closes it,
    # which keeps the OS flock alive for the daemon's entire lifetime.
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

    Separated from main() so tests can inject a fake lock without needing a
    real flock on disk.

    Args:
        settings: Loaded application settings — the *initial* snapshot. The
            reconciliation loop re-checks :func:`common.config.current_settings`
            at the top of every cycle, so a later config change is picked up
            with no restart (web-redesign §5).
        app_db_path: Filesystem path to ``app.db`` — threaded through to the
            loop so :func:`current_settings` watches the same file every cycle.
        app_db: The open app.db connection for the dashboard recorder, or None
            when app.db is unavailable.
    """
    register_signal_handlers()

    # ------------------------------------------------------------------
    # Preflight (SPEC §5.7)
    # ------------------------------------------------------------------
    # Construct the long-lived clients ONCE here so preflight verifies the
    # exact instances the daemon goes on to use — a throwaway client proves
    # nothing about the one doing the real work.
    paperless = PaperlessClient(settings)
    embedding_client = EmbeddingClient(settings)
    try:
        _run_preflight(paperless, embedding_client)
    except _PREFLIGHT_EXCEPTIONS:
        # rationale: startup-preflight fatal boundary — a Paperless transport
        # failure or embedding model error must stop the daemon before indexing
        # begins (fail closed, CODE_GUIDELINES §1.11).  exc_info=True attaches
        # the traceback that error=str(exc) would discard on this exit path.
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
        # rationale: startup-preflight fatal boundary — a store error opening
        # or migrating the index, or applying an embedding-model change, must
        # stop the daemon before the loop runs (CODE_GUIDELINES §1.11).
        # exc_info=True attaches the traceback; error=str(exc) would discard it.
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

    # Build the dashboard recorder only when app.db is available.
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
        # Note: a config change between cycles replaces ``reconciler`` and its
        # paperless client; the old client is dereferenced and GC reclaims it
        # (httpx pools release on finaliser + atexit). The ``paperless`` name
        # here is the *startup* client — held so the original handle survives
        # the loop body and can be closed deterministically on shutdown.
        paperless.close()
        store_writer.close()

    log.info("indexer.stopped")


def _open_app_db(app_db_path: str) -> sqlite3.Connection | None:
    """Open the app.db connection for the dashboard, best-effort.

    Returns an open, migrated connection, or ``None`` if app.db cannot be
    opened — in which case the indexer runs without recording activity or a
    heartbeat (web-redesign spec §5: the dashboard is never worth crashing a
    daemon over).
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
    """Verify Paperless reachability and the embedding model responds.

    Raises on any fatal condition; the caller maps the exception to a
    CRITICAL log and a non-zero exit.

    Args:
        paperless: The live PaperlessClient the daemon will use.
        embedding_client: The live EmbeddingClient the daemon will use — the
            same instance, so preflight verifies what actually does the work.
    """
    log.info("indexer.preflight_started")

    # Verify Paperless is reachable.
    paperless.ping()
    log.info("indexer.preflight_paperless_ok")

    # Verify the embedding model responds with a minimal single-token embed,
    # exercising the very client the reconciler will go on to use.
    embedding_client.embed([_PREFLIGHT_EMBED_TEXT])
    log.info("indexer.preflight_embedding_ok")
