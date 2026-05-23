"""Tests for indexer.daemon._run_loop — the reconciliation daemon loop.

Behavioural promises tested:

1. The loop runs one incremental_sync + checkpoint each cycle, then waits.
2. is_shutdown_requested() becoming True ends the loop promptly and the loop
   does not run another cycle.
3. A present reconcile.request sentinel forces the next cycle to include a
   deletion_sweep.
4. A cycle-level failure is isolated; the loop survives and the next cycle
   retries, and a failed cycle never advances the deletion-sweep clock.
5. The deletion sweep runs only when DELETION_SWEEP_INTERVAL has elapsed since
   the last sweep — or a manual trigger forced a full cycle.
6. _run_loop re-checks current_settings() at the top of every cycle and, when
   config_version has moved, rebuilds the Reconciler exactly once (web-redesign
   spec §5 hot-load contract).

The sweep cadence is driven by an injected ``clock`` (CODE_GUIDELINES §11.4):
a test passes a deterministic clock so the loop reaches a chosen elapsed time
without real time passing.  The flock-acquisition and ``_interruptible_wait``
tests live in test_daemon_main.py — the daemon's tests are split across two
files for the 500-line ceiling (CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import common.shutdown as shutdown_mod
from indexer.daemon import _run_loop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reconciler() -> MagicMock:
    """Return a mock Reconciler whose two operations report empty outcomes."""
    reconciler = MagicMock()
    reconciler.incremental_sync.return_value = MagicMock(
        indexed=0, metadata_only=0, skipped=0, failed=0, given_up=0
    )
    reconciler.deletion_sweep.return_value = MagicMock(
        pruned=0, aborted=False, candidates=0
    )
    return reconciler


def _make_settings(
    reconcile_interval: int = 300, deletion_sweep_interval: int = 3600
) -> MagicMock:
    """Return a MagicMock standing in for Settings with the loop intervals."""
    settings = MagicMock()
    settings.RECONCILE_INTERVAL = reconcile_interval
    settings.DELETION_SWEEP_INTERVAL = deletion_sweep_interval
    return settings


# ---------------------------------------------------------------------------
# 1. Loop runs one cycle (incremental_sync + checkpoint), then waits
# ---------------------------------------------------------------------------


def test_loop_runs_incremental_sync_and_checkpoint_each_cycle(tmp_path: Path) -> None:
    """One cycle: incremental_sync called, then checkpoint, then the wait begins."""
    reconciler = _make_reconciler()
    store_writer = MagicMock()
    settings = _make_settings()
    wait_count = 0

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        nonlocal wait_count
        wait_count += 1
        # Signal shutdown so the loop exits after the first cycle.
        shutdown_mod.request_shutdown()
        return False  # no manual trigger pending

    with (
        patch("indexer.daemon._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon.current_settings", return_value=settings),
    ):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=tmp_path / "reconcile.request",
        )

    reconciler.incremental_sync.assert_called_once()
    store_writer.checkpoint.assert_called_once()
    assert wait_count == 1


# ---------------------------------------------------------------------------
# 2. Shutdown flag ends the loop promptly
# ---------------------------------------------------------------------------


def test_shutdown_ends_loop_promptly(tmp_path: Path) -> None:
    """Requesting shutdown before the loop runs causes it to exit immediately."""
    reconciler = _make_reconciler()
    store_writer = MagicMock()
    settings = _make_settings()

    shutdown_mod.request_shutdown()

    with patch("indexer.daemon.current_settings", return_value=settings):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=tmp_path / "reconcile.request",
        )

    # The loop must have checked the flag at entry and exited without doing work.
    reconciler.incremental_sync.assert_not_called()
    store_writer.checkpoint.assert_not_called()


def test_shutdown_during_wait_exits_after_current_cycle(tmp_path: Path) -> None:
    """Shutdown requested during the wait does not run another full cycle."""
    reconciler = _make_reconciler()
    store_writer = MagicMock()
    settings = _make_settings()
    cycles: list[int] = []

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        cycles.append(1)
        shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon.current_settings", return_value=settings),
    ):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=tmp_path / "reconcile.request",
        )

    # Exactly one cycle ran before the loop noticed shutdown.
    assert reconciler.incremental_sync.call_count == 1
    assert len(cycles) == 1


# ---------------------------------------------------------------------------
# 4. A cycle-level failure does not crash the daemon
# ---------------------------------------------------------------------------


def test_cycle_failure_does_not_crash_loop_and_proceeds_to_next_cycle(
    tmp_path: Path,
) -> None:
    """An incremental_sync that raises on the first cycle must not kill the loop.

    The cycle body is wrapped in an exception boundary (CODE_GUIDELINES §6.4)
    mirroring common/daemon_loop: a transient cycle-level failure is logged and
    the loop falls through to the wait, so the next cycle retries.
    """
    reconciler = _make_reconciler()
    store_writer = MagicMock()
    settings = _make_settings()

    # First call raises (transient failure); second call succeeds.
    reconciler.incremental_sync.side_effect = [
        ConnectionError("Paperless blipped mid-cycle"),
        MagicMock(indexed=1, metadata_only=0, skipped=0, failed=0, given_up=0),
    ]

    wait_count = 0

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        nonlocal wait_count
        wait_count += 1
        # Let two cycles run, then stop the loop.
        if wait_count >= 2:
            shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon.current_settings", return_value=settings),
    ):
        # Must NOT raise — the failing first cycle is caught and isolated.
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=tmp_path / "reconcile.request",
        )

    # The loop survived the failure and ran a second cycle.
    assert reconciler.incremental_sync.call_count == 2
    assert wait_count == 2


def test_cycle_failure_does_not_advance_the_deletion_sweep_clock(
    tmp_path: Path,
) -> None:
    """A failed cycle must not advance the sweep clock — the sweep retries next cycle.

    The sweep is due on the first cycle (last sweep at 0, interval 1).
    incremental_sync raises before the sweep runs, so the sweep must run on the
    next (successful) cycle.  The default monotonic clock makes "elapsed" far
    larger than the interval on both cycles.
    """
    reconciler = _make_reconciler()
    store_writer = MagicMock()
    settings = _make_settings(deletion_sweep_interval=1)

    reconciler.incremental_sync.side_effect = [
        RuntimeError("cycle 1 failed before the sweep"),
        MagicMock(indexed=0, metadata_only=0, skipped=0, failed=0, given_up=0),
    ]

    wait_count = 0

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        nonlocal wait_count
        wait_count += 1
        if wait_count >= 2:
            shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon.current_settings", return_value=settings),
    ):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=tmp_path / "reconcile.request",
        )

    # Cycle 1 failed before the sweep; cycle 2 succeeded and swept exactly once.
    assert reconciler.incremental_sync.call_count == 2
    assert reconciler.deletion_sweep.call_count == 1


def test_deletion_sweep_failure_does_not_crash_loop(tmp_path: Path) -> None:
    """A deletion_sweep that raises is isolated by the same cycle boundary."""
    reconciler = _make_reconciler()
    store_writer = MagicMock()
    settings = _make_settings(deletion_sweep_interval=1)

    reconciler.deletion_sweep.side_effect = ConnectionError("sweep enumeration died")

    wait_count = 0

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        nonlocal wait_count
        wait_count += 1
        shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon.current_settings", return_value=settings),
    ):
        # Must NOT raise — the sweep failure is caught by the cycle boundary.
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=tmp_path / "reconcile.request",
        )

    assert reconciler.deletion_sweep.call_count == 1
    # The loop still reached the wait despite the sweep blowing up.
    assert wait_count == 1


# ---------------------------------------------------------------------------
# 3. Manual-trigger sentinel forces a deletion_sweep
# ---------------------------------------------------------------------------


def test_sentinel_present_is_deleted_and_forces_deletion_sweep(tmp_path: Path) -> None:
    """A reconcile.request sentinel is deleted and the next cycle runs deletion_sweep."""
    reconciler = _make_reconciler()
    store_writer = MagicMock()
    settings = _make_settings()
    sentinel_path = tmp_path / "reconcile.request"
    sentinel_path.touch()

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon.current_settings", return_value=settings),
    ):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=sentinel_path,
        )

    # The sentinel must have been consumed (deleted) before the loop waited.
    assert not sentinel_path.exists()
    # A manual trigger at cycle-start forces a deletion_sweep regardless of
    # whether the interval has elapsed.
    reconciler.deletion_sweep.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Deletion sweep runs only when interval elapsed (or manual trigger)
# ---------------------------------------------------------------------------


def test_deletion_sweep_skipped_when_interval_not_elapsed(tmp_path: Path) -> None:
    """No deletion_sweep when DELETION_SWEEP_INTERVAL has not elapsed.

    The injected clock returns 1.0 throughout, so on the first cycle
    ``elapsed = clock() - last_sweep_at`` is ``1.0 - 0.0`` — far short of the
    3600s interval.
    """
    reconciler = _make_reconciler()
    store_writer = MagicMock()
    settings = _make_settings()

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon.current_settings", return_value=settings),
    ):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=tmp_path / "reconcile.request",
            clock=lambda: 1.0,
        )

    reconciler.deletion_sweep.assert_not_called()


def test_deletion_sweep_runs_when_interval_elapsed(tmp_path: Path) -> None:
    """deletion_sweep is called when DELETION_SWEEP_INTERVAL seconds have elapsed.

    The clock returns 3601.0, so on the first cycle ``elapsed`` is
    ``3601.0 - 0.0`` — past the 3600s interval.
    """
    reconciler = _make_reconciler()
    store_writer = MagicMock()
    settings = _make_settings()

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon.current_settings", return_value=settings),
    ):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=tmp_path / "reconcile.request",
            clock=lambda: 3601.0,
        )

    reconciler.deletion_sweep.assert_called_once()


def test_deletion_sweep_runs_on_manual_trigger_regardless_of_interval(
    tmp_path: Path,
) -> None:
    """A manual trigger forces deletion_sweep even if the interval has not elapsed.

    The clock returns 1.0 — far short of the interval — so only the sentinel
    can be responsible for the sweep running.
    """
    reconciler = _make_reconciler()
    store_writer = MagicMock()
    settings = _make_settings()
    sentinel_path = tmp_path / "reconcile.request"
    sentinel_path.touch()  # sentinel present at cycle start

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon.current_settings", return_value=settings),
    ):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=sentinel_path,
            clock=lambda: 1.0,
        )

    reconciler.deletion_sweep.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Hot-load: config changes between cycles trigger a Reconciler rebuild
# ---------------------------------------------------------------------------


def test_indexer_loads_settings_from_app_db(tmp_path: Path) -> None:
    """The indexer builds Settings via the hot-load accessor, so the config
    table overrides the environment — the indexer is on config-in-database."""
    from appdb import config as config_store
    from appdb.connection import connect
    from appdb.schema import ensure_schema
    from common.config import current_settings

    app_db = str(tmp_path / "app.db")
    conn = connect(app_db)
    ensure_schema(conn)
    config_store.set_value(conn, "RECONCILE_INTERVAL", "777")
    conn.close()

    env = {
        "APP_DB_PATH": app_db,
        "PAPERLESS_TOKEN": "env-token",
        "OPENAI_API_KEY": "env-api-key",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = current_settings()

    # This is exactly the call indexer.daemon.main() now makes.
    assert settings.RECONCILE_INTERVAL == 777
    assert settings.APP_DB_PATH == app_db


def test_run_loop_records_each_cycle_through_the_recorder() -> None:
    """_run_loop calls the recorder's record_sync after the sync and
    record_sweep after the sweep, with the cycle reports."""
    from pathlib import Path
    from unittest.mock import MagicMock

    from indexer.daemon import _run_loop
    from indexer.reconciler import SyncReport
    from indexer.reconciler._sweep import SweepReport

    # A reconciler whose two operations return canned reports.
    reconciler = MagicMock()
    reconciler.incremental_sync.return_value = SyncReport(
        indexed=2, metadata_only=0, skipped=0, failed=0, given_up=0
    )
    reconciler.deletion_sweep.return_value = SweepReport(
        pruned=1, aborted=False, candidates=1
    )
    store_writer = MagicMock()
    recorder = MagicMock()

    # A clock that advances so the first cycle runs a sweep, then a
    # shutdown is requested so the loop exits after one cycle.
    settings = _make_settings(deletion_sweep_interval=1)

    # Clock returns 100.0 on the elapsed check (>= interval 1), then 100.0
    # to record last_sweep_at.
    ticks = iter([100.0, 100.0])

    def clock() -> float:
        try:
            return next(ticks)
        except StopIteration:
            return 200.0

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        shutdown_mod.request_shutdown()
        return False

    try:
        with (
            patch("indexer.daemon._interruptible_wait", side_effect=fake_wait),
            patch("indexer.daemon.current_settings", return_value=settings),
        ):
            _run_loop(
                reconciler=reconciler,
                store_writer=store_writer,
                settings=settings,
                app_db_path="/nonexistent/app.db",
                sentinel_path=Path("/nonexistent/reconcile.request"),
                clock=clock,
                cycle_recorder=recorder,
            )
    finally:
        shutdown_mod.reset_shutdown()

    assert recorder.record_sync.called
    sync_call = recorder.record_sync.call_args
    assert sync_call.args[0].indexed == 2
    assert recorder.record_sweep.called
    assert recorder.record_sweep.call_args.args[0].pruned == 1


def test_run_loop_works_without_a_recorder() -> None:
    """cycle_recorder is optional — the loop runs unchanged when it is None
    (the existing behaviour is preserved)."""
    from pathlib import Path
    from unittest.mock import MagicMock

    from indexer.daemon import _run_loop
    from indexer.reconciler import SyncReport

    reconciler = MagicMock()
    reconciler.incremental_sync.return_value = SyncReport(
        indexed=0, metadata_only=0, skipped=0, failed=0, given_up=0
    )
    settings = _make_settings()

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        shutdown_mod.request_shutdown()
        return False

    try:
        with (
            patch("indexer.daemon._interruptible_wait", side_effect=fake_wait),
            patch("indexer.daemon.current_settings", return_value=settings),
        ):
            # Must not raise — cycle_recorder defaults to None.
            _run_loop(
                reconciler=reconciler,
                store_writer=MagicMock(),
                settings=settings,
                app_db_path="/nonexistent/app.db",
                sentinel_path=Path("/nonexistent/reconcile.request"),
            )
    finally:
        shutdown_mod.reset_shutdown()


def test_indexer_run_loop_rebuilds_on_a_config_change(tmp_path: Path) -> None:
    """_run_loop re-checks config_version each cycle and, when it moves,
    rebuilds the reconciler — the indexer hot-reloads with no restart."""
    from appdb import config as config_store
    from appdb.connection import connect
    from appdb.schema import ensure_schema
    from common.config import current_settings
    from indexer import daemon as indexer_daemon

    app_db = str(tmp_path / "app.db")
    conn = connect(app_db)
    ensure_schema(conn)
    conn.close()

    env = {
        "APP_DB_PATH": app_db,
        "INDEX_DB_PATH": str(tmp_path / "index.db"),
        "PAPERLESS_TOKEN": "env-token",
        "OPENAI_API_KEY": "env-api-key",
    }
    rebuilds: list[int] = []

    def _record_rebuild(settings, old):
        rebuilds.append(1)
        return old

    with patch.dict(os.environ, env, clear=True):
        current_settings(app_db)  # prime the cache so the first cycle sees no change
        with patch.object(
            indexer_daemon,
            "_rebuild_reconciler",
            side_effect=_record_rebuild,
        ):
            # Drive two cycles: a config write between them must trigger
            # exactly one rebuild.
            def _bump_config() -> None:
                bump_conn = connect(app_db)
                config_store.set_value(bump_conn, "RECONCILE_INTERVAL", "999")
                bump_conn.close()

            indexer_daemon._run_loop_for_test(
                app_db_path=app_db,
                cycles=2,
                on_cycle_1=_bump_config,
            )
    assert sum(rebuilds) == 1
