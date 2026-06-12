"""A circuit breaker that halts a daemon when Paperless write-backs keep failing.

Each tag daemon spends LLM tokens on a document *before* it writes the result
back to Paperless. When every write-back is rejected the same way — a
misconfigured field, a deleted tag, a Paperless API change — working through the
rest of the queue would spend one LLM call per document and save none of them.
Quarantining each document stops it looping forever, but a queue of thousands
would still burn thousands of calls in a single pass.

This breaker is the guard against that one-pass burn. It counts *consecutive*
write-back failures and, once they reach the threshold, reports itself tripped so
the daemon stops pulling new work until the fault is fixed. One success resets the
count, so a single bad document never trips it — only a sustained run does.
"""

from __future__ import annotations

import threading

import structlog

log = structlog.get_logger(__name__)

# How many write-backs must fail in a row before the daemon halts. Low enough
# that a systemic failure wastes only a handful of LLM calls before stopping;
# high enough that an unlucky cluster of unrelated failures does not false-trip.
DEFAULT_FAILURES_BEFORE_HALT = 3

# The heartbeat detail a halted daemon shows on the dashboard, and the reason
# string its ``halt_check`` returns. Names the cause and the fix in one line.
HALTED_DETAIL = (
    "halted: Paperless keeps rejecting write-backs — fix the cause "
    "(see logs) then change config or restart"
)


class WriteBackCircuitBreaker:
    """Halts document processing after consecutive Paperless write-backs fail.

    One instance is shared across a daemon's worker threads, so every state
    change is guarded by a lock — the one sanctioned in-process singleton the
    threading rules allow (CODE_GUIDELINES §8.5). The state is per-daemon and
    in-process: two daemon instances each keep their own breaker and halt
    independently (CODE_GUIDELINES §1.12).
    """

    def __init__(
        self, failures_before_halt: int = DEFAULT_FAILURES_BEFORE_HALT
    ) -> None:
        if failures_before_halt < 1:
            raise ValueError("failures_before_halt must be >= 1")
        self._failures_before_halt = failures_before_halt
        self._lock = threading.Lock()
        # Limitation (known, accepted): under the daemon's ThreadPoolExecutor
        # the streak counts *completion order*, not document order. Workers run
        # concurrently and report their write-back outcome as each finishes, so
        # an interleaving like success / fail / fail / success / fail can reset
        # the streak even while failures dominate — a purely systemic fault is
        # still caught quickly (every outcome is a failure, so no success ever
        # resets), but a fault that fails most-but-not-all write-backs may take
        # longer to trip than a strict document-ordered count would. A robust
        # fix is a sliding failure-rate window rather than a consecutive count;
        # it is deferred as too invasive to land safely here. The consecutive
        # count remains correct for the case the breaker exists to stop: a
        # blanket write-back rejection where nothing succeeds.
        self._consecutive_failures = 0
        self._tripped = False

    def record_success(self) -> None:
        """A write-back succeeded — clear the failure streak."""
        with self._lock:
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        """A write-back failed — extend the streak and trip once it hits the threshold."""
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
        """Clear the halt and the streak — called when the fault may be fixed.

        The daemons call this on a configuration change (a hot-reload), which is
        the signal an operator has likely corrected the cause.
        """
        with self._lock:
            if self._tripped:
                log.info(
                    "Write-back circuit breaker reset; resuming document processing"
                )
            self._consecutive_failures = 0
            self._tripped = False
