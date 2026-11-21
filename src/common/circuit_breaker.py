"""A circuit breaker that halts a daemon when Paperless write-backs keep failing.

Each document costs an LLM call before its write-back, so when every write-back
is rejected the same way, working through the queue burns tokens for nothing.
The breaker trips after consecutive failures; one success resets the count.
"""

from __future__ import annotations

import threading

import structlog

log = structlog.get_logger(__name__)

# How many write-backs must fail in a row before the daemon halts. Low enough
# that a systemic failure wastes only a handful of LLM calls before stopping;
# high enough that an unlucky cluster of unrelated failures does not false-trip.
DEFAULT_FAILURES_BEFORE_HALT = 3

# The heartbeat detail a halted daemon shows, and its halt_check reason.
HALTED_DETAIL = (
    "halted: Paperless keeps rejecting write-backs — fix the cause "
    "(see logs) then change config or restart"
)


class WriteBackCircuitBreaker:
    """Halts document processing after consecutive Paperless write-backs fail.

    Shared across a daemon's worker threads, so state changes take a lock. The
    state is in-process: each daemon instance halts independently.
    """

    def __init__(
        self, failures_before_halt: int = DEFAULT_FAILURES_BEFORE_HALT
    ) -> None:
        if failures_before_halt < 1:
            raise ValueError("failures_before_halt must be >= 1")
        self._failures_before_halt = failures_before_halt
        self._lock = threading.Lock()
        # Workers run concurrently, so the streak is in completion order.
        self._consecutive_failures = 0
        self._tripped = False

    def record_success(self) -> None:
        """A write-back succeeded — clear the failure streak."""
        with self._lock:
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        """A write-back failed — extend the streak and trip at the threshold."""
        with self._lock:
            self._consecutive_failures += 1
            reached_threshold = self._consecutive_failures >= self._failures_before_halt
            if reached_threshold and not self._tripped:
                self._tripped = True
                log.error(
                    "Write-back circuit breaker tripped; halting document processing "
                    "to stop burning LLM tokens. Fix the cause (check the logged "
                    "Paperless rejection) and the daemon resumes on the next config "
                    "change or restart.",
                    consecutive_failures=self._consecutive_failures,
                    failures_before_halt=self._failures_before_halt,
                )

    def is_tripped(self) -> bool:
        """True once the daemon should stop pulling new work.

        Stays True until :meth:`reset` — a late success from a worker still in
        flight when the breaker tripped clears the streak but must not lift the
        halt on its own.
        """
        with self._lock:
            return self._tripped

    def reset(self) -> None:
        """Clear the halt and the streak.

        Daemons call this on a config change, the sign an operator has likely
        fixed the cause.
        """
        with self._lock:
            if self._tripped:
                log.info(
                    "Write-back circuit breaker reset; resuming document processing"
                )
            self._consecutive_failures = 0
            self._tripped = False
