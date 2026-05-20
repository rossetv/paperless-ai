"""Indexer reconciliation daemon entry point.

Runs the semantic-search indexer: acquires the exclusive writer flock, performs
preflight checks, constructs the Reconciler, and enters the reconciliation loop.

Boot order::

    1. Settings + logging + libraries
    2. Acquire OS flock on ``<INDEX_DB_PATH>.lock`` — another indexer aborts.
    3. Register SIGTERM / SIGINT shutdown handlers.
    4. Preflight: Paperless reachable, store writable, embedding model responds,
       check_embedding_model() (may trigger a rebuild).
    5. Construct Reconciler and StoreWriter.
    6. Enter _run_loop.

Allowed deps: store/ (StoreWriter), indexer/ (lock, reconciler), common/.
Forbidden: imports from search/, sqlite3, httpx direct, bare openai calls.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import structlog

from common.config import Settings
from common.embeddings import EmbeddingClient
from common.library_setup import setup_libraries
from common.logging_config import configure_logging
from common.paperless import PaperlessClient
from common.shutdown import is_shutdown_requested, register_signal_handlers
from indexer.lock import IndexerLockError, acquire_writer_lock
from indexer.reconciler import Reconciler
from store.writer import StoreWriter

log = structlog.get_logger(__name__)

# Duration of each sleep slice in _interruptible_wait.  Short enough to react
# to shutdown and manual triggers promptly; long enough to avoid busy-looping.
_WAKE_CHECK_INTERVAL: float = 5.0

# Key used to embed a single token to verify the embedding model is reachable.
_PREFLIGHT_EMBED_TEXT = "ping"


def main() -> None:
    """Daemon entry point.

    Exits non-zero if the writer lock is already held (another indexer running)
    or if preflight fails fatally.  Normal daemon operation never returns;
    it runs until SIGTERM / SIGINT.
    """
    settings = Settings()
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

    # Hold lock_handle open for the process lifetime.
    try:
        _start_daemon(settings, lock_handle)
    finally:
        lock_handle.close()


def _start_daemon(settings: Settings, lock_handle: object) -> None:
    """Run signal registration, preflight, and the reconciliation loop.

    Separated from main() so tests can inject a fake lock without needing a
    real flock on disk.

    Args:
        settings: Loaded application settings.
        lock_handle: The open flock file handle (kept open to hold the lock).
    """
    register_signal_handlers()

    # ------------------------------------------------------------------
    # Preflight (SPEC §5.7)
    # ------------------------------------------------------------------
    paperless = PaperlessClient(settings)
    try:
        _run_preflight(settings, paperless)
    except Exception as exc:
        log.critical("indexer.preflight_failed", error=str(exc))
        paperless.close()
        sys.exit(2)

    store_writer = StoreWriter(settings)
    embedding_client = EmbeddingClient(settings)

    try:
        rebuild = store_writer.check_embedding_model()
        if rebuild:
            log.warning(
                "indexer.embedding_model_rebuild_triggered",
                advice="All chunks wiped; next reconciliation re-embeds everything.",
            )
    except Exception as exc:
        log.critical("indexer.store_preflight_failed", error=str(exc))
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

    try:
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            reconcile_interval=settings.RECONCILE_INTERVAL,
            deletion_sweep_interval=settings.DELETION_SWEEP_INTERVAL,
            sentinel_path=sentinel_path,
        )
    finally:
        paperless.close()
        store_writer.close()

    log.info("indexer.stopped")


def _run_preflight(settings: Settings, paperless: PaperlessClient) -> None:
    """Verify Paperless reachability and the embedding model responds.

    Raises on any fatal condition; the caller maps the exception to a
    CRITICAL log and a non-zero exit.

    Args:
        settings: Application settings.
        paperless: A live PaperlessClient.
    """
    log.info("indexer.preflight_started")

    # Verify Paperless is reachable.
    paperless.ping()
    log.info("indexer.preflight_paperless_ok")

    # Verify the embedding model responds with a minimal single-token embed.
    embedding_client = EmbeddingClient(settings)
    embedding_client.embed([_PREFLIGHT_EMBED_TEXT])
    log.info("indexer.preflight_embedding_ok")


def _run_loop(
    *,
    reconciler: Reconciler,
    store_writer: StoreWriter,
    reconcile_interval: int,
    deletion_sweep_interval: int,
    sentinel_path: Path,
    _last_sweep_at: float | None = None,
) -> None:
    """Run the reconciliation loop until shutdown is requested.

    Each iteration:
    1. Check the shutdown flag — exit immediately if set.
    2. Check for a manual-trigger sentinel file — consume it if present.
    3. Run ``reconciler.incremental_sync()``.
    4. Run ``reconciler.deletion_sweep()`` if the sweep interval has elapsed
       OR a manual trigger was pending at cycle start.
    5. ``store_writer.checkpoint()``.
    6. ``_interruptible_wait(reconcile_interval)`` — returns early on shutdown
       or if a new sentinel appears.

    The loop is sequential; cycles never overlap.

    Args:
        reconciler: The Reconciler instance.
        store_writer: The StoreWriter instance (used for checkpoint).
        reconcile_interval: Seconds between cycles (RECONCILE_INTERVAL).
        deletion_sweep_interval: Seconds between deletion sweeps
            (DELETION_SWEEP_INTERVAL).
        sentinel_path: Path to the manual-trigger sentinel file
            (``<data-dir>/reconcile.request``).
        _last_sweep_at: Internal — monotonic timestamp of the last sweep;
            defaults to 0 so the first cycle always sweeps.  Exposed as a
            parameter for test injection.
    """
    last_sweep_at: float = _last_sweep_at if _last_sweep_at is not None else 0.0

    while not is_shutdown_requested():
        # Consume a manual trigger at cycle entry — it forces a deletion sweep
        # regardless of the interval (SPEC §5.8).
        manual_trigger = _consume_sentinel(sentinel_path)
        if manual_trigger:
            log.info("indexer.manual_trigger_consumed")

        # Determine whether a deletion sweep is due this cycle.
        elapsed = time.monotonic() - last_sweep_at
        run_sweep = manual_trigger or elapsed >= deletion_sweep_interval

        # Run incremental sync every cycle.
        sync_report = reconciler.incremental_sync()
        log.info(
            "indexer.cycle_sync",
            indexed=sync_report.indexed,
            metadata_only=sync_report.metadata_only,
            skipped=sync_report.skipped,
            failed=sync_report.failed,
        )

        # Run deletion sweep when due.
        if run_sweep:
            sweep_report = reconciler.deletion_sweep()
            last_sweep_at = time.monotonic()
            log.info(
                "indexer.cycle_sweep",
                pruned=sweep_report.pruned,
                candidates=sweep_report.candidates,
                aborted=sweep_report.aborted,
            )

        store_writer.checkpoint()

        # Wait for the next cycle, waking early on shutdown or a new sentinel.
        _interruptible_wait(
            seconds=float(reconcile_interval),
            sentinel_path=sentinel_path,
        )


def _interruptible_wait(seconds: float, sentinel_path: Path) -> bool:
    """Sleep for *seconds*, waking early on shutdown or a sentinel file.

    Sleeps in slices of ``_WAKE_CHECK_INTERVAL`` seconds.  On each slice:

    - If ``is_shutdown_requested()`` → return ``False`` (no manual trigger).
    - If *sentinel_path* exists → delete it and return ``True`` (manual trigger
      detected; the next cycle should include a deletion sweep).

    Returns:
        ``True`` if a manual-trigger sentinel was detected and consumed;
        ``False`` if the full duration elapsed or shutdown was requested.
    """
    deadline = time.monotonic() + seconds

    # Check sentinel immediately at entry — a sentinel written just before the
    # wait begins is detected without sleeping first.
    if sentinel_path.exists():
        sentinel_path.unlink(missing_ok=True)
        log.debug("indexer.sentinel_consumed_at_wait_entry")
        return True

    while time.monotonic() < deadline:
        if is_shutdown_requested():
            return False

        remaining = deadline - time.monotonic()
        slice_duration = min(_WAKE_CHECK_INTERVAL, remaining)
        if slice_duration <= 0:
            break
        time.sleep(slice_duration)

        if sentinel_path.exists():
            sentinel_path.unlink(missing_ok=True)
            log.debug("indexer.sentinel_consumed_mid_wait")
            return True

    return False


def _consume_sentinel(sentinel_path: Path) -> bool:
    """Delete *sentinel_path* and return True if it exists; else False.

    Used at cycle entry to consume a manual-trigger sentinel that may have been
    written while the previous cycle was running (SPEC §5.8).

    Args:
        sentinel_path: The sentinel file path.

    Returns:
        True if the sentinel was present and deleted; False otherwise.
    """
    if sentinel_path.exists():
        sentinel_path.unlink(missing_ok=True)
        return True
    return False


if __name__ == "__main__":
    main()
