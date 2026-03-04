from common.daemon_loop import run_polling_threadpool
from common.shutdown import request_shutdown, reset_shutdown


def test_run_polling_threadpool_processes_batch_and_continues_on_item_error():
    reset_shutdown()
    calls = {"fetch": 0, "before": 0}
    processed = []
    attempted = []

    def fetch_work():
        calls["fetch"] += 1
        return [1, 2, 3] if calls["fetch"] == 1 else []

    def before_each_batch(items):
        assert items == [1, 2, 3]
        calls["before"] += 1

    def process_item(item):
        attempted.append(item)
        if item == 2:
            raise RuntimeError("boom")
        processed.append(item)

    sleep_calls = {"count": 0}

    def sleep(_seconds):
        sleep_calls["count"] += 1
        # After the first loop iteration, stop the daemon.
        request_shutdown()

    run_polling_threadpool(
        daemon_name="test",
        fetch_work=fetch_work,
        process_item=process_item,
        poll_interval_seconds=15,
        max_workers=1,
        before_each_batch=before_each_batch,
        sleep=sleep,
    )

    assert calls["fetch"] == 1
    assert calls["before"] == 1
    assert attempted == [1, 2, 3]
    assert processed == [1, 3]
    assert sleep_calls["count"] == 1
    reset_shutdown()
