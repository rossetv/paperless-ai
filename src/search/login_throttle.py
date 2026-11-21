"""In-process failed-login throttle for ``POST /api/auth/login``.

argon2id's per-verify cost alone does not stop a sustained online guessing
campaign, so two failure counters are kept and a login is denied (429, before
any argon2 work) if either is locked:

- per (client IP, username): the single-source case;
- per username, ignoring the IP: ``SEARCH_FORWARDED_ALLOW_IPS`` defaults to
  ``"*"``, so a reachable port lets an attacker rotate ``X-Forwarded-For`` and
  get a fresh per-IP key on every request. Its threshold is higher so a user
  behind a shared NAT is not locked out as eagerly as a lone attacker.

Only repeated failures inside the rolling window accrue; a success clears both
entries. The counters are process-local, which is correct for this
single-process server but would not be shared across replicas.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

#: An :class:`AttemptKey` for the per-(IP, username) map, a ``str`` username for
#: the per-username map.
_K = TypeVar("_K")

#: In-window failures tolerated for one (client IP, username) before it locks.
_MAX_FAILURES_BEFORE_LOCKOUT = 5
#: In-window failures tolerated for one username across all IPs.
_MAX_FAILURES_PER_USERNAME = 20
#: Rolling window (seconds); a slow trickle of wrong guesses never trips a lock.
_FAILURE_WINDOW_SECONDS = 900
#: How long (seconds) a key stays locked once it trips.
_LOCKOUT_SECONDS = 900
#: Memory-leak guard, not a tuning knob; oldest keys are evicted first.
_MAX_TRACKED_KEYS = 4096


@dataclass(frozen=True, slots=True)
class AttemptKey:
    """The identity a login throttle counts against.

    The username is an account identifier, not a secret, so it is safe to log.

    Attributes:
        client_ip: The caller's IP, or ``""`` when it cannot be determined.
        username: Case-folded so case variants of one account share a counter.
    """

    client_ip: str
    username: str


def build_attempt_key(*, client_ip: str | None, username: str) -> AttemptKey:
    """Build an :class:`AttemptKey` from a request's IP and submitted username."""
    return AttemptKey(client_ip=client_ip or "", username=username.casefold())


@dataclass
class _AttemptRecord:
    """Per-key throttle state.

    Attributes:
        failure_times: Monotonic timestamps of in-window failures, oldest first.
        locked_until: Monotonic time the lockout expires, or ``None``.
    """

    failure_times: list[float]
    locked_until: float | None


def _is_record_locked(record: _AttemptRecord, now: float) -> bool:
    """Return whether *record* is locked at *now*, clearing an expired lockout."""
    if record.locked_until is None:
        return False
    if now >= record.locked_until:
        record.locked_until = None
        record.failure_times.clear()
        return False
    return True


def _register_failure(
    records: OrderedDict[_K, _AttemptRecord],
    key: _K,
    now: float,
    *,
    threshold: int,
) -> None:
    """Record one in-window failure for *key* in *records*, locking on threshold.

    The caller holds the lock.
    """
    record = records.get(key)
    if record is None:
        record = _AttemptRecord(failure_times=[], locked_until=None)
        records[key] = record
    records.move_to_end(key)

    cutoff = now - _FAILURE_WINDOW_SECONDS
    record.failure_times = [t for t in record.failure_times if t > cutoff]
    record.failure_times.append(now)

    if len(record.failure_times) >= threshold:
        record.locked_until = now + _LOCKOUT_SECONDS

    while len(records) > _MAX_TRACKED_KEYS:
        records.popitem(last=False)


class LoginThrottle:
    """A bounded, TTL'd, thread-safe failed-login throttle.

    Both counters (see the module docstring) share one lock and use an
    ``OrderedDict`` for O(1) oldest-first eviction. *clock* is injectable for
    tests.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._records: OrderedDict[AttemptKey, _AttemptRecord] = OrderedDict()
        self._username_records: OrderedDict[str, _AttemptRecord] = OrderedDict()

    def is_locked(self, key: AttemptKey) -> bool:
        """Return whether *key* is locked by either counter.

        Called before authenticating, so a locked key costs no argon2 work.
        """
        now = self._clock()
        with self._lock:
            return self._is_key_locked(key, now) or self._is_username_locked(
                key.username, now
            )

    def _is_key_locked(self, key: AttemptKey, now: float) -> bool:
        """Whether the per-(IP, username) counter is locked. Caller holds lock."""
        record = self._records.get(key)
        return record is not None and _is_record_locked(record, now)

    def _is_username_locked(self, username: str, now: float) -> bool:
        """Whether the per-username counter is locked. Caller holds the lock."""
        record = self._username_records.get(username)
        return record is not None and _is_record_locked(record, now)

    def record_failure(self, key: AttemptKey) -> None:
        """Record one failed login for *key* against both counters."""
        now = self._clock()
        with self._lock:
            _register_failure(
                self._records,
                key,
                now,
                threshold=_MAX_FAILURES_BEFORE_LOCKOUT,
            )
            _register_failure(
                self._username_records,
                key.username,
                now,
                threshold=_MAX_FAILURES_PER_USERNAME,
            )

    def record_success(self, key: AttemptKey) -> None:
        """Clear *key*'s history in both counters, including the per-username one."""
        with self._lock:
            self._records.pop(key, None)
            self._username_records.pop(key.username, None)

    def size(self) -> int:
        """Return the per-(IP, username) tracked-key count (tests/observability)."""
        with self._lock:
            return len(self._records)

    def username_size(self) -> int:
        """Return the per-username tracked-key count (tests/observability)."""
        with self._lock:
            return len(self._username_records)

    def reset(self) -> None:
        """Drop every tracked key in both maps — for tests, never the request path."""
        with self._lock:
            self._records.clear()
            self._username_records.clear()


# Process-wide: a fresh instance per request would forget every prior failure.
_login_throttle: LoginThrottle | None = None
_login_throttle_lock = threading.Lock()


def get_login_throttle() -> LoginThrottle:
    """Return the process-wide :class:`LoginThrottle`, building it once."""
    global _login_throttle
    if _login_throttle is not None:
        return _login_throttle
    with _login_throttle_lock:
        if _login_throttle is None:
            _login_throttle = LoginThrottle()
        return _login_throttle


def reset_login_throttle() -> None:
    """Drop the process-wide throttle singleton — for tests only."""
    global _login_throttle
    with _login_throttle_lock:
        _login_throttle = None
