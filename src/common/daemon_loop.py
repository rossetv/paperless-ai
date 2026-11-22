"""Polling loop with concurrent thread pool processing for both daemons."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TypeVar

import structlog

from .paperless import PAPERLESS_CALL_EXCEPTIONS
from .shutdown import is_shutdown_requested, wait_for_shutdown

log = structlog.get_logger(__name__)

# Transient network/API errors the polling loop survives.
_DAEMON_LOOP_EXCEPTIONS = PAPERLESS_CALL_EXCEPTIONS

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CycleOutcome:
    """The outcome of one poll iteration, passed to an ``on_cycle`` hook.

    Attributes:
        processed: Work items dispatched to the thread pool.
        idle: True when the poll found no work.
        halted: True when ``halt_check`` skipped the poll entirely.
    """

    processed: int
    idle: bool
    halted: bool = False


def _process_batch(
    items: list[T],
    process_item: Callable[[T], None],
    max_workers: int,
    daemon_name: str,
    halt_check: Callable[[], str | None] | None,
) -> int:
    """Process *items* concurrently in sub-batches of ``max_workers``.

    ``halt_check`` runs between sub-batches and before each item, so a circuit
    breaker that trips mid-pass over a deep queue wastes at most one sub-batch
    of LLM calls instead of one per queued document. A requested shutdown stops
    the pass the same way: documents in hand finish, no new one starts. A
    halted skip is not a failure. One item's exception is logged and does not
    affect the others.

    Returns the number of items actually run (fewer than ``len(items)`` after a
    halt).
    """
    dispatched = 0

    def _run_one(item: T) -> bool:
        if is_shutdown_requested() or (
            halt_check is not None and halt_check() is not None
        ):
            # Halted while queued: skip before the LLM call, without a failure.
            return False
        process_item(item)
        return True

    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix=f"{daemon_name}-worker"
    ) as executor:
        for start in range(0, len(items), max_workers):
            if is_shutdown_requested() or (
                halt_check is not None and halt_check() is not None
            ):
                break
            chunk = items[start : start + max_workers]
            future_to_item = {executor.submit(_run_one, item): item for item in chunk}
            for future in as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    if future.result():
                        dispatched += 1
                except Exception:
                    # One document's failure must not stop the rest of the batch.
                    log.exception(
                        "Work item failed",
                        daemon=daemon_name,
                        item=_safe_item_summary(item),
                    )

    return dispatched


def _poll_once(
    *,
    daemon_name: str,
    fetch_work: Callable[[], list[T]],
    process_item: Callable[[T], None],
    max_workers: int,
    before_each_batch: Callable[[list[T]], None] | None,
    was_idle: bool,
    halt_check: Callable[[], str | None] | None,
) -> CycleOutcome:
    """Execute a single poll iteration. Returns the iteration's outcome."""
    if halt_check is not None and halt_check() is not None:
        # No per-poll log: the breaker logs the trip once and on_cycle keeps the
        # dashboard showing the halt.
        return CycleOutcome(processed=0, idle=False, halted=True)

    items = fetch_work()
    if not items:
        if not was_idle:
            log.info("No work found; waiting", daemon=daemon_name)
        return CycleOutcome(processed=0, idle=True)

    if before_each_batch is not None:
        before_each_batch(items)

    log.info(
        "Processing batch",
        daemon=daemon_name,
        item_count=len(items),
        max_workers=max_workers,
    )

    # Report what actually ran, not the queue depth.
    dispatched = _process_batch(
        items, process_item, max_workers, daemon_name, halt_check
    )
    return CycleOutcome(processed=dispatched, idle=False)


def run_polling_threadpool(
    *,
    daemon_name: str,
    fetch_work: Callable[[], list[T]],
    process_item: Callable[[T], None],
    poll_interval_seconds: int,
    max_workers: int,
    before_each_batch: Callable[[list[T]], None] | None = None,
    before_each_poll: Callable[[], None] | None = None,
    on_cycle: Callable[[CycleOutcome], None] | None = None,
    halt_check: Callable[[], str | None] | None = None,
    sleep: Callable[[float], None] = wait_for_shutdown,
) -> None:
    """Run an infinite polling loop and process items concurrently in a thread pool.

    Args:
        before_each_poll: Called before each ``fetch_work``; the tag daemons
            hot-reload config here. It runs outside the loop's ``try``, so an
            exception (only an invalid stored config) is fatal by design.
        on_cycle: Called after every poll with its outcome, e.g. to write a
            heartbeat. Its exceptions are logged and swallowed.
        halt_check: Returns a reason string to skip the poll entirely, e.g.
            once the write-back circuit breaker has tripped.
    """
    poll_interval_seconds = max(1, int(poll_interval_seconds))
    max_workers = max(1, int(max_workers))

    was_idle = False
    while not is_shutdown_requested():
        if before_each_poll is not None:
            before_each_poll()
        try:
            outcome = _poll_once(
                daemon_name=daemon_name,
                fetch_work=fetch_work,
                process_item=process_item,
                max_workers=max_workers,
                before_each_batch=before_each_batch,
                was_idle=was_idle,
                halt_check=halt_check,
            )
            was_idle = outcome.idle
            _run_on_cycle(on_cycle, outcome, daemon_name)
            sleep(poll_interval_seconds)
        except _DAEMON_LOOP_EXCEPTIONS as exc:
            # Expected and recoverable: the next poll retries.
            log.warning(
                "Transient error in daemon loop; sleeping before retry",
                daemon=daemon_name,
                poll_interval_seconds=poll_interval_seconds,
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )
            sleep(poll_interval_seconds)

    log.info("Shutdown requested; exiting gracefully", daemon=daemon_name)


def _run_on_cycle(
    on_cycle: Callable[[CycleOutcome], None] | None,
    outcome: CycleOutcome,
    daemon_name: str,
) -> None:
    """Invoke the optional per-cycle hook; a bug in it must never crash the loop."""
    if on_cycle is None:
        return
    try:
        on_cycle(outcome)
    except Exception:
        log.exception("on_cycle hook failed", daemon=daemon_name)


def _safe_item_summary(item: object) -> str:
    """Best-effort string for logging a work item (usually a Paperless document)."""
    try:
        if isinstance(item, dict):
            if "id" in item:
                return f"doc_id={item.get('id')}"
            return f"dict_keys={sorted(item.keys())}"
        return str(item)
    except (TypeError, ValueError, AttributeError):
        # Unorderable keys or a raising __str__; other bugs still surface.
        return "<unprintable>"
