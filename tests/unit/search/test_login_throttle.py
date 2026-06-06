"""Tests for search.login_throttle — the failed-login brute-force throttle.

Covers (HTTP-01, §10.6): a first attempt is never locked; a key locks only
after a burst of failures inside the window; a success clears the counter so a
legitimate login is never throttled; a stale trickle of failures outside the
window does not trip the lock; an expired lockout clears; the map is bounded.

The clock is injected so every timing assertion is deterministic (§11.7) — no
``time.sleep`` anywhere.
"""

from __future__ import annotations

from search.login_throttle import (
    _FAILURE_WINDOW_SECONDS,
    _LOCKOUT_SECONDS,
    _MAX_FAILURES_BEFORE_LOCKOUT,
    _MAX_TRACKED_KEYS,
    AttemptKey,
    LoginThrottle,
    build_attempt_key,
)


class _FakeClock:
    """A monotonic clock whose value the test advances explicitly."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _key(username: str = "alice", ip: str = "10.0.0.1") -> AttemptKey:
    return AttemptKey(client_ip=ip, username=username)


def test_a_fresh_key_is_not_locked() -> None:
    """An untracked key — a first login attempt — is never locked."""
    throttle = LoginThrottle(clock=_FakeClock())
    assert throttle.is_locked(_key()) is False


def test_failures_below_the_threshold_do_not_lock() -> None:
    """One short of the threshold leaves the key unlocked."""
    throttle = LoginThrottle(clock=_FakeClock())
    key = _key()
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT - 1):
        throttle.record_failure(key)
    assert throttle.is_locked(key) is False


def test_a_burst_of_failures_locks_the_key() -> None:
    """The threshold number of in-window failures locks the key (HTTP-01)."""
    throttle = LoginThrottle(clock=_FakeClock())
    key = _key()
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT):
        throttle.record_failure(key)
    assert throttle.is_locked(key) is True


def test_a_success_clears_the_failure_counter() -> None:
    """A successful login drops the key's history; it is never throttled."""
    throttle = LoginThrottle(clock=_FakeClock())
    key = _key()
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT - 1):
        throttle.record_failure(key)
    throttle.record_success(key)
    # After the reset a fresh burst must start from zero, so one more failure
    # does not lock.
    throttle.record_failure(key)
    assert throttle.is_locked(key) is False


def test_failures_outside_the_window_do_not_count() -> None:
    """A slow trickle spread beyond the window never trips the lock."""
    clock = _FakeClock()
    throttle = LoginThrottle(clock=clock)
    key = _key()
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT - 1):
        throttle.record_failure(key)
    # Move past the window so the earlier failures are pruned, then fail once.
    clock.advance(_FAILURE_WINDOW_SECONDS + 1)
    throttle.record_failure(key)
    assert throttle.is_locked(key) is False


def test_the_lockout_expires_after_the_cooldown() -> None:
    """Once the cooldown elapses the key unlocks and may retry."""
    clock = _FakeClock()
    throttle = LoginThrottle(clock=clock)
    key = _key()
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT):
        throttle.record_failure(key)
    assert throttle.is_locked(key) is True

    clock.advance(_LOCKOUT_SECONDS + 1)
    assert throttle.is_locked(key) is False


def test_distinct_keys_are_tracked_independently() -> None:
    """Locking one (ip, username) does not lock a different one."""
    throttle = LoginThrottle(clock=_FakeClock())
    locked = _key(username="alice")
    other_user = _key(username="bob")
    other_ip = _key(username="alice", ip="10.0.0.2")
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT):
        throttle.record_failure(locked)
    assert throttle.is_locked(locked) is True
    assert throttle.is_locked(other_user) is False
    assert throttle.is_locked(other_ip) is False


def test_the_tracked_map_is_bounded() -> None:
    """The map never grows past the cap — oldest keys are evicted (§8.5)."""
    throttle = LoginThrottle(clock=_FakeClock())
    for index in range(_MAX_TRACKED_KEYS + 50):
        throttle.record_failure(_key(username=f"user-{index}"))
    assert throttle.size() <= _MAX_TRACKED_KEYS


def test_build_attempt_key_lowercases_username_and_defaults_ip() -> None:
    """The key folds username case and tolerates a missing client IP."""
    key = build_attempt_key(client_ip=None, username="Alice")
    assert key == AttemptKey(client_ip="", username="alice")
