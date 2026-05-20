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

The sweep cadence is driven by an injected ``clock`` (CODE_GUIDELINES §11.4):
a test passes a deterministic clock so the loop reaches a chosen elapsed time
without real time passing.  The flock-acquisition and ``_interruptible_wait``
tests live in test_daemon_main.py — the daemon's tests are split across two
files for the 500-line ceiling (CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# 1. Loop runs one cycle (incremental_sync + checkpoint), then waits
# ---------------------------------------------------------------------------


def test_loop_runs_incremental_sync_and_checkpoint_each_cycle(tmp_path: Path) -> None:
    """One cycle: incremental_sync called, then checkpoint, then the wait begins."""
    reconciler = _make_reconciler()
    store_writer = MagicMock()
    wait_count = 0

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        nonlocal wait_count
        wait_count += 1
        # Signal shutdown so the loop exits after the first cycle.
        shutdown_mod.request_shutdown()
        return False  # no manual trigger pending

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            reconcile_interval=300,
            deletion_sweep_interval=3600,
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

    shutdown_mod.request_shutdown()

    _run_loop(
        reconciler=reconciler,
        store_writer=store_writer,
        reconcile_interval=300,
        deletion_sweep_interval=3600,
        sentinel_path=tmp_path / "reconcile.request",
    )

    # The loop must have checked the flag at entry and exited without doing work.
    reconciler.incremental_sync.assert_not_called()
    store_writer.checkpoint.assert_not_called()


def test_shutdown_during_wait_exits_after_current_cycle(tmp_path: Path) -> None:
    """Shutdown requested during the wait does not run another full cycle."""
    reconciler = _make_reconciler()
    store_writer = MagicMock()
    cycles: list[int] = []

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        cycles.append(1)
        shutdown_mod.request_shutdown()
        return False

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            reconcile_interval=300,
            deletion_sweep_interval=3600,
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

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        # Must NOT raise — the failing first cycle is caught and isolated.
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            reconcile_interval=300,
            deletion_sweep_interval=3600,
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

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            reconcile_interval=300,
            deletion_sweep_interval=1,
            sentinel_path=tmp_path / "reconcile.request",
        )

    # Cycle 1 failed before the sweep; cycle 2 succeeded and swept exactly once.
    assert reconciler.incremental_sync.call_count == 2
    assert reconciler.deletion_sweep.call_count == 1


def test_deletion_sweep_failure_does_not_crash_loop(tmp_path: Path) -> None:
    """A deletion_sweep that raises is isolated by the same cycle boundary."""
    reconciler = _make_reconciler()
    store_writer = MagicMock()

    reconciler.deletion_sweep.side_effect = ConnectionError("sweep enumeration died")

    wait_count = 0

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        nonlocal wait_count
        wait_count += 1
        shutdown_mod.request_shutdown()
        return False

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        # Must NOT raise — the sweep failure is caught by the cycle boundary.
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            reconcile_interval=300,
            deletion_sweep_interval=1,
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
    sentinel_path = tmp_path / "reconcile.request"
    sentinel_path.touch()

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            reconcile_interval=300,
            deletion_sweep_interval=3600,
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

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            reconcile_interval=300,
            deletion_sweep_interval=3600,
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

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            reconcile_interval=300,
            deletion_sweep_interval=3600,
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
    sentinel_path = tmp_path / "reconcile.request"
    sentinel_path.touch()  # sentinel present at cycle start

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            reconcile_interval=300,
            deletion_sweep_interval=3600,
            sentinel_path=sentinel_path,
            clock=lambda: 1.0,
        )

    reconciler.deletion_sweep.assert_called_once()
