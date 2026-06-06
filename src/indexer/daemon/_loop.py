"""The reconciliation run-loop, its per-cycle body, and the hot-reload rebuild.

The heart of the indexer daemon: :func:`_run_loop` drives :func:`_run_one_cycle`
until shutdown is requested, threading the (hot-reloadable) reconciler, settings,
and sweep clock through each iteration as an immutable :class:`_LoopState`.  The
config hot-reload (web-redesign §5) rebuilds the config-derived clients between
cycles via :func:`_rebuild_reconciler`.

This is a module of the ``indexer.daemon`` package (CODE_GUIDELINES §3.3); the
boot sequence lives in :mod:`._boot` and the inter-cycle wait in :mod:`._wait`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
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

log = structlog.get_logger(__name__)

# The rebuild-sentinel file name. Written beside index.db by the search
# server's POST /api/index/rebuild; consumed here at cycle entry to wipe and
# re-index the whole archive (web-redesign spec §5, Wave 6).
_REBUILD_SENTINEL_NAME = "rebuild.request"


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

    The old reconciler's Paperless and embedding clients are explicitly closed
    before the new ones are built, matching the pattern in the OCR and
    classifier daemons (``ocr/daemon.py``, ``classifier/daemon.py``). Explicit
    close is the project convention: it releases each ``httpx`` connection pool
    deterministically and avoids assumptions about CPython finaliser timing for
    any cycle the OpenAI SDK may introduce. The indexer loop is single-threaded
    and rebuilds between cycles (no embed in flight), so closing the outgoing
    clients here cannot race a concurrent use.

    Args:
        settings: The freshly loaded configuration.
        old: The reconciler in use up to now — its ``store_writer`` is carried
            over to the new instance.

    Returns:
        A new :class:`~indexer.reconciler.Reconciler` built from *settings*,
        sharing the same :class:`~store.writer.StoreWriter` as *old*.
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
    """Run the reconciliation loop until shutdown is requested.

    Each iteration drives :func:`_run_one_cycle` — the real cycle body — and
    then waits.  Per cycle:

    0. Re-check :func:`common.config.current_settings`. When ``config_version``
       has moved the loop rebuilds *reconciler* via :func:`_rebuild_reconciler`,
       so a config save propagates with no restart (web-redesign §5). The
       ``RECONCILE_INTERVAL`` and ``DELETION_SWEEP_INTERVAL`` used to schedule
       this and every subsequent cycle are re-read from the live ``Settings``.
    1. Check for a manual-trigger sentinel file — consume it if present.
    2. Run ``reconciler.incremental_sync()``.
    3. Run ``reconciler.deletion_sweep()`` if the sweep interval has elapsed
       OR a manual trigger was pending at cycle start.
    4. ``store_writer.checkpoint()``.
    5. ``_interruptible_wait(settings.RECONCILE_INTERVAL)`` — returns early on
       shutdown or if a new sentinel appears.

    Steps 2–4 run inside a cycle-level ``try/except Exception``: a transient
    failure anywhere in the cycle is logged with its traceback and the loop
    falls through to the wait, so the next cycle retries.  A cycle failure
    never crashes the daemon and never advances the deletion-sweep clock.

    The loop is sequential; cycles never overlap.

    Args:
        reconciler: The Reconciler instance — replaced by a fresh one if
            :func:`current_settings` returns a new ``Settings`` on a cycle
            boundary.
        store_writer: The StoreWriter instance (used for checkpoint).
        settings: The initial Settings — replaced by a fresh snapshot if
            :func:`current_settings` returns a new value.
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
    # The mutable state carried across iterations: the (hot-reloadable)
    # reconciler and settings, and the monotonic time of the last completed
    # sweep.  ``last_sweep_at`` starts at 0 so the first cycle is always far
    # enough past it to run a deletion sweep.
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

        # Wait for the next cycle, waking early on shutdown or a new sentinel.
        # The interval is read live from settings so a hot-loaded change to
        # RECONCILE_INTERVAL takes effect from this wait onwards.  The
        # cycle_recorder is passed so the wait can beat idle periodically and
        # prevent the dashboard from reporting the indexer as "stopped" while
        # it is simply sleeping between cycles.
        _interruptible_wait(
            seconds=float(state.settings.RECONCILE_INTERVAL),
            sentinel_path=sentinel_path,
            cycle_recorder=cycle_recorder,
        )


@dataclass(frozen=True, slots=True)
class _LoopState:
    """The state :func:`_run_one_cycle` reads in and threads out each iteration.

    Frozen so a cycle returns a *new* state rather than mutating in place: the
    loop reassigns ``state = _run_one_cycle(state, ...)``, which makes the
    hot-reload replacement (a new ``reconciler`` + ``settings``) and the
    sweep-clock advance explicit in the return value.

    Attributes:
        reconciler: The current Reconciler — replaced by a fresh one when the
            config hot-reloads.
        settings: The current Settings snapshot — replaced on a config change.
        last_sweep_at: Monotonic seconds of the last completed deletion sweep;
            advanced only after a successful sweep so a failed cycle never moves
            the sweep clock.
    """

    reconciler: Reconciler
    settings: Settings
    last_sweep_at: float


def _run_one_cycle(
    state: _LoopState,
    *,
    store_writer: StoreWriter,
    app_db_path: str,
    sentinel_path: Path,
    clock: Callable[[], float],
    cycle_recorder: IndexerActivityRecorder | None,
) -> _LoopState:
    """Run a single reconciliation cycle and return the next loop state.

    This is the real cycle body :func:`_run_loop` drives every iteration — the
    hot-load config re-check, the sentinel consumption, the incremental sync,
    the due-when deletion sweep, and the checkpoint — wrapped in the cycle-level
    fault-isolation boundary.  It is a standalone function (not inlined in the
    loop) so tests drive the *real* cycle directly rather than a hand-copied
    parallel implementation (CODE_GUIDELINES §1.3, §11.4).

    Returns:
        A new :class:`_LoopState`: the reconciler and settings (replaced when
        the config hot-reloaded this cycle) and ``last_sweep_at`` (advanced only
        if a sweep completed).
    """
    reconciler = state.reconciler
    settings = state.settings
    last_sweep_at = state.last_sweep_at

    # Hot-load boundary (web-redesign §5): re-check config_version. When it has
    # moved, rebuild the config-derived resources for this and every later
    # cycle. current_settings() returns the SAME cached object when nothing
    # changed, so the `is` check is the whole cost.
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

    # Consume a rebuild trigger at cycle entry — wipe the index before this
    # cycle's sync so the sync re-indexes the whole archive (web-redesign spec
    # §5, Wave 6). The rebuild sentinel lives beside index.db, the same
    # directory as the reconcile sentinel.
    rebuild_sentinel = sentinel_path.parent / _REBUILD_SENTINEL_NAME
    needs_rebuild = _consume_sentinel(rebuild_sentinel)

    # Determine whether a deletion sweep is due this cycle. The interval is read
    # live from settings so a hot-loaded change takes effect now.
    elapsed = clock() - last_sweep_at
    run_sweep = manual_trigger or elapsed >= settings.DELETION_SWEEP_INTERVAL

    try:
        if needs_rebuild:
            _run_rebuild(store_writer, cycle_recorder)
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
        # outer-boundary catch) — a transient failure anywhere in the cycle (a
        # taxonomy-refresh network error, an incremental-paging drop, a
        # malformed Paperless document, a StoreError) must not crash the daemon.
        # The traceback is logged and the loop falls through to the wait so the
        # next cycle retries — mirroring common/daemon_loop.run_polling_threadpool.
        # last_sweep_at is assigned only after a successful sweep, so a failed
        # cycle never advances it: a missed sweep is retried next cycle.
        log.exception("indexer.cycle_failed")

    return _LoopState(
        reconciler=reconciler, settings=settings, last_sweep_at=last_sweep_at
    )


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
