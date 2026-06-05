"""Tests for common.circuit_breaker — the write-back failure halt."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from common.circuit_breaker import WriteBackCircuitBreaker


class TestWriteBackCircuitBreaker:
    def test_starts_untripped(self):
        breaker = WriteBackCircuitBreaker(failures_before_halt=3)
        assert breaker.is_tripped() is False

    def test_trips_after_consecutive_failures_reach_threshold(self):
        breaker = WriteBackCircuitBreaker(failures_before_halt=3)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_tripped() is False
        breaker.record_failure()
        assert breaker.is_tripped() is True

    def test_a_success_resets_the_streak(self):
        breaker = WriteBackCircuitBreaker(failures_before_halt=3)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()  # streak back to zero
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_tripped() is False  # only two since the reset

    def test_a_late_success_does_not_lift_a_trip(self):
        # A worker already in flight when the breaker trips can report success
        # afterwards; that must not resume the daemon on its own — only reset().
        breaker = WriteBackCircuitBreaker(failures_before_halt=2)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_tripped() is True
        breaker.record_success()
        assert breaker.is_tripped() is True

    def test_reset_clears_a_trip(self):
        breaker = WriteBackCircuitBreaker(failures_before_halt=1)
        breaker.record_failure()
        assert breaker.is_tripped() is True
        breaker.reset()
        assert breaker.is_tripped() is False

    def test_streak_must_be_consecutive(self):
        breaker = WriteBackCircuitBreaker(failures_before_halt=2)
        breaker.record_failure()
        breaker.record_success()
        breaker.record_failure()
        # The success broke the run, so a single failure since does not trip.
        assert breaker.is_tripped() is False

    def test_threshold_below_one_is_rejected(self):
        with pytest.raises(ValueError, match="failures_before_halt"):
            WriteBackCircuitBreaker(failures_before_halt=0)

    def test_default_threshold_is_usable(self):
        # The no-argument constructor the daemons use must work and not trip on
        # the first failure.
        breaker = WriteBackCircuitBreaker()
        breaker.record_failure()
        assert breaker.is_tripped() is False

    def test_is_thread_safe_under_concurrent_failures(self):
        # The breaker is shared across a daemon's worker threads, so its counter
        # must be lock-guarded. Many threads each recording one failure must sum
        # exactly — a lost update would leave it below the threshold and the
        # daemon would never halt.
        threads = 50
        breaker = WriteBackCircuitBreaker(failures_before_halt=threads)
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(lambda _: breaker.record_failure(), range(threads)))
        # Exactly `threads` failures were recorded, so the breaker is tripped;
        # one fewer would have left it untripped, proving none were lost.
        assert breaker.is_tripped() is True
