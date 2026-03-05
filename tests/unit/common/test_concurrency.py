"""
Comprehensive tests for ``common.concurrency``.

Covers initialization with zero/N, unlimited vs limited semaphore behavior,
threading concurrency limiting, and re-initialization.
"""

from __future__ import annotations

import threading
import time

import pytest

from common.concurrency import llm_limiter, init_llm_semaphore, llm_semaphore


# ---------------------------------------------------------------------------
# Reset limiter state between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_semaphore():
    """Reset the limiter's semaphore to None before each test."""
    llm_limiter._semaphore = None
    yield
    llm_limiter._semaphore = None


# ===================================================================
# init with 0 -> semaphore is None (unlimited)
# ===================================================================

class TestInitZero:

    def test_zero_sets_semaphore_to_none(self):
        init_llm_semaphore(0)
        assert llm_limiter._semaphore is None

    def test_negative_treated_as_zero(self):
        """Negative values should also result in no semaphore (unlimited)."""
        init_llm_semaphore(-1)
        assert llm_limiter._semaphore is None


# ===================================================================
# init with N -> BoundedSemaphore(N) created
# ===================================================================

class TestInitPositive:

    def test_creates_bounded_semaphore(self):
        init_llm_semaphore(3)
        assert llm_limiter._semaphore is not None
        assert isinstance(llm_limiter._semaphore, threading.BoundedSemaphore)

    def test_creates_semaphore_with_value_1(self):
        init_llm_semaphore(1)
        assert llm_limiter._semaphore is not None


# ===================================================================
# llm_semaphore() with unlimited -> yields immediately (no-op)
# ===================================================================

class TestUnlimitedSemaphore:

    def test_yields_immediately(self):
        init_llm_semaphore(0)
        entered = False
        with llm_semaphore():
            entered = True
        assert entered is True

    def test_no_blocking(self):
        """Multiple threads can enter simultaneously without blocking."""
        init_llm_semaphore(0)
        results = []

        def worker():
            with llm_semaphore():
                results.append(threading.current_thread().name)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(results) == 10


# ===================================================================
# llm_semaphore() with limit -> actually limits concurrent threads
# ===================================================================

class TestLimitedSemaphore:

    def test_limits_concurrency(self):
        """With semaphore of 2, at most 2 threads run concurrently."""
        init_llm_semaphore(2)
        max_concurrent = 0
        current_concurrent = 0
        lock = threading.Lock()

        def worker():
            nonlocal max_concurrent, current_concurrent
            with llm_semaphore():
                with lock:
                    current_concurrent += 1
                    max_concurrent = max(max_concurrent, current_concurrent)
                time.sleep(0.05)
                with lock:
                    current_concurrent -= 1

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert max_concurrent <= 2

    def test_semaphore_released_on_exception(self):
        """Semaphore is released even if the body raises."""
        init_llm_semaphore(1)

        with pytest.raises(RuntimeError):
            with llm_semaphore():
                raise RuntimeError("boom")

        # The semaphore should be released, so another acquire succeeds
        with llm_semaphore():
            pass  # would deadlock if not released


# ===================================================================
# Re-init replaces previous semaphore
# ===================================================================

class TestReInit:

    def test_reinit_replaces_semaphore(self):
        init_llm_semaphore(5)
        first = llm_limiter._semaphore
        init_llm_semaphore(2)
        second = llm_limiter._semaphore
        assert first is not second

    def test_reinit_to_unlimited(self):
        init_llm_semaphore(5)
        assert llm_limiter._semaphore is not None
        init_llm_semaphore(0)
        assert llm_limiter._semaphore is None


# ===================================================================
# LLMConcurrencyLimiter class direct usage
# ===================================================================

class TestLLMConcurrencyLimiterDirect:

    def test_acquire_method(self):
        """Test the class acquire() method directly."""
        llm_limiter.init(1)
        with llm_limiter.acquire():
            pass  # should not deadlock

    def test_init_method(self):
        """Test the class init() method directly."""
        llm_limiter.init(3)
        assert llm_limiter._semaphore is not None
        llm_limiter.init(0)
        assert llm_limiter._semaphore is None
