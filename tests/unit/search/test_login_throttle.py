"""Tests for search.login_throttle, the failed-login brute-force throttle.

The clock is injected so timing assertions are deterministic.
"""

from __future__ import annotations

from search.login_throttle import (
    _FAILURE_WINDOW_SECONDS,
    _LOCKOUT_SECONDS,
    _MAX_FAILURES_BEFORE_LOCKOUT,
    _MAX_FAILURES_PER_USERNAME,
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


def _admits(throttle: LoginThrottle, key: AttemptKey) -> bool:
    """Whether a login for *key* is let in; an admitted attempt is settled at once."""
    if not throttle.begin_attempt(key):
        return False
    throttle.abandon_attempt(key)
    return True


def test_a_fresh_key_is_not_locked() -> None:
    """An untracked key — a first login attempt — is never locked."""
    throttle = LoginThrottle(clock=_FakeClock())
    assert _admits(throttle, _key())


def test_failures_below_the_threshold_do_not_lock() -> None:
    """One short of the threshold leaves the key unlocked."""
    throttle = LoginThrottle(clock=_FakeClock())
    key = _key()
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT - 1):
        throttle.record_failure(key)
    assert _admits(throttle, key)


def test_a_burst_of_failures_locks_the_key() -> None:
    """The threshold number of in-window failures locks the key."""
    throttle = LoginThrottle(clock=_FakeClock())
    key = _key()
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT):
        throttle.record_failure(key)
    assert not _admits(throttle, key)


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
    assert _admits(throttle, key)


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
    assert _admits(throttle, key)


def test_the_lockout_expires_after_the_cooldown() -> None:
    """Once the cooldown elapses the key unlocks and may retry."""
    clock = _FakeClock()
    throttle = LoginThrottle(clock=clock)
    key = _key()
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT):
        throttle.record_failure(key)
    assert not _admits(throttle, key)

    clock.advance(_LOCKOUT_SECONDS + 1)
    assert _admits(throttle, key)


def test_distinct_keys_are_tracked_independently() -> None:
    """Locking one (ip, username) does not lock a different one."""
    throttle = LoginThrottle(clock=_FakeClock())
    locked = _key(username="alice")
    other_user = _key(username="bob")
    other_ip = _key(username="alice", ip="10.0.0.2")
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT):
        throttle.record_failure(locked)
    assert not _admits(throttle, locked)
    assert _admits(throttle, other_user)
    assert _admits(throttle, other_ip)


def test_the_tracked_map_is_bounded() -> None:
    """The map never grows past the cap — oldest keys are evicted."""
    throttle = LoginThrottle(clock=_FakeClock())
    for index in range(_MAX_TRACKED_KEYS + 50):
        throttle.record_failure(_key(username=f"user-{index}"))
    assert throttle.size() <= _MAX_TRACKED_KEYS


def test_a_lock_survives_the_map_filling_with_other_keys() -> None:
    """Filling the map with other failures does not end a lock before its time."""
    clock = _FakeClock()
    throttle = LoginThrottle(clock=clock)
    key = _key()
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT):
        throttle.record_failure(key)
    for index in range(_MAX_TRACKED_KEYS + 50):
        throttle.record_failure(_key(username=f"other-{index}", ip="10.0.0.2"))
    clock.advance(_LOCKOUT_SECONDS - 1)
    assert not _admits(throttle, key)
    clock.advance(1)
    assert _admits(throttle, key)


def test_a_per_username_lock_survives_the_map_filling_with_other_names() -> None:
    """The per-username lock also outlasts a map full of other usernames."""
    clock = _FakeClock()
    throttle = LoginThrottle(clock=clock)
    for index in range(_MAX_FAILURES_PER_USERNAME):
        throttle.record_failure(_key(ip=f"203.0.113.{index}"))
    for index in range(_MAX_TRACKED_KEYS + 50):
        throttle.record_failure(_key(username=f"other-{index}", ip="10.0.0.2"))
    clock.advance(_LOCKOUT_SECONDS - 1)
    assert not _admits(throttle, _key(ip="198.51.100.7"))


def test_the_map_stays_bounded_when_every_record_is_locked() -> None:
    """With only locked records left, the oldest goes and the cap still holds."""
    throttle = LoginThrottle(clock=_FakeClock())
    for index in range(_MAX_TRACKED_KEYS + 10):
        for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT):
            throttle.record_failure(_key(username=f"user-{index}"))
    assert throttle.size() == _MAX_TRACKED_KEYS
    assert not _admits(throttle, _key(username=f"user-{_MAX_TRACKED_KEYS + 9}"))


def test_build_attempt_key_lowercases_username_and_defaults_ip() -> None:
    """The key folds username case and tolerates a missing client IP."""
    key = build_attempt_key(client_ip=None, username="Alice")
    assert key == AttemptKey(client_ip="", username="alice")


# Per-username counter: the IP-independent defence against a brute force that
# rotates X-Forwarded-For against one account.


def test_per_username_counter_locks_despite_rotating_ips() -> None:
    """Rotating the IP per attempt still locks the account by username alone.

    With ``SEARCH_FORWARDED_ALLOW_IPS="*"`` the client IP is attacker-controlled, so
    every (IP, username) key is fresh; only the per-username counter can bound the
    attack.
    """
    throttle = LoginThrottle(clock=_FakeClock())
    for index in range(_MAX_FAILURES_PER_USERNAME):
        # A brand-new IP every attempt — the per-(IP, username) counter can
        # never accumulate, only the per-username one can.
        throttle.record_failure(_key(username="alice", ip=f"203.0.113.{index}"))
    # Any subsequent attempt for this username — even from yet another fresh IP —
    # is denied by the per-username lock.
    assert not _admits(throttle, _key(username="alice", ip="198.51.100.7"))


def test_per_username_threshold_is_higher_than_per_ip_threshold() -> None:
    """A legitimate user behind a shared NAT is not locked as eagerly.

    The per-username threshold must exceed the per-(IP, username) one, so a
    handful of honest typos from one shared proxy does not lock the whole
    account for everyone behind that proxy.
    """
    assert _MAX_FAILURES_PER_USERNAME > _MAX_FAILURES_BEFORE_LOCKOUT


def test_distributed_failures_below_username_threshold_do_not_lock() -> None:
    """One short of the per-username threshold, from distinct IPs, stays open."""
    throttle = LoginThrottle(clock=_FakeClock())
    for index in range(_MAX_FAILURES_PER_USERNAME - 1):
        throttle.record_failure(_key(username="alice", ip=f"203.0.113.{index}"))
    assert _admits(throttle, _key(username="alice", ip="203.0.113.250"))


def test_a_successful_login_clears_the_per_username_counter() -> None:
    """A success resets the per-username counter, not only the per-(IP) one.

    A legitimate user who finally logs in correctly must not stay one failure
    away from a username-level lock.
    """
    throttle = LoginThrottle(clock=_FakeClock())
    good_ip = "10.0.0.9"
    for index in range(_MAX_FAILURES_PER_USERNAME - 1):
        throttle.record_failure(_key(username="alice", ip=f"203.0.113.{index}"))
    throttle.record_success(_key(username="alice", ip=good_ip))
    # After the reset the per-username burst restarts from zero, so one more
    # distributed failure does not lock.
    throttle.record_failure(_key(username="alice", ip="203.0.113.251"))
    assert _admits(throttle, _key(username="alice", ip="198.51.100.8"))


def test_per_username_failures_outside_the_window_do_not_count() -> None:
    """A slow distributed trickle beyond the window never trips the lock."""
    clock = _FakeClock()
    throttle = LoginThrottle(clock=clock)
    for index in range(_MAX_FAILURES_PER_USERNAME - 1):
        throttle.record_failure(_key(username="alice", ip=f"203.0.113.{index}"))
    clock.advance(_FAILURE_WINDOW_SECONDS + 1)
    throttle.record_failure(_key(username="alice", ip="203.0.113.252"))
    assert _admits(throttle, _key(username="alice", ip="198.51.100.9"))


def test_the_per_username_lockout_expires_after_the_cooldown() -> None:
    """Once the cooldown elapses the username unlocks and may retry."""
    clock = _FakeClock()
    throttle = LoginThrottle(clock=clock)
    for index in range(_MAX_FAILURES_PER_USERNAME):
        throttle.record_failure(_key(username="alice", ip=f"203.0.113.{index}"))
    assert not _admits(throttle, _key(username="alice", ip="198.51.100.1"))
    clock.advance(_LOCKOUT_SECONDS + 1)
    assert _admits(throttle, _key(username="alice", ip="198.51.100.1"))


def test_per_username_lock_does_not_leak_across_usernames() -> None:
    """Locking one username by distributed attack does not lock another."""
    throttle = LoginThrottle(clock=_FakeClock())
    for index in range(_MAX_FAILURES_PER_USERNAME):
        throttle.record_failure(_key(username="alice", ip=f"203.0.113.{index}"))
    assert not _admits(throttle, _key(username="alice", ip="1.1.1.1"))
    assert _admits(throttle, _key(username="bob", ip="1.1.1.1"))


def test_the_per_username_map_is_also_bounded() -> None:
    """Many distinct usernames cannot grow the per-username map past the cap."""
    throttle = LoginThrottle(clock=_FakeClock())
    for index in range(_MAX_TRACKED_KEYS + 50):
        throttle.record_failure(_key(username=f"user-{index}", ip="10.0.0.1"))
    assert throttle.username_size() <= _MAX_TRACKED_KEYS


# Attempts still being checked count toward the limit.


def test_attempts_under_way_count_toward_the_limit() -> None:
    """Once the threshold of attempts is in flight, the next one is refused."""
    throttle = LoginThrottle(clock=_FakeClock())
    key = _key()
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT):
        assert throttle.begin_attempt(key) is True
    assert throttle.begin_attempt(key) is False


def test_attempts_under_way_count_toward_the_per_username_limit() -> None:
    """In-flight attempts from many IPs count against the username."""
    throttle = LoginThrottle(clock=_FakeClock())
    for index in range(_MAX_FAILURES_PER_USERNAME):
        assert throttle.begin_attempt(_key(ip=f"203.0.113.{index}")) is True
    assert throttle.begin_attempt(_key(ip="198.51.100.7")) is False


def test_in_flight_attempts_and_past_failures_add_up() -> None:
    """Recorded failures plus attempts under way reach the threshold together."""
    throttle = LoginThrottle(clock=_FakeClock())
    key = _key()
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT - 1):
        assert throttle.begin_attempt(key) is True
        throttle.record_failure(key)
    assert throttle.begin_attempt(key) is True
    assert throttle.begin_attempt(key) is False


def test_a_success_frees_its_slot_without_dropping_others_in_flight() -> None:
    """A success clears the history but other attempts under way still count."""
    throttle = LoginThrottle(clock=_FakeClock())
    key = _key()
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT):
        assert throttle.begin_attempt(key) is True
    throttle.record_success(key)
    assert throttle.begin_attempt(key) is True
    assert throttle.begin_attempt(key) is False


def test_an_abandoned_attempt_frees_its_slot_and_counts_no_failure() -> None:
    """An attempt that ends in an error neither holds its slot nor counts."""
    throttle = LoginThrottle(clock=_FakeClock())
    key = _key()
    for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT):
        assert throttle.begin_attempt(key) is True
        throttle.abandon_attempt(key)
    assert throttle.begin_attempt(key) is True


def test_retry_after_counts_down_the_remaining_lockout_rounded_up() -> None:
    clock = _FakeClock()
    throttle = LoginThrottle(clock=clock)
    key = _key()
    for _ in range(5):
        throttle.record_failure(key)
    assert throttle.retry_after_seconds(key) == 900
    clock.advance(0.5)
    assert throttle.retry_after_seconds(key) == 900
    clock.advance(898.6)
    assert throttle.retry_after_seconds(key) == 1


def test_retry_after_is_at_least_one_second_when_nothing_is_locked() -> None:
    throttle = LoginThrottle(clock=_FakeClock())
    assert throttle.retry_after_seconds(_key()) == 1
