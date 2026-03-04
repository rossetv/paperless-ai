"""Tests for the LLM concurrency limiter."""

import threading
import time

from common.concurrency import init_llm_semaphore, llm_semaphore


def test_unlimited_is_noop():
    """When max_concurrent=0, the semaphore is a no-op."""
    init_llm_semaphore(0)
    with llm_semaphore():
        pass  # should not block


def test_semaphore_limits_concurrency():
    """Verify that only N threads can enter the semaphore simultaneously."""
    init_llm_semaphore(2)
    inside = {"count": 0, "peak": 0}
    lock = threading.Lock()

    def worker():
        with llm_semaphore():
            with lock:
                inside["count"] += 1
                inside["peak"] = max(inside["peak"], inside["count"])
            # Wait long enough for other threads to attempt entry
            time.sleep(0.1)
            with lock:
                inside["count"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert inside["peak"] <= 2


def test_reinit_replaces_semaphore():
    """Re-initializing with a different limit works."""
    init_llm_semaphore(1)
    with llm_semaphore():
        pass
    init_llm_semaphore(0)
    with llm_semaphore():
        pass  # back to no-op
