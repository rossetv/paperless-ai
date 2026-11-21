"""Tests for indexer.daemon._run_loop, the reconciliation daemon loop.

The sweep cadence is driven by an injected ``clock`` so a test reaches a chosen
elapsed time without real time passing.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import common.shutdown as shutdown_mod
from indexer.daemon import _run_loop
from tests.unit.indexer.conftest import make_daemon_reconciler, make_daemon_settings


def test_loop_runs_incremental_sync_and_checkpoint_each_cycle(tmp_path: Path) -> None:
    reconciler = make_daemon_reconciler()
    store_writer = MagicMock()
    settings = make_daemon_settings()
    wait_count = 0

    def fake_wait(seconds: float, sentinel_path: Path, **_kwargs: object) -> bool:
        nonlocal wait_count
        wait_count += 1
        shutdown_mod.request_shutdown()
        return False  # no manual trigger pending

    with (
        patch("indexer.daemon._loop._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon._loop.current_settings", return_value=settings),
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


def test_shutdown_ends_loop_promptly(tmp_path: Path) -> None:
    reconciler = make_daemon_reconciler()
    store_writer = MagicMock()
    settings = make_daemon_settings()

    shutdown_mod.request_shutdown()

    with patch("indexer.daemon._loop.current_settings", return_value=settings):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=tmp_path / "reconcile.request",
        )

    reconciler.incremental_sync.assert_not_called()
    store_writer.checkpoint.assert_not_called()


def test_shutdown_during_wait_exits_after_current_cycle(tmp_path: Path) -> None:
    reconciler = make_daemon_reconciler()
    store_writer = MagicMock()
    settings = make_daemon_settings()
    cycles: list[int] = []

    def fake_wait(seconds: float, sentinel_path: Path, **_kwargs: object) -> bool:
        cycles.append(1)
        shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._loop._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon._loop.current_settings", return_value=settings),
    ):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=tmp_path / "reconcile.request",
        )

    assert reconciler.incremental_sync.call_count == 1
    assert len(cycles) == 1


def test_cycle_failure_does_not_crash_loop_and_proceeds_to_next_cycle(
    tmp_path: Path,
) -> None:
    """A transient cycle failure is logged and the next cycle retries."""
    reconciler = make_daemon_reconciler()
    store_writer = MagicMock()
    settings = make_daemon_settings()

    reconciler.incremental_sync.side_effect = [
        ConnectionError("Paperless blipped mid-cycle"),
        MagicMock(indexed=1, metadata_only=0, skipped=0, failed=0, given_up=0),
    ]

    wait_count = 0

    def fake_wait(seconds: float, sentinel_path: Path, **_kwargs: object) -> bool:
        nonlocal wait_count
        wait_count += 1
        if wait_count >= 2:
            shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._loop._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon._loop.current_settings", return_value=settings),
    ):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=tmp_path / "reconcile.request",
        )

    assert reconciler.incremental_sync.call_count == 2
    assert wait_count == 2


def test_cycle_failure_does_not_advance_the_deletion_sweep_clock(
    tmp_path: Path,
) -> None:
    """The sweep is due on both cycles (interval 1, real monotonic clock), so a
    cycle that fails before sweeping leaves it to the next cycle."""
    reconciler = make_daemon_reconciler()
    store_writer = MagicMock()
    settings = make_daemon_settings(deletion_sweep_interval=1)

    reconciler.incremental_sync.side_effect = [
        RuntimeError("cycle 1 failed before the sweep"),
        MagicMock(indexed=0, metadata_only=0, skipped=0, failed=0, given_up=0),
    ]

    wait_count = 0

    def fake_wait(seconds: float, sentinel_path: Path, **_kwargs: object) -> bool:
        nonlocal wait_count
        wait_count += 1
        if wait_count >= 2:
            shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._loop._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon._loop.current_settings", return_value=settings),
    ):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=tmp_path / "reconcile.request",
        )

    assert reconciler.incremental_sync.call_count == 2
    assert reconciler.deletion_sweep.call_count == 1


def test_deletion_sweep_failure_does_not_crash_loop(tmp_path: Path) -> None:
    reconciler = make_daemon_reconciler()
    store_writer = MagicMock()
    settings = make_daemon_settings(deletion_sweep_interval=1)

    reconciler.deletion_sweep.side_effect = ConnectionError("sweep enumeration died")

    wait_count = 0

    def fake_wait(seconds: float, sentinel_path: Path, **_kwargs: object) -> bool:
        nonlocal wait_count
        wait_count += 1
        shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._loop._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon._loop.current_settings", return_value=settings),
    ):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=tmp_path / "reconcile.request",
        )

    assert reconciler.deletion_sweep.call_count == 1
    assert wait_count == 1


@pytest.mark.parametrize(
    ("failing_step", "expected_sweeps"),
    [("incremental_sync", 1), ("deletion_sweep", 2)],
)
def test_manual_trigger_stays_pending_until_its_sweep_completes(
    tmp_path: Path, failing_step: str, expected_sweeps: int
) -> None:
    """The sentinel is consumed at cycle 1's entry, then cycle 1 fails.

    The clock is fixed at 1.0, far short of the 3600 s interval, so only the
    still-pending trigger can make cycle 2 sweep; cycle 3 must not sweep.
    """
    reconciler = make_daemon_reconciler()
    step = getattr(reconciler, failing_step)
    step.side_effect = [RuntimeError("cycle 1 failed"), *[step.return_value] * 2]
    settings = make_daemon_settings()
    sentinel_path = tmp_path / "reconcile.request"
    sentinel_path.touch()
    waits = 0

    def fake_wait(seconds: float, sentinel_path: Path, **_kwargs: object) -> bool:
        nonlocal waits
        waits += 1
        if waits == 3:
            shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._loop._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon._loop.current_settings", return_value=settings),
    ):
        _run_loop(
            reconciler=reconciler,
            store_writer=MagicMock(),
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=sentinel_path,
            clock=lambda: 1.0,
        )

    assert reconciler.incremental_sync.call_count == 3
    assert reconciler.deletion_sweep.call_count == expected_sweeps


def test_sentinel_present_is_deleted_and_forces_deletion_sweep(tmp_path: Path) -> None:
    reconciler = make_daemon_reconciler()
    store_writer = MagicMock()
    settings = make_daemon_settings()
    sentinel_path = tmp_path / "reconcile.request"
    sentinel_path.touch()

    def fake_wait(seconds: float, sentinel_path: Path, **_kwargs: object) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._loop._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon._loop.current_settings", return_value=settings),
    ):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=sentinel_path,
        )

    assert not sentinel_path.exists()
    reconciler.deletion_sweep.assert_called_once()


def test_deletion_sweep_skipped_when_interval_not_elapsed(tmp_path: Path) -> None:
    """The clock returns 1.0, far short of the 3600 s interval."""
    reconciler = make_daemon_reconciler()
    store_writer = MagicMock()
    settings = make_daemon_settings()

    def fake_wait(seconds: float, sentinel_path: Path, **_kwargs: object) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._loop._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon._loop.current_settings", return_value=settings),
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
    """The clock returns 3601.0, past the 3600 s interval."""
    reconciler = make_daemon_reconciler()
    store_writer = MagicMock()
    settings = make_daemon_settings()

    def fake_wait(seconds: float, sentinel_path: Path, **_kwargs: object) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._loop._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon._loop.current_settings", return_value=settings),
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
    """The clock returns 1.0, so only the sentinel can cause the sweep."""
    reconciler = make_daemon_reconciler()
    store_writer = MagicMock()
    settings = make_daemon_settings()
    sentinel_path = tmp_path / "reconcile.request"
    sentinel_path.touch()  # sentinel present at cycle start

    def fake_wait(seconds: float, sentinel_path: Path, **_kwargs: object) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with (
        patch("indexer.daemon._loop._interruptible_wait", side_effect=fake_wait),
        patch("indexer.daemon._loop.current_settings", return_value=settings),
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
