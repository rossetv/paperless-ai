"""The indexer's reconciliation loop, per-cycle body, and hot-reload rebuild."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import structlog

from common.clock import utc_now_iso
from common.concurrency import llm_limiter
from common.config import Settings, current_settings
from common.embeddings import EmbeddingClient
from common.library_setup import setup_libraries
from common.logging_config import configure_logging
from common.paperless import PaperlessClient
from common.shutdown import is_shutdown_requested
from indexer.daemon._wait import _consume_sentinel, _interruptible_wait
from indexer.reconciler import Reconciler
from store import StoreError
from store.writer import StoreWriter

if TYPE_CHECKING:
    from pathlib import Path

    from indexer.activity import IndexerActivityRecorder
    from indexer.reconciler import SweepReport

log = structlog.get_logger(__name__)

# Written beside index.db by the search server's POST /api/index/rebuild;
# consumed at cycle entry to wipe and re-index the whole archive.
_REBUILD_SENTINEL_NAME = "rebuild.request"


def _rebuild_reconciler(settings: Settings, old: Reconciler) -> Reconciler:
    """Rebuild the Reconciler and its config-derived clients on a config change.

    Logging and library setup are re-applied so the OpenAI client picks up a
    changed API key or base URL. The store writer is not config-derived (the
    index path is a bootstrap env var), so *old*'s writer is reused.

    The old clients are closed explicitly to release their httpx pools
    deterministically. The loop is single-threaded and rebuilds between cycles,
    so the close cannot race an embed in flight.
    """
    old.paperless.close()
    old.embedding_client.close()
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
    """Run reconciliation cycles sequentially until shutdown is requested.

    Each iteration runs :func:`_run_one_cycle`, then waits
    ``RECONCILE_INTERVAL`` seconds, waking early on shutdown or when a
    manual-trigger sentinel (*sentinel_path*) appears. A sentinel consumed by
    the wait forces the next cycle's deletion sweep.

    *clock* (monotonic seconds) schedules the deletion sweep; tests inject a
    fake one. *cycle_recorder* is ``None`` when app.db is unavailable.
    """
    # last_sweep_at starts at 0 so the first cycle always runs a deletion sweep.
    state = _LoopState(reconciler=reconciler, settings=settings, last_sweep_at=0.0)

    while not is_shutdown_requested():
        state = _run_one_cycle(
            state,
            store_writer=store_writer,
            app_db_path=app_db_path,
            sentinel_path=sentinel_path,
            clock=clock,
            cycle_recorder=cycle_recorder,
        )

        # The recorder lets the wait beat idle, so the dashboard does not show
        # a sleeping indexer as stopped. A True result means the wait consumed
        # a sentinel, so the next cycle's own check would find nothing.
        if _interruptible_wait(
            seconds=float(state.settings.RECONCILE_INTERVAL),
            sentinel_path=sentinel_path,
            cycle_recorder=cycle_recorder,
        ):
            log.info("indexer.manual_trigger_consumed")
            state = replace(state, sweep_pending=True)


@dataclass(frozen=True, slots=True)
class _LoopState:
    """The state :func:`_run_one_cycle` reads in and returns each iteration.

    Attributes:
        reconciler: The current Reconciler, replaced on a config change.
        settings: The current Settings snapshot, replaced on a config change.
        last_sweep_at: Monotonic seconds of the last deletion sweep to return;
            a cycle that raises never moves it.
        sweep_pending: A consumed manual trigger whose deletion sweep has not
            yet run. It survives a failed cycle and is cleared once
            ``deletion_sweep()`` returns. An aborted sweep (Paperless
            enumeration failed) returns normally and so clears it too; the
            abort is recorded ``ok=False`` for the operator to re-trigger.
    """

    reconciler: Reconciler
    settings: Settings
    last_sweep_at: float
    sweep_pending: bool = False


def _run_one_cycle(
    state: _LoopState,
    *,
    store_writer: StoreWriter,
    app_db_path: str,
    sentinel_path: Path,
    clock: Callable[[], float],
    cycle_recorder: IndexerActivityRecorder | None,
) -> _LoopState:
    """Run one reconciliation cycle and return the next loop state.

    The cycle re-checks config, consumes sentinels, runs the incremental sync,
    the deletion sweep when due, and a checkpoint. A manual trigger (a sentinel
    found now, or ``state.sweep_pending``) forces the sweep regardless of the
    interval. Any exception is logged and the cycle ends, so the next retries.
    """
    reconciler = state.reconciler
    settings = state.settings
    last_sweep_at = state.last_sweep_at

    # current_settings() returns the same cached object when nothing changed,
    # so the `is` check is the whole cost.
    latest = current_settings(app_db_path)
    if latest is not settings:
        log.info("indexer.config_reloaded")
        reconciler = _rebuild_reconciler(latest, reconciler)
        settings = latest

    # Consume the sentinel even when a sweep is already pending, so one written
    # since the wait woke does not linger and cause a spurious extra wake.
    if _consume_sentinel(sentinel_path):
        log.info("indexer.manual_trigger_consumed")
        sweep_pending = True
    else:
        sweep_pending = state.sweep_pending

    # A rebuild wipes the index before this cycle's sync, so the sync
    # re-indexes the whole archive.
    rebuild_sentinel = sentinel_path.parent / _REBUILD_SENTINEL_NAME
    needs_rebuild = _consume_sentinel(rebuild_sentinel)

    elapsed = clock() - last_sweep_at
    run_sweep = sweep_pending or elapsed >= settings.DELETION_SWEEP_INTERVAL

    try:
        if needs_rebuild:
            _run_rebuild(store_writer, cycle_recorder, settings=settings)
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

        # The sweep clock and pending trigger move only once deletion_sweep()
        # returns, so a sweep that raises is retried, still forced, next cycle.
        if run_sweep:
            sweep_started = utc_now_iso()
            sweep_report = reconciler.deletion_sweep()
            last_sweep_at = clock()
            sweep_pending = False
            _report_sweep(sweep_report, cycle_recorder, started_at=sweep_started)

        store_writer.checkpoint()
    except Exception:
        # A transient failure anywhere in the cycle (network, a malformed
        # document, a StoreError) must not crash the daemon; the next cycle
        # retries.
        log.exception("indexer.cycle_failed")

    return _LoopState(
        reconciler=reconciler,
        settings=settings,
        last_sweep_at=last_sweep_at,
        sweep_pending=sweep_pending,
    )


def _report_sweep(
    sweep_report: SweepReport,
    cycle_recorder: IndexerActivityRecorder | None,
    *,
    started_at: str,
) -> None:
    """Log a completed deletion sweep and record it in the activity log."""
    log.info(
        "indexer.cycle_sweep",
        pruned=sweep_report.pruned,
        candidates=sweep_report.candidates,
        aborted=sweep_report.aborted,
    )
    if cycle_recorder is not None:
        cycle_recorder.record_sweep(
            sweep_report, started_at=started_at, finished_at=utc_now_iso()
        )


def _run_rebuild(
    store_writer: StoreWriter,
    cycle_recorder: IndexerActivityRecorder | None,
    *,
    settings: Settings,
) -> None:
    """Wipe the index in response to a consumed rebuild sentinel.

    A :class:`~store.StoreError` is logged and swallowed; the operator can
    re-trigger. *settings* is the cycle's live config, not the writer's boot
    settings, so a rebuild after a model switch stamps the new model into meta.
    """
    log.warning("indexer.rebuild_triggered")
    rebuild_started = utc_now_iso()
    try:
        store_writer.rebuild_index(
            embedding_model=settings.EMBEDDING_MODEL,
            embedding_dimensions=settings.EMBEDDING_DIMENSIONS,
        )
    except StoreError:
        log.exception("indexer.rebuild_failed")
        return
    if cycle_recorder is not None:
        cycle_recorder.record_rebuild(
            started_at=rebuild_started,
            finished_at=utc_now_iso(),
        )
    log.warning("indexer.rebuild_completed")
