"""Extended tests for common.daemon_loop — idle states and error recovery."""

from common.daemon_loop import _safe_item_summary, run_polling_threadpool
from common.shutdown import request_shutdown, reset_shutdown


def test_idle_logging_only_once():
    """After the first idle log, subsequent empty polls should not re-log."""
    reset_shutdown()
    fetch_calls = {"count": 0}

    def fetch_work():
        fetch_calls["count"] += 1
        return []

    sleep_count = {"n": 0}

    def sleep(_seconds):
        sleep_count["n"] += 1
        if sleep_count["n"] >= 3:
            request_shutdown()

    run_polling_threadpool(
        daemon_name="test",
        fetch_work=fetch_work,
        process_item=lambda _: None,
        poll_interval_seconds=1,
        max_workers=1,
        sleep=sleep,
    )

    assert fetch_calls["count"] == 3
    assert sleep_count["n"] == 3
    reset_shutdown()


def test_no_before_each_batch_when_not_set():
    """When before_each_batch is None, the loop still processes items."""
    reset_shutdown()
    processed = []

    def fetch_work():
        return [1] if not processed else []

    def sleep(_seconds):
        request_shutdown()

    run_polling_threadpool(
        daemon_name="test",
        fetch_work=fetch_work,
        process_item=lambda item: processed.append(item),
        poll_interval_seconds=1,
        max_workers=1,
        before_each_batch=None,
        sleep=sleep,
    )

    assert processed == [1]
    reset_shutdown()


def test_unexpected_error_in_fetch_work_recovered():
    """An error in fetch_work is caught and the loop sleeps then retries."""
    reset_shutdown()
    calls = {"count": 0}

    def fetch_work():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("transient error")
        return []

    sleep_count = {"n": 0}

    def sleep(_seconds):
        sleep_count["n"] += 1
        if sleep_count["n"] >= 2:
            request_shutdown()

    run_polling_threadpool(
        daemon_name="test",
        fetch_work=fetch_work,
        process_item=lambda _: None,
        poll_interval_seconds=1,
        max_workers=1,
        sleep=sleep,
    )

    assert calls["count"] >= 2
    reset_shutdown()


def test_poll_interval_clamped_to_minimum():
    """Poll interval of 0 is clamped to 1."""
    reset_shutdown()
    actual_intervals = []

    def fetch_work():
        return []

    def sleep(seconds):
        actual_intervals.append(seconds)
        request_shutdown()

    run_polling_threadpool(
        daemon_name="test",
        fetch_work=fetch_work,
        process_item=lambda _: None,
        poll_interval_seconds=0,
        max_workers=1,
        sleep=sleep,
    )

    assert actual_intervals[0] == 1
    reset_shutdown()


# ---------------------------------------------------------------------------
# _safe_item_summary
# ---------------------------------------------------------------------------


def test_safe_item_summary_dict_with_id():
    assert _safe_item_summary({"id": 42}) == "doc_id=42"


def test_safe_item_summary_dict_without_id():
    result = _safe_item_summary({"name": "test"})
    assert "dict_keys" in result


def test_safe_item_summary_non_dict():
    assert _safe_item_summary(42) == "42"


def test_safe_item_summary_unprintable():
    class BadObj:
        def __str__(self):
            raise RuntimeError("boom")

    assert _safe_item_summary(BadObj()) == "<unprintable>"


# ---------------------------------------------------------------------------
# Graceful shutdown via shutdown flag
# ---------------------------------------------------------------------------


def test_shutdown_flag_stops_loop():
    """When shutdown is requested, the loop exits without processing more items."""
    reset_shutdown()
    processed = []

    def fetch_work():
        return [1] if not processed else []

    def sleep(_seconds):
        # Request shutdown during the sleep after the first batch
        request_shutdown()

    run_polling_threadpool(
        daemon_name="test",
        fetch_work=fetch_work,
        process_item=lambda item: processed.append(item),
        poll_interval_seconds=1,
        max_workers=1,
        sleep=sleep,
    )

    assert processed == [1]
    reset_shutdown()
