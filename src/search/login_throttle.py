"""In-process failed-login throttle for the search server (HTTP-01, §10.6).

``POST /api/auth/login`` is the human credential path and, before this module,
had no application-layer abuse protection — only argon2id's per-verify cost
(tens of milliseconds), which does not stop a sustained online guessing
campaign against a weak password. §10.6 mandates abuse protection on exposed
endpoints; this is the login counterpart of the ``/api/search`` concurrency
cap.

What it does
~~~~~~~~~~~~
Two bounded, TTL'd, thread-safe failure counters work in tandem; a login is
denied if **either** one is tripped:

- The **per-(client IP, username)** counter is the common single-source case.
  After :data:`_MAX_FAILURES_BEFORE_LOCKOUT` failures inside a rolling
  :data:`_FAILURE_WINDOW_SECONDS` window the key locks for
  :data:`_LOCKOUT_SECONDS`.
- The **per-username** counter is source-IP-*independent* and exists because
  ``SEARCH_FORWARDED_ALLOW_IPS`` defaults to ``"*"``: when the port is
  reachable, ``request.client.host`` is attacker-controllable, so rotating
  ``X-Forwarded-For`` yields a fresh per-(IP, username) key every request and
  defeats the first counter alone. The per-username counter ignores the IP
  entirely, so a *distributed* brute force against one account is still bounded.
  Its threshold (:data:`_MAX_FAILURES_PER_USERNAME`) is deliberately *higher*
  than the per-(IP, username) one so a legitimate user behind a shared
  NAT/proxy is not locked out as eagerly as a single attacker would be.

In both counters:

- A **first** attempt and a **successful** login are never delayed or denied —
  the counters start at zero and a success clears the relevant entries. Only
  repeated *failures* accrue.
- A locked key is denied (HTTP 429) without ever reaching ``authenticate`` — so
  a locked key costs no argon2 work either.
- Failures older than the window are pruned, so a slow trickle of wrong guesses
  never trips a lock; only a burst does.

Why in-process and single-instance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
This is exactly the *documented singleton owning a* ``threading.Lock`` that
§8.5 permits, mirroring :mod:`search.cache` and ``common.concurrency``. The
search server is one process (§1.12), so process-local maps are the right
scope; they are **not** shared across replicas. A multi-instance deployment
would need a shared store — out of scope for the single-writer architecture,
and noted here so the limitation is conscious, not accidental. Both maps are
bounded by :data:`_MAX_TRACKED_KEYS` with oldest-first eviction (§8.5/§14.5).

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
from typing import TypeVar

#: The key type of a failure-counter map — an :class:`AttemptKey` for the
#: per-(IP, username) counter, or a ``str`` username for the per-username one.
_K = TypeVar("_K")

# Policy thresholds (§3.5) — tune the throttle here, in one place.
#: In-window failures tolerated for one (client IP, username) before that key
#: locks. The common single-source brute-force bound.
_MAX_FAILURES_BEFORE_LOCKOUT = 5
#: In-window failures tolerated for one username *across all IPs* before the
#: account locks. Source-IP-independent, so it survives X-Forwarded-For
#: rotation (SEARCH_FORWARDED_ALLOW_IPS defaults to "*", making the client IP
#: attacker-controlled). Set higher than the per-(IP, username) threshold so a
#: legitimate user behind a shared NAT/proxy is not locked as eagerly as a lone
#: attacker — but still bounds a distributed attack on one account.
_MAX_FAILURES_PER_USERNAME = 20
#: Failures older than this (seconds) are pruned and no longer count toward
#: either lockout — a slow trickle of wrong guesses never trips them, only a
#: burst does.
_FAILURE_WINDOW_SECONDS = 900
#: How long (seconds) a key stays locked once it trips. Applies to both
#: counters.
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


def _is_record_locked(record: _AttemptRecord, now: float) -> bool:
    """Return whether *record* is locked at *now*, clearing an expired lockout.

    Shared by both counters. An expired lockout is cleared in place so the next
    caller starts fresh — a recovered key proceeds normally.
    """
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

    Prunes failures outside the rolling window first, appends the new one, and
    locks the key once *threshold* in-window failures accrue. Bounds the map to
    :data:`_MAX_TRACKED_KEYS` with oldest-first eviction (§8.5/§14.5). The
    caller holds the lock; this mutates shared state.
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
    """A bounded, TTL'd, thread-safe failed-login throttle (§10.6, MED).

    Mirrors the discipline of :class:`search.cache.SearchResultCache`: an
    ``OrderedDict`` for O(1) oldest-first eviction, a single ``threading.Lock``
    guarding all shared state, and a monotonic clock injected for deterministic
    tests (§11.7).

    Two counters share that one lock and the same window/lockout machinery: a
    per-(client IP, username) map for the single-source case, and a per-username
    map (keyed on the username string alone) for the distributed, XFF-rotating
    case. A login is locked if *either* trips. See the module docstring for why
    both are needed.

    Args:
        clock: A monotonic time source, injected for tests. Defaults to
            :func:`time.monotonic`.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._records: OrderedDict[AttemptKey, _AttemptRecord] = OrderedDict()
        self._username_records: OrderedDict[str, _AttemptRecord] = OrderedDict()

    def is_locked(self, key: AttemptKey) -> bool:
        """Return whether *key* is locked by either counter.

        Checked *before* authenticating, so a locked key is denied without any
        argon2 work. A key is locked if its (IP, username) counter is locked
        *or* its username's source-IP-independent counter is locked. An
        untracked key, or one whose lockout has expired, is not locked — a first
        attempt and a recovered key both proceed normally.
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
        """Record one failed login for *key* against both counters.

        The per-(IP, username) counter locks after
        :data:`_MAX_FAILURES_BEFORE_LOCKOUT` in-window failures; the
        source-IP-independent per-username counter locks after the higher
        :data:`_MAX_FAILURES_PER_USERNAME`. Both maps are memory-bounded by
        :data:`_MAX_TRACKED_KEYS`.
        """
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
        """Clear *key*'s history in both counters — a success is never throttled.

        Dropping both records on success guarantees a legitimate login is
        unaffected by earlier typos — including distributed ones counted against
        the username — and keeps the maps small.
        """
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
