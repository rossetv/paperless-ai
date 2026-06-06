"""In-process failed-login throttle for the search server (HTTP-01, §10.6).

``POST /api/auth/login`` is the human credential path and, before this module,
had no application-layer abuse protection — only argon2id's per-verify cost
(tens of milliseconds), which does not stop a sustained online guessing
campaign against a weak password. §10.6 mandates abuse protection on exposed
endpoints; this is the login counterpart of the ``/api/search`` concurrency
cap.

What it does
~~~~~~~~~~~~
A bounded, TTL'd, thread-safe counter keyed on ``(client IP, username)``:

- A **first** attempt and a **successful** login are never delayed or denied —
  the counter starts at zero and a success clears the key. Only repeated
  *failures* accrue.
- After :data:`_MAX_FAILURES_BEFORE_LOCKOUT` failures inside a rolling
  :data:`_FAILURE_WINDOW_SECONDS` window, the key is locked for
  :data:`_LOCKOUT_SECONDS`; further attempts are denied (HTTP 429) without ever
  reaching ``authenticate`` — so a locked key costs no argon2 work either.
- Failures older than the window are pruned, so a slow trickle of wrong guesses
  never trips the lock; only a burst does.

Why in-process and single-instance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
This is exactly the *documented singleton owning a* ``threading.Lock`` that
§8.5 permits, mirroring :mod:`search.cache` and ``common.concurrency``. The
search server is one process (§1.12), so a process-local map is the right
scope; it is **not** shared across replicas. A multi-instance deployment would
need a shared store — out of scope for the single-writer architecture, and
noted here so the limitation is conscious, not accidental. Memory is bounded by
:data:`_MAX_TRACKED_KEYS` with oldest-first eviction (§8.5/§14.5).

The thresholds are module constants (§3.5) so a maintainer can tune the policy
in one place.

Allowed deps: standard library only.
Forbidden: FastAPI, sqlite3, any I/O, secrets in any field.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

# Policy thresholds (§3.5) — tune the throttle here, in one place.
#: Consecutive in-window failures tolerated before a key is locked.
_MAX_FAILURES_BEFORE_LOCKOUT = 5
#: Failures older than this (seconds) are pruned and no longer count toward the
#: lockout — a slow trickle of wrong guesses never trips it, only a burst does.
_FAILURE_WINDOW_SECONDS = 900
#: How long (seconds) a key stays locked once it trips.
_LOCKOUT_SECONDS = 900
#: Hard upper bound on tracked keys — a memory-leak guard (§8.5/§14.5), never a
#: tuning knob. Far above any honest login volume; the windows are the real
#: lifetime. Oldest-tracked keys are evicted first when at capacity.
_MAX_TRACKED_KEYS = 4096


@dataclass(frozen=True, slots=True)
class AttemptKey:
    """The identity a login throttle counts against.

    Frozen + slots so it is hashable and usable as a dict key. The username is
    *not* a secret (§7.4) — it is an account identifier, safe to hold and log.

    Attributes:
        client_ip: The caller's IP, or ``""`` when it cannot be determined.
        username: The submitted username, lower-cased so case variants of one
            account share a counter.
    """

    client_ip: str
    username: str


def build_attempt_key(*, client_ip: str | None, username: str) -> AttemptKey:
    """Build an :class:`AttemptKey` from a request's IP and submitted username.

    Args:
        client_ip: The caller's IP, or ``None`` when Starlette could not
            resolve it.
        username: The submitted username.

    Returns:
        The throttle key; the IP falls back to ``""`` and the username is
        lower-cased so ``Alice`` and ``alice`` share one counter.
    """
    return AttemptKey(client_ip=client_ip or "", username=username.casefold())


@dataclass
class _AttemptRecord:
    """Per-key throttle state.

    Attributes:
        failure_times: Monotonic timestamps of in-window failures, oldest
            first. Pruned to the rolling window on every touch.
        locked_until: The monotonic time the lockout expires, or ``None`` when
            the key is not locked.
    """

    failure_times: list[float]
    locked_until: float | None


class LoginThrottle:
    """A bounded, TTL'd, thread-safe failed-login throttle (§10.6).

    Mirrors the discipline of :class:`search.cache.SearchResultCache`: an
    ``OrderedDict`` for O(1) oldest-first eviction, a single
    ``threading.Lock``, and a monotonic clock injected for deterministic tests
    (§11.7).

    Args:
        clock: A monotonic time source, injected for tests. Defaults to
            :func:`time.monotonic`.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._records: OrderedDict[AttemptKey, _AttemptRecord] = OrderedDict()

    def is_locked(self, key: AttemptKey) -> bool:
        """Return whether *key* is currently locked out.

        Checked *before* authenticating, so a locked key is denied without any
        argon2 work. An untracked key, or one whose lockout has expired, is not
        locked — a first attempt and a recovered key both proceed normally.
        """
        with self._lock:
            record = self._records.get(key)
            if record is None or record.locked_until is None:
                return False
            if self._clock() >= record.locked_until:
                # The lockout has elapsed — clear it and let the caller retry.
                record.locked_until = None
                record.failure_times.clear()
                return False
            return True

    def record_failure(self, key: AttemptKey) -> None:
        """Record one failed login for *key*, locking it if the threshold trips.

        Prunes failures outside the rolling window first, so only a burst of
        :data:`_MAX_FAILURES_BEFORE_LOCKOUT` in-window failures locks the key.
        A no-op's worth of memory is bounded by :data:`_MAX_TRACKED_KEYS`.
        """
        now = self._clock()
        with self._lock:
            record = self._records.get(key)
            if record is None:
                record = _AttemptRecord(failure_times=[], locked_until=None)
                self._records[key] = record
            self._records.move_to_end(key)

            cutoff = now - _FAILURE_WINDOW_SECONDS
            record.failure_times = [t for t in record.failure_times if t > cutoff]
            record.failure_times.append(now)

            if len(record.failure_times) >= _MAX_FAILURES_BEFORE_LOCKOUT:
                record.locked_until = now + _LOCKOUT_SECONDS

            while len(self._records) > _MAX_TRACKED_KEYS:
                self._records.popitem(last=False)

    def record_success(self, key: AttemptKey) -> None:
        """Clear *key*'s failure history — a success is never throttled.

        Dropping the record on success guarantees a legitimate login is
        unaffected by an earlier typo and keeps the map small.
        """
        with self._lock:
            self._records.pop(key, None)

    def size(self) -> int:
        """Return the number of tracked keys (for tests/observability)."""
        with self._lock:
            return len(self._records)

    def reset(self) -> None:
        """Drop every tracked key — for tests, never the request path."""
        with self._lock:
            self._records.clear()


# The documented process-wide singleton and its accessor (§4.6, §8.5). One
# throttle guards every login on this single-process server (§1.12); a fresh
# instance per request would forget every prior failure and defeat the purpose.
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
