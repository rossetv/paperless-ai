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
Configuration is loaded from app.db (the config table) layered over the
environment via common.config.current_settings, and re-checked at the top of
every reconciliation cycle so a config change hot-loads (web-redesign §5).
Forbidden: imports from search/, sqlite3, httpx direct, bare openai calls.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import typing
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import structlog

from appdb.connection import connect as connect_app_db
from appdb.schema import ensure_schema
from common.clock import utc_now_iso
from common.concurrency import llm_limiter
from common.config import Settings, current_settings
from indexer.activity import IndexerActivityRecorder
from common.embeddings import EMBEDDING_FAILURE_EXCEPTIONS, EmbeddingClient
from common.library_setup import setup_libraries
from common.logging_config import configure_logging
from common.paperless import PAPERLESS_CALL_EXCEPTIONS, PaperlessClient
from common.shutdown import is_shutdown_requested, register_signal_handlers
from indexer.lock import IndexerLockError, acquire_writer_lock
from indexer.reconciler import Reconciler
from store import StoreError
from store.writer import StoreWriter

log = structlog.get_logger(__name__)

# Duration of each sleep slice in _interruptible_wait.  Short enough to react
# to shutdown and manual triggers promptly; long enough to avoid busy-looping.
_WAKE_CHECK_INTERVAL: float = 5.0

# How often to beat the idle heartbeat during the inter-cycle wait.  Must be
# well below the stale-after threshold (90 s by default) so the dashboard
# never reads the indexer as "stopped" while it is simply waiting.
_IDLE_BEAT_INTERVAL: float = 30.0

# The rebuild-sentinel file name. Written beside index.db by the search
# server's POST /api/index/rebuild; consumed here at cycle entry to wipe and
# re-index the whole archive (web-redesign spec §5, Wave 6).
_REBUILD_SENTINEL_NAME = "rebuild.request"

# Key used to embed a single token to verify the embedding model is reachable.
_PREFLIGHT_EMBED_TEXT = "ping"

# Combined exception tuple for the preflight boundary — covers both Paperless
# transport errors and embedding model failures so the except clause is typed.
_PREFLIGHT_EXCEPTIONS: tuple[type[Exception], ...] = (
    *PAPERLESS_CALL_EXCEPTIONS,
    *EMBEDDING_FAILURE_EXCEPTIONS,
)


@dataclass(frozen=True, slots=True)
class _IndexerResources:
    """Per-cycle, config-derived resources held by ``_run_loop``.

    The reconciliation loop owns these as a single bundle so the hot-reload
    path (web-redesign §5) can replace them atomically when ``config_version``
    moves: every field is rebuilt from the new ``Settings`` together, and the
    old paperless client is closed in the same step.

    ``store_writer`` is *not* config-derived — the index database path is a
    bootstrap-only env-var — but is bundled here so ``_run_loop`` has a single
    handle for the data the cycle needs.
    """

    reconciler: Reconciler
    paperless: PaperlessClient
    embedding_client: EmbeddingClient
    store_writer: StoreWriter


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

    # Hold lock_handle open for the process lifetime.
    try:
        _start_daemon(settings, app_db_path, lock_handle, app_db)
    finally:
        lock_handle.close()
        if app_db is not None:
            app_db.close()


def _start_daemon(
    settings: Settings,
    app_db_path: str,
    lock_handle: typing.IO[bytes],
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
        lock_handle: The open flock file handle from
            :func:`~indexer.lock.acquire_writer_lock`, kept open to hold the
            lock for the process lifetime.
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


def _rebuild_reconciler(settings: Settings, old: Reconciler) -> Reconciler:
    """Rebuild the Reconciler and its config-derived clients on a config change.

    Hot-load boundary (web-redesign §5): when the ``config`` table changes the
    indexer replaces its config-derived resources between cycles rather than
    restarting. ``configure_logging`` and ``setup_libraries`` are re-applied so
    the OpenAI client picks up a changed API key or base URL; the LLM
    concurrency limiter is re-sized; the Paperless and embedding clients are
    rebuilt from the new ``Settings``. The store writer is *not* config-derived
    — the index database path is a bootstrap env-var — so the old writer is
    reused via ``old.store_writer``.

    The old reconciler's paperless client is left to garbage collection: the
    new reconciler is returned and assigned over the old one, removing the
    only live reference. ``httpx.Client`` releases its connection pool through
    its finaliser, so the pool is reclaimed promptly without an explicit close
    call — which would require widening the reconciler's public API.

    Args:
        settings: The freshly loaded configuration.
        old: The reconciler in use up to now — its ``store_writer`` is carried
            over to the new instance.

    Returns:
        A new :class:`~indexer.reconciler.Reconciler` built from *settings*,
        sharing the same :class:`~store.writer.StoreWriter` as *old*.
    """
    configure_logging(settings)
    setup_libraries(settings)
    llm_limiter.init(settings.LLM_MAX_CONCURRENT)
    paperless = PaperlessClient(settings)
    embedding_client = EmbeddingClient(settings)
    return Reconciler(
        settings=settings,
        paperless=paperless,
        store_writer=old.store_writer,
        embedding_client=embedding_client,
    )


def _run_loop(
    *,
    reconciler: Reconciler,
    store_writer: StoreWriter,
    settings: Settings,
    app_db_path: str,
    sentinel_path: Path,
    clock: Callable[[], float] = time.monotonic,
    cycle_recorder: IndexerActivityRecorder | None = None,
) -> None:
    """Run the reconciliation loop until shutdown is requested.

    Each iteration:

    0. Re-check :func:`common.config.current_settings`. When ``config_version``
       has moved the loop rebuilds *reconciler* via :func:`_rebuild_reconciler`,
       so a config save propagates with no restart (web-redesign §5). The
       ``RECONCILE_INTERVAL`` and ``DELETION_SWEEP_INTERVAL`` used to schedule
       this and every subsequent cycle are re-read from the live ``Settings``.
    1. Check the shutdown flag — exit immediately if set.
    2. Check for a manual-trigger sentinel file — consume it if present.
    3. Run ``reconciler.incremental_sync()``.
    4. Run ``reconciler.deletion_sweep()`` if the sweep interval has elapsed
       OR a manual trigger was pending at cycle start.
    5. ``store_writer.checkpoint()``.
    6. ``_interruptible_wait(settings.RECONCILE_INTERVAL)`` — returns early on
       shutdown or if a new sentinel appears.

    Steps 3–5 run inside a cycle-level ``try/except Exception``: a transient
    failure anywhere in the cycle is logged with its traceback and the loop
    falls through to the wait, so the next cycle retries.  A cycle failure
    never crashes the daemon and never advances the deletion-sweep clock.

    The loop is sequential; cycles never overlap.

    Args:
        reconciler: The Reconciler instance — replaced in-place by a fresh
            one if :func:`current_settings` returns a new ``Settings`` on a
            cycle boundary.
        store_writer: The StoreWriter instance (used for checkpoint).
        settings: The initial Settings — replaced in-place by a fresh snapshot
            if :func:`current_settings` returns a new value.
        app_db_path: Filesystem path to ``app.db`` — the source the hot-load
            accessor watches every cycle.
        sentinel_path: Path to the manual-trigger sentinel file
            (``<data-dir>/reconcile.request``).
        clock: Monotonic-seconds source used to schedule the deletion sweep.
            Defaults to :func:`time.monotonic`; tests inject a deterministic
            clock to drive the sweep cadence without real elapsed time
            (CODE_GUIDELINES §11.4).
        cycle_recorder: Optional recorder that logs each sync/sweep cycle to
            the reconcile-activity table and beats the indexer's daemon-status
            heartbeat (web-redesign spec §5, Wave 6). None in tests; the
            daemon supplies a real one.
    """
    # Start the sweep clock at 0 so the first cycle is always far enough past
    # the (zero) last-sweep time to run a deletion sweep.
    last_sweep_at: float = 0.0

    while not is_shutdown_requested():
        # Hot-load boundary (web-redesign §5): re-check config_version. When
        # it has moved, rebuild the config-derived resources for this and
        # every later cycle. current_settings() returns the SAME cached
        # object when nothing changed, so the `is` check is the whole cost.
        latest = current_settings(app_db_path)
        if latest is not settings:
            log.info("indexer.config_reloaded")
            reconciler = _rebuild_reconciler(latest, reconciler)
            settings = latest

        # Consume a manual trigger at cycle entry — it forces a deletion sweep
        # regardless of the interval (SPEC §5.8).
        manual_trigger = _consume_sentinel(sentinel_path)
        if manual_trigger:
            log.info("indexer.manual_trigger_consumed")

        # Consume a rebuild trigger at cycle entry — wipe the index before
        # this cycle's sync so the sync re-indexes the whole archive
        # (web-redesign spec §5, Wave 6). The rebuild sentinel lives beside
        # index.db, the same directory as the reconcile sentinel.
        rebuild_sentinel = sentinel_path.parent / _REBUILD_SENTINEL_NAME
        if _consume_sentinel(rebuild_sentinel):
            _run_rebuild(store_writer, cycle_recorder)

        # Determine whether a deletion sweep is due this cycle. The interval
        # is read live from settings so a hot-loaded change takes effect now.
        elapsed = clock() - last_sweep_at
        run_sweep = manual_trigger or elapsed >= settings.DELETION_SWEEP_INTERVAL

        try:
            # Run incremental sync every cycle.
            sync_started = utc_now_iso()
            sync_report = reconciler.incremental_sync()
            log.info(
                "indexer.cycle_sync",
                indexed=sync_report.indexed,
                metadata_only=sync_report.metadata_only,
                skipped=sync_report.skipped,
                failed=sync_report.failed,
                given_up=sync_report.given_up,
            )
            if cycle_recorder is not None:
                cycle_recorder.record_sync(
                    sync_report,
                    started_at=sync_started,
                    finished_at=utc_now_iso(),
                )

            # Run deletion sweep when due.
            if run_sweep:
                sweep_started = utc_now_iso()
                sweep_report = reconciler.deletion_sweep()
                last_sweep_at = clock()
                log.info(
                    "indexer.cycle_sweep",
                    pruned=sweep_report.pruned,
                    candidates=sweep_report.candidates,
                    aborted=sweep_report.aborted,
                )
                if cycle_recorder is not None:
                    cycle_recorder.record_sweep(
                        sweep_report,
                        started_at=sweep_started,
                        finished_at=utc_now_iso(),
                    )

            store_writer.checkpoint()
        except Exception:
            # rationale: cycle-level fault isolation (CODE_GUIDELINES §6.4
            # outer-boundary catch) — a transient failure anywhere in the
            # cycle (a taxonomy-refresh network error, an incremental-paging
            # drop, a malformed Paperless document, a StoreError) must not
            # crash the daemon.  The traceback is logged and the loop falls
            # through to the wait so the next cycle retries — mirroring
            # common/daemon_loop.run_polling_threadpool.  last_sweep_at is
            # assigned only after a successful sweep, so a failed cycle never
            # advances it: a missed sweep is retried next cycle.
            log.exception("indexer.cycle_failed")

        # Wait for the next cycle, waking early on shutdown or a new sentinel.
        # The interval is read live from settings so a hot-loaded change to
        # RECONCILE_INTERVAL takes effect from this wait onwards.  The
        # cycle_recorder is passed so the wait can beat idle periodically and
        # prevent the dashboard from reporting the indexer as "stopped" while
        # it is simply sleeping between cycles.
        _interruptible_wait(
            seconds=float(settings.RECONCILE_INTERVAL),
            sentinel_path=sentinel_path,
            cycle_recorder=cycle_recorder,
        )


def _run_loop_for_test(
    *,
    app_db_path: str,
    cycles: int,
    on_cycle_1: Callable[[], None] | None = None,
) -> None:
    """Drive the hot-load check of :func:`_run_loop` for a fixed number of cycles.

    Test seam (CODE_GUIDELINES §11.4): runs the cycle-0 hot-load check
    (``current_settings(app_db_path)`` and the optional rebuild) ``cycles``
    times, without the real ``while not is_shutdown_requested()`` loop, the
    real reconciler work, the sleep, or any filesystem I/O. *on_cycle_1* is
    invoked between cycle 1 and cycle 2 so a test can simulate an external
    config write that the next cycle's hot-load check must observe.

    Args:
        app_db_path: ``app.db`` location — forwarded to :func:`current_settings`.
        cycles: Number of cycles to drive.
        on_cycle_1: Optional callable invoked after cycle 1's hot-load check;
            used by hot-reload tests to bump ``config_version`` between cycles.
    """
    settings = current_settings(app_db_path)
    reconciler: Reconciler | None = None  # the real loop has one; tests don't.

    for index in range(cycles):
        latest = current_settings(app_db_path)
        if latest is not settings:
            # The patched _rebuild_reconciler in tests just records the call
            # and returns the placeholder; the real path builds a new one.
            reconciler = _rebuild_reconciler(latest, reconciler)  # type: ignore[arg-type]
            settings = latest
        if index == 0 and on_cycle_1 is not None:
            on_cycle_1()


def _interruptible_wait(
    seconds: float,
    sentinel_path: Path,
    cycle_recorder: IndexerActivityRecorder | None = None,
) -> bool:
    """Sleep for *seconds*, waking early on shutdown or a sentinel file.

    Sleeps in slices of ``_WAKE_CHECK_INTERVAL`` seconds.  On each slice:

    - If ``is_shutdown_requested()`` → return ``False`` (no manual trigger).
    - If *sentinel_path* exists → delete it and return ``True`` (manual trigger
      detected; the next cycle should include a deletion sweep).

    When *cycle_recorder* is provided the function beats an idle heartbeat
    every ``_IDLE_BEAT_INTERVAL`` seconds so the Index dashboard does not
    report the indexer as ``stopped`` during long inter-cycle waits.  The
    default reconcile interval (300 s) exceeds the stale-after threshold (90 s)
    by more than three times, so without this beat the dashboard routinely
    shows the indexer as stopped while it is healthy.

    Args:
        seconds: How long to wait in total.
        sentinel_path: Path to the manual-trigger sentinel file.
        cycle_recorder: Optional activity recorder — ``beat_idle`` is called
            periodically when provided.  ``None`` in tests that do not need
            heartbeat coverage.

    Returns:
        ``True`` if a manual-trigger sentinel was detected and consumed;
        ``False`` if the full duration elapsed or shutdown was requested.
    """
    deadline = time.monotonic() + seconds
    last_beat_at = time.monotonic()

    # Check sentinel immediately at entry — a sentinel written just before the
    # wait begins is detected without sleeping first.
    if sentinel_path.exists():
        sentinel_path.unlink(missing_ok=True)
        log.debug("indexer.sentinel_consumed_at_wait_entry")
        return True

    while time.monotonic() < deadline:
        if is_shutdown_requested():
            return False

        # Beat idle if enough time has elapsed since the last beat.
        if cycle_recorder is not None:
            now = time.monotonic()
            if now - last_beat_at >= _IDLE_BEAT_INTERVAL:
                cycle_recorder.beat_idle()
                last_beat_at = now

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


def _run_rebuild(
    store_writer: StoreWriter,
    cycle_recorder: IndexerActivityRecorder | None,
) -> None:
    """Wipe the index in response to a consumed rebuild sentinel.

    Calls :meth:`~store.writer.StoreWriter.rebuild_index` and records the
    rebuild into the dashboard's activity log. A :class:`~store.StoreError`
    from the wipe is logged and swallowed — a failed rebuild must not crash
    the daemon; the operator can re-trigger it. The cycle's normal
    incremental sync runs next regardless: on a successful wipe it re-indexes
    everything; on a failed wipe it is an ordinary incremental sync.
    """
    log.warning("indexer.rebuild_triggered")
    rebuild_started = utc_now_iso()
    try:
        store_writer.rebuild_index()
    except StoreError:
        # rationale: a rebuild failure is a recoverable operational error —
        # logged with its traceback, not fatal. The operator re-triggers it.
        log.exception("indexer.rebuild_failed")
        return
    if cycle_recorder is not None:
        cycle_recorder.record_rebuild(
            started_at=rebuild_started,
            finished_at=utc_now_iso(),
        )
    log.warning("indexer.rebuild_completed")


if __name__ == "__main__":
    main()
