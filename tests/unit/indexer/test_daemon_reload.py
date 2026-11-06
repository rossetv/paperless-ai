"""Tests for indexer.daemon's hot-load, activity-recorder and rebuild paths.

Behavioural promises tested:

- The indexer builds its Settings through the hot-load accessor, so the
  ``config`` table in app.db overrides the environment.
- _run_loop records each sync and sweep through the optional cycle recorder,
  and runs unchanged without one.
- _run_one_cycle re-checks current_settings() every cycle and, when
  config_version has moved, rebuilds the Reconciler exactly once (web-redesign
  spec §5 hot-load contract); _rebuild_reconciler closes the outgoing clients.
- A rebuild.request sentinel at cycle entry wipes the index before the sync;
  without it rebuild_index is never called.

The core loop, failure-isolation and sweep-cadence tests live in
test_daemon.py — the daemon's tests are split across three files for the
500-line ceiling (CODE_GUIDELINES §3.1).  The shared mock builders and the
``_reset_shutdown`` autouse fixture come from tests/unit/indexer/conftest.py.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import common.shutdown as shutdown_mod
from indexer.daemon import _run_loop
from tests.unit.indexer.conftest import make_daemon_reconciler, make_daemon_settings


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
    settings = make_daemon_settings(deletion_sweep_interval=1)

    # Clock returns 100.0 on the elapsed check (>= interval 1), then 100.0
    # to record last_sweep_at.
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
    settings = make_daemon_settings()

    def fake_wait(seconds: float, sentinel_path: Path, **_kwargs: object) -> bool:
        shutdown_mod.request_shutdown()
        return False

    try:
        with (
            patch("indexer.daemon._loop._interruptible_wait", side_effect=fake_wait),
            patch("indexer.daemon._loop.current_settings", return_value=settings),
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


def test_indexer_run_one_cycle_rebuilds_on_a_config_change(tmp_path: Path) -> None:
    """_run_one_cycle re-checks config_version each cycle and, when it moves,
    rebuilds the reconciler — the indexer hot-reloads with no restart.

    This drives the REAL cycle body (CODE_GUIDELINES §1.3, §11.4): the same
    _run_one_cycle the production loop calls, not a parallel re-implementation.
    Two cycles are driven; a config write between them must trigger exactly one
    rebuild, and the rebuilt reconciler must be threaded into the next cycle's
    state.
    """
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
            # Cycle 1: config_version unchanged → no rebuild.
            state = _run_one_cycle(
                state,
                store_writer=store_writer,
                app_db_path=app_db,
                sentinel_path=tmp_path / "reconcile.request",
                clock=lambda: 1.0,
                cycle_recorder=None,
            )
            assert sum(rebuilds) == 0

            # A config write between cycles bumps config_version.
            bump_conn = connect(app_db)
            config_store.set_value(bump_conn, "RECONCILE_INTERVAL", "999")
            bump_conn.close()

            # Cycle 2: config_version moved → exactly one rebuild, and the new
            # reconciler is threaded into the returned state.
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
    """When a rebuild.request sentinel exists at cycle entry, _run_loop
    calls store_writer.rebuild_index() before the cycle's sync, then
    deletes the sentinel."""
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

    # The rebuild ran with the cycle's live settings — the model/dims the
    # re-embed will use are stamped into meta. Regression: a rebuild after a UI
    # model switch must not leave stale meta that re-embeds twice on next boot.
    store_writer.rebuild_index.assert_called_once_with(
        embedding_model=settings.EMBEDDING_MODEL,
        embedding_dimensions=settings.EMBEDDING_DIMENSIONS,
    )
    assert not rebuild_sentinel.exists()
    # The sync ran after the rebuild.
    assert reconciler.incremental_sync.called


def test_run_loop_does_not_rebuild_without_the_sentinel(tmp_path: Path) -> None:
    """No rebuild.request sentinel → rebuild_index is never called."""
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
    """On a config-change rebuild, both outgoing httpx clients are closed.

    Regression guard for the EmbeddingClient hot-reload leak: old.paperless and
    old.embedding_client must both be closed before the new reconciler is
    built, releasing their connection pools deterministically rather than
    leaving them to GC.
    """
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
