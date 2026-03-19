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

        with patch(f"{MODULE}.is_shutdown_requested", _make_shutdown_after(2)), \
             patch(f"{MODULE}.log") as mock_log:
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
            c for c in mock_log.info.call_args_list
            if "No work found" in str(c)
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

        with patch(f"{MODULE}.is_shutdown_requested", _shutdown), \
             patch(f"{MODULE}.log") as mock_log:
            run_polling_threadpool(
                daemon_name="mytest",
                fetch_work=fetch_work,
                process_item=process_item,
                poll_interval_seconds=5,
                max_workers=1,
                sleep=mock_sleep,
            )

        shutdown_calls = [
            c for c in mock_log.info.call_args_list
            if "Shutdown" in str(c) or "shutdown" in str(c)
        ]
        assert len(shutdown_calls) >= 1

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
