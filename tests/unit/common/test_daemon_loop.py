"""Tests for common.daemon_loop."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from common.daemon_loop import _safe_item_summary, run_polling_threadpool

MODULE = "common.daemon_loop"


def _make_shutdown_after(n_iterations: int):
    """Return an is_shutdown_requested replacement that returns False n times, then True."""
    counter = {"calls": 0}

    def _is_shutdown():
        counter["calls"] += 1
        return counter["calls"] > n_iterations

    return _is_shutdown


def _make_sleep_noop():
    """Return a no-op sleep that records calls."""
    mock_sleep = MagicMock()
    return mock_sleep


class TestRunPollingThreadpool:
    """Tests for run_polling_threadpool()."""

    def test_processes_batch_items_via_process_item_callable(self):
        items = [{"id": 1}, {"id": 2}]
        fetch_work = MagicMock(return_value=items)
        process_item = MagicMock()
        mock_sleep = _make_sleep_noop()

        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=1,
                sleep=mock_sleep,
            )

        assert process_item.call_count == 2

    def test_calls_before_each_batch_when_provided(self):
        items = [{"id": 1}]
        fetch_work = MagicMock(return_value=items)
        process_item = MagicMock()
        before_each_batch = MagicMock()
        mock_sleep = _make_sleep_noop()

        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=1,
                before_each_batch=before_each_batch,
                sleep=mock_sleep,
            )

        before_each_batch.assert_called_once_with(items)

    def test_logs_and_continues_on_item_processing_error(self):
        items = [{"id": 1}, {"id": 2}]
        fetch_work = MagicMock(return_value=items)
        call_count = {"n": 0}

        def failing_process(item):
            call_count["n"] += 1
            if item["id"] == 1:
                raise RuntimeError("item 1 failed")

        mock_sleep = _make_sleep_noop()

        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=fetch_work,
                process_item=failing_process,
                poll_interval_seconds=5,
                max_workers=1,
                sleep=mock_sleep,
            )

        assert call_count["n"] == 2

    def test_sleeps_between_iterations(self):
        fetch_work = MagicMock(return_value=[{"id": 1}])
        process_item = MagicMock()
        mock_sleep = _make_sleep_noop()

        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=10,
                max_workers=1,
                sleep=mock_sleep,
            )

        mock_sleep.assert_called_with(10)

    def test_handles_fetch_work_exception_gracefully(self):
        fetch_work = MagicMock(side_effect=OSError("fetch failed"))
        process_item = MagicMock()
        mock_sleep = _make_sleep_noop()

        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=1,
                sleep=mock_sleep,
            )

        process_item.assert_not_called()
        # Sleep was still called (error recovery sleep)
        mock_sleep.assert_called()

    def test_idle_logging_only_once(self):
        fetch_work = MagicMock(return_value=[])
        process_item = MagicMock()
        mock_sleep = _make_sleep_noop()

        with (
            patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(2)),
            patch(f"{MODULE}.log") as mock_log,
        ):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=1,
                sleep=mock_sleep,
            )

        # Assert — "No work found" logged only once despite two idle iterations
        idle_calls = [
            c for c in mock_log.info.call_args_list if "No work found" in str(c)
        ]
        assert len(idle_calls) == 1

    def test_no_before_each_batch_when_none(self):
        fetch_work = MagicMock(return_value=[{"id": 1}])
        process_item = MagicMock()
        mock_sleep = _make_sleep_noop()

        # Act — should not raise even without before_each_batch
        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=1,
                before_each_batch=None,
                sleep=mock_sleep,
            )

        process_item.assert_called_once()

    def test_poll_interval_seconds_clamped_to_min_1(self):
        fetch_work = MagicMock(return_value=[{"id": 1}])
        process_item = MagicMock()
        mock_sleep = _make_sleep_noop()

        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=-5,
                max_workers=1,
                sleep=mock_sleep,
            )

        mock_sleep.assert_called_with(1)

    def test_max_workers_clamped_to_min_1(self):
        fetch_work = MagicMock(return_value=[{"id": 1}])
        process_item = MagicMock()
        mock_sleep = _make_sleep_noop()

        # Act — max_workers=0 should be clamped to 1 and still work
        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=0,
                sleep=mock_sleep,
            )

        process_item.assert_called_once()

    def test_stops_on_shutdown_signal(self):
        fetch_work = MagicMock(return_value=[{"id": 1}])
        process_item = MagicMock()
        mock_sleep = _make_sleep_noop()

        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(0)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=1,
                sleep=mock_sleep,
            )

        fetch_work.assert_not_called()
        process_item.assert_not_called()

    def test_halt_check_skips_fetch_and_processing(self):
        # When halt_check reports a reason, the poll fetches and processes
        # nothing — the guarantee that a halted daemon spends no LLM tokens.
        fetch_work = MagicMock(return_value=[{"id": 1}])
        process_item = MagicMock()
        mock_sleep = _make_sleep_noop()

        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=1,
                halt_check=lambda: "halted for a test",
                sleep=mock_sleep,
            )

        fetch_work.assert_not_called()
        process_item.assert_not_called()

    def test_halt_check_returning_none_processes_normally(self):
        fetch_work = MagicMock(return_value=[{"id": 1}])
        process_item = MagicMock()
        mock_sleep = _make_sleep_noop()

        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=1,
                halt_check=lambda: None,
                sleep=mock_sleep,
            )

        process_item.assert_called_once()

    def test_halt_check_marks_the_cycle_outcome_halted(self):
        from common.daemon_loop import CycleOutcome

        outcomes: list[CycleOutcome] = []
        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=lambda: [{"id": 1}],
                process_item=MagicMock(),
                poll_interval_seconds=5,
                max_workers=1,
                halt_check=lambda: "halted for a test",
                on_cycle=outcomes.append,
                sleep=_make_sleep_noop(),
            )

        assert len(outcomes) == 1
        assert outcomes[0].halted is True
        assert outcomes[0].idle is False
        assert outcomes[0].processed == 0

    def test_logs_shutdown_message(self):
        fetch_work = MagicMock(return_value=[])
        process_item = MagicMock()
        mock_sleep = _make_sleep_noop()

        # We need is_shutdown_requested to return False once (to enter loop),
        # True on second call (to exit loop), then True for the final check
        call_count = {"n": 0}

        def _shutdown():
            call_count["n"] += 1
            # First call: enter loop; second call onwards: exit
            return call_count["n"] > 1

        with (
            patch(f"{MODULE}.is_shutdown_requested", _shutdown),
            patch(f"{MODULE}.log") as mock_log,
        ):
            run_polling_threadpool(
                daemon_name="mytest",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=1,
                sleep=mock_sleep,
            )

        shutdown_calls = [
            c
            for c in mock_log.info.call_args_list
            if "Shutdown" in str(c) or "shutdown" in str(c)
        ]
        assert len(shutdown_calls) >= 1


class TestHaltMidQueue:
    """A breaker that trips mid-pass stops further LLM calls within the batch.

    These cover the M2 fix: ``_poll_once`` only skips *new* polls, so a deep
    already-materialised queue is bounded by the per-item pre-call halt check
    and the chunked dispatch inside ``_process_batch``.
    """

    def test_a_trip_mid_batch_stops_processing_remaining_items(self):
        # The breaker trips after the 2nd item is processed; the remaining items
        # must short-circuit before their (expensive) process_item call runs.
        items = [{"id": i} for i in range(10)]
        fetch_work = MagicMock(return_value=items)
        processed: list[int] = []
        tripped = {"flag": False}

        def process_item(item):
            processed.append(item["id"])
            if len(processed) >= 2:
                tripped["flag"] = True  # systemic write-back failure detected

        # Single worker so completion order is deterministic; halt_check reads
        # the same flag the daemon's breaker would expose.
        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=1,
                halt_check=lambda: "halted" if tripped["flag"] else None,
                sleep=_make_sleep_noop(),
            )

        # Only the items up to the trip ran; the rest of the queue was skipped
        # without a process_item (and therefore without an LLM) call.
        assert processed == [0, 1]

    def test_halt_between_sub_batches_stops_dispatch(self):
        # With max_workers=2 the queue is dispatched in pairs. The breaker trips
        # during the first pair, so the second pair is never dispatched.
        items = [{"id": i} for i in range(6)]
        processed: list[int] = []
        tripped = {"flag": False}

        def process_item(item):
            processed.append(item["id"])
            tripped["flag"] = True  # any failure trips it for this test

        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=MagicMock(return_value=items),
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=2,
                halt_check=lambda: "halted" if tripped["flag"] else None,
                sleep=_make_sleep_noop(),
            )

        # At most the first sub-batch (2 items) ran; the remaining four were
        # never dispatched. The exact count within the first pair depends on
        # scheduling, but the queue must not have been processed in full.
        assert len(processed) <= 2
        assert set(processed).issubset({0, 1})

    def test_processed_count_reflects_dispatched_not_queue_depth(self):
        # When a halt cuts a batch short, on_cycle's outcome.processed must be
        # the number actually dispatched — the heartbeat reports real work, not
        # the materialised queue depth.
        from common.daemon_loop import CycleOutcome

        items = [{"id": i} for i in range(10)]
        outcomes: list[CycleOutcome] = []
        processed: list[int] = []
        tripped = {"flag": False}

        def process_item(item):
            processed.append(item["id"])
            if len(processed) >= 3:
                tripped["flag"] = True

        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=MagicMock(return_value=items),
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=1,
                halt_check=lambda: "halted" if tripped["flag"] else None,
                on_cycle=outcomes.append,
                sleep=_make_sleep_noop(),
            )

        assert len(outcomes) == 1
        assert outcomes[0].processed == len(processed)
        assert outcomes[0].processed < len(items)
        assert outcomes[0].idle is False

    def test_no_halt_check_processes_the_whole_queue(self):
        # Regression: with no halt_check the entire materialised queue is still
        # processed exactly once — the conservative non-breaker path is unchanged.
        items = [{"id": i} for i in range(7)]
        process_item = MagicMock()

        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(1)):
            run_polling_threadpool(
                daemon_name="test",
                fetch_work=MagicMock(return_value=items),
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=3,
                sleep=_make_sleep_noop(),
            )

        assert process_item.call_count == 7


class TestSafeItemSummary:
    """Tests for _safe_item_summary()."""

    def test_returns_doc_id_for_dict_with_id(self):
        item = {"id": 42, "title": "Test"}

        result = _safe_item_summary(item)

        assert result == "doc_id=42"

    def test_returns_dict_keys_for_dict_without_id(self):
        item = {"name": "foo", "value": "bar"}

        result = _safe_item_summary(item)

        assert "dict_keys=" in result
        assert "name" in result
        assert "value" in result

    def test_returns_str_for_non_dict(self):
        item = "hello-world"

        result = _safe_item_summary(item)

        assert result == "hello-world"

    def test_returns_unprintable_for_objects_that_raise_in_str(self):
        class BadStr:
            def __str__(self):
                raise ValueError("cannot stringify")

        item = BadStr()

        result = _safe_item_summary(item)

        assert result == "<unprintable>"


def test_before_each_poll_runs_at_the_top_of_every_iteration() -> None:
    """run_polling_threadpool calls before_each_poll once per poll, before
    fetch_work — the hot-load boundary for the tag daemons."""
    from common.daemon_loop import run_polling_threadpool
    from common.shutdown import request_shutdown, reset_shutdown

    calls: list[str] = []
    polls = {"n": 0}

    def fetch_work() -> list[int]:
        polls["n"] += 1
        calls.append("fetch")
        if polls["n"] >= 2:
            request_shutdown()
        return []

    try:
        run_polling_threadpool(
            daemon_name="test",
            fetch_work=fetch_work,
            process_item=lambda _item: None,
            poll_interval_seconds=1,
            max_workers=1,
            before_each_poll=lambda: calls.append("hook"),
            sleep=lambda _s: None,
        )
    finally:
        reset_shutdown()

    # The hook precedes fetch on every iteration.
    assert calls[:4] == ["hook", "fetch", "hook", "fetch"]


def test_on_cycle_is_called_after_each_poll_with_the_outcome() -> None:
    """run_polling_threadpool invokes on_cycle once per poll, passing the
    processed-item count and the idle flag for that iteration."""
    from common.daemon_loop import CycleOutcome, run_polling_threadpool
    from common.shutdown import reset_shutdown

    outcomes: list[CycleOutcome] = []
    # Two work items the first poll, none the second, then stop.
    batches = [[{"id": 1}, {"id": 2}], []]
    polls = iter(batches)

    def fetch_work() -> list[dict]:
        try:
            return next(polls)
        except StopIteration:
            from common.shutdown import request_shutdown

            request_shutdown()
            return []

    try:
        run_polling_threadpool(
            daemon_name="test",
            fetch_work=fetch_work,
            process_item=lambda _item: None,
            poll_interval_seconds=1,
            max_workers=1,
            on_cycle=outcomes.append,
            sleep=lambda _s: None,
        )
    finally:
        reset_shutdown()

    # At least the two real polls were observed.
    assert len(outcomes) >= 2
    assert outcomes[0].processed == 2
    assert outcomes[0].idle is False
    assert outcomes[1].processed == 0
    assert outcomes[1].idle is True


def test_a_failing_on_cycle_callback_does_not_crash_the_loop() -> None:
    """A buggy on_cycle hook is isolated — the loop keeps running."""
    from common.daemon_loop import run_polling_threadpool
    from common.shutdown import reset_shutdown

    polls = iter([[], []])

    def fetch_work() -> list[dict]:
        try:
            return next(polls)
        except StopIteration:
            from common.shutdown import request_shutdown

            request_shutdown()
            return []

    def boom(_outcome) -> None:
        raise RuntimeError("buggy hook")

    try:
        # Must complete without propagating the RuntimeError.
        run_polling_threadpool(
            daemon_name="test",
            fetch_work=fetch_work,
            process_item=lambda _item: None,
            poll_interval_seconds=1,
            max_workers=1,
            on_cycle=boom,
            sleep=lambda _s: None,
        )
    finally:
        reset_shutdown()
