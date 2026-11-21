"""Tests for indexer.daemon's hot-load, activity-recorder and rebuild paths."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import common.shutdown as shutdown_mod
from indexer.daemon import _run_loop
from tests.unit.indexer.conftest import make_daemon_reconciler, make_daemon_settings


def test_indexer_loads_settings_from_app_db(tmp_path: Path) -> None:
    """The hot-load accessor lets the app.db config table override the env."""
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

    assert settings.RECONCILE_INTERVAL == 777
    assert settings.APP_DB_PATH == app_db


def test_run_loop_records_each_cycle_through_the_recorder() -> None:
    from pathlib import Path
    from unittest.mock import MagicMock

    from indexer.daemon import _run_loop
    from indexer.reconciler import SyncReport
    from indexer.reconciler._sweep import SweepReport

    reconciler = MagicMock()
    reconciler.incremental_sync.return_value = SyncReport(
        indexed=2, metadata_only=0, skipped=0, failed=0, given_up=0
    )
    reconciler.deletion_sweep.return_value = SweepReport(
        pruned=1, aborted=False, candidates=1
    )
    store_writer = MagicMock()
    recorder = MagicMock()

    settings = make_daemon_settings(deletion_sweep_interval=1)

    # 100.0 for the elapsed check (>= interval 1), then 100.0 for last_sweep_at.
    ticks = iter([100.0, 100.0])

    def clock() -> float:
        try:
            return next(ticks)
        except StopIteration:
            return 200.0

    def fake_wait(seconds: float, sentinel_path: Path, **_kwargs: object) -> bool:
        shutdown_mod.request_shutdown()
        return False

    try:
        with (
            patch("indexer.daemon._loop._interruptible_wait", side_effect=fake_wait),
            patch("indexer.daemon._loop.current_settings", return_value=settings),
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
    from pathlib import Path
    from unittest.mock import MagicMock

    from indexer.daemon import _run_loop
    from indexer.reconciler import SyncReport

    reconciler = MagicMock()
    reconciler.incremental_sync.return_value = SyncReport(
        indexed=0, metadata_only=0, skipped=0, failed=0, given_up=0
    )
    settings = make_daemon_settings()

    def fake_wait(seconds: float, sentinel_path: Path, **_kwargs: object) -> bool:
        shutdown_mod.request_shutdown()
        return False

    try:
        with (
            patch("indexer.daemon._loop._interruptible_wait", side_effect=fake_wait),
            patch("indexer.daemon._loop.current_settings", return_value=settings),
        ):
            _run_loop(
                reconciler=reconciler,
                store_writer=MagicMock(),
                settings=settings,
                app_db_path="/nonexistent/app.db",
                sentinel_path=Path("/nonexistent/reconcile.request"),
            )
    finally:
        shutdown_mod.reset_shutdown()


def test_indexer_run_one_cycle_rebuilds_on_a_config_change(tmp_path: Path) -> None:
    """A config write between two cycles triggers exactly one reconciler rebuild,
    and the rebuilt reconciler is threaded into the returned state."""
    from appdb import config as config_store
    from appdb.connection import connect
    from appdb.schema import ensure_schema
    from common.config import current_settings
    from indexer.daemon import _LoopState, _run_one_cycle
    from indexer.daemon import _loop as daemon_loop

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
    rebuilt_reconciler = make_daemon_reconciler()

    def _record_rebuild(settings, old):
        rebuilds.append(1)
        return rebuilt_reconciler

    with patch.dict(os.environ, env, clear=True):
        initial_settings = current_settings(app_db)  # prime: cycle 1 sees no change
        store_writer = MagicMock()
        state = _LoopState(
            reconciler=make_daemon_reconciler(),
            settings=initial_settings,
            last_sweep_at=0.0,
        )
        with patch.object(
            daemon_loop,
            "_rebuild_reconciler",
            side_effect=_record_rebuild,
        ):
            state = _run_one_cycle(
                state,
                store_writer=store_writer,
                app_db_path=app_db,
                sentinel_path=tmp_path / "reconcile.request",
                clock=lambda: 1.0,
                cycle_recorder=None,
            )
            assert sum(rebuilds) == 0

            bump_conn = connect(app_db)
            config_store.set_value(bump_conn, "RECONCILE_INTERVAL", "999")
            bump_conn.close()

            state = _run_one_cycle(
                state,
                store_writer=store_writer,
                app_db_path=app_db,
                sentinel_path=tmp_path / "reconcile.request",
                clock=lambda: 1.0,
                cycle_recorder=None,
            )

    assert sum(rebuilds) == 1
    assert state.reconciler is rebuilt_reconciler


def test_run_loop_rebuilds_when_the_rebuild_sentinel_is_present(
    tmp_path: Path,
) -> None:
    reconciler = make_daemon_reconciler()
    store_writer = MagicMock()
    settings = make_daemon_settings()

    sentinel = tmp_path / "reconcile.request"
    rebuild_sentinel = tmp_path / "rebuild.request"
    rebuild_sentinel.touch()

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
            sentinel_path=sentinel,
        )

    # The rebuild stamps the live settings' model/dims into meta; stale meta
    # after a UI model switch would re-embed everything again on next boot.
    store_writer.rebuild_index.assert_called_once_with(
        embedding_model=settings.EMBEDDING_MODEL,
        embedding_dimensions=settings.EMBEDDING_DIMENSIONS,
    )
    assert not rebuild_sentinel.exists()
    assert reconciler.incremental_sync.called


def test_run_loop_does_not_rebuild_without_the_sentinel(tmp_path: Path) -> None:
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
        )
    assert not store_writer.rebuild_index.called


def test_rebuild_reconciler_closes_old_paperless_and_embedding_clients() -> None:
    """Closing the outgoing httpx clients releases their pools instead of
    leaving them to GC."""
    from indexer.daemon import _rebuild_reconciler

    old = MagicMock()
    settings = MagicMock()
    with (
        patch("indexer.daemon._loop.configure_logging"),
        patch("indexer.daemon._loop.setup_libraries"),
        patch("indexer.daemon._loop.llm_limiter"),
        patch("indexer.daemon._loop.PaperlessClient"),
        patch("indexer.daemon._loop.EmbeddingClient"),
        patch("indexer.daemon._loop.Reconciler"),
    ):
        _rebuild_reconciler(settings, old)

    old.paperless.close.assert_called_once_with()
    old.embedding_client.close.assert_called_once_with()
