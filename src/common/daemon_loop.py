"""Polling loop with concurrent thread pool processing for both daemons."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TypeVar

import structlog

from .paperless import PAPERLESS_CALL_EXCEPTIONS
from .shutdown import is_shutdown_requested

log = structlog.get_logger(__name__)

# Daemon-level fault isolation: catch transient network/API errors so the
# polling loop survives temporary outages without crashing.
_DAEMON_LOOP_EXCEPTIONS = PAPERLESS_CALL_EXCEPTIONS

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CycleOutcome:
    """The outcome of one poll iteration, passed to an ``on_cycle`` hook.

    Attributes:
        processed: How many work items the iteration dispatched to the
            thread pool. Zero on an idle or halted poll.
        idle: True when the poll found no work.
        halted: True when the poll was skipped because ``halt_check`` reported
            the daemon halted (e.g. the write-back circuit breaker tripped). No
            work is fetched or processed on a halted poll.
    """

    processed: int
    idle: bool
    halted: bool = False


def _process_batch(
    items: list[T],
    process_item: Callable[[T], None],
    max_workers: int,
    daemon_name: str,
) -> None:
    """Process a batch of work items concurrently using a thread pool.

    Exceptions raised while processing one item are logged but do not
    prevent other items from completing.
    """
    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix=f"{daemon_name}-worker"
    ) as executor:
        future_to_item = {executor.submit(process_item, item): item for item in items}
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                future.result()
            except Exception:
                # rationale: per-document worker-dispatch boundary
                # (CODE_GUIDELINES §6.4, site 2) — one document's failure is
                # logged with its traceback and isolated so the rest of the
                # batch still completes. The traceback is attached via
                # log.exception.
                log.exception(
                    "Work item failed",
                    daemon=daemon_name,
                    item=_safe_item_summary(item),
                )


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
        # The daemon is halted (the write-back circuit breaker has tripped).
        # Skip fetching and processing so no LLM tokens are spent while the fault
        # persists; the queued documents wait, untouched, for the daemon to
        # resume. The breaker logs the trip once and ``on_cycle`` keeps the
        # dashboard showing the halt, so no per-poll log is needed here.
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

    _process_batch(items, process_item, max_workers, daemon_name)
    return CycleOutcome(processed=len(items), idle=False)


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
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run an infinite polling loop and process items concurrently in a thread pool.

    This function intentionally keeps behaviour conservative and predictable.

    Args:
        before_each_poll: Called once at the top of every poll iteration,
            before ``fetch_work``. The tag daemons use it to re-check the
            configuration and hot-reload config-derived resources between
            polls (web-redesign §5). A hook exception is not swallowed by the
            loop's ``try`` — it runs before the ``try`` — so a hook must not
            raise on the recoverable path; ``current_settings()`` only raises
            on a genuinely invalid stored config, which is a fatal condition
            the daemon should not survive silently.
        on_cycle: Invoked once after every poll iteration with that iteration's
            CycleOutcome — the daemons use it to write a heartbeat. A callback
            exception is isolated and logged; it never crashes the loop.
        halt_check: Polled at the top of each iteration. When it returns a
            reason string the iteration is skipped entirely — no work is fetched
            or processed — and the outcome is marked ``halted``. The tag daemons
            use it to stop pulling work once the write-back circuit breaker has
            tripped. ``None`` (the default) means never halt.
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
            # An expected, recoverable anomaly: a transient Paperless network
            # or API failure. WARNING (not ERROR) per §7.3; exc_info=True
            # attaches the traceback — log.error(str(exc)) would discard it
            # (§7.5). The loop sleeps and the next poll retries.
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
    """Invoke the optional per-cycle hook, isolating any failure.

    The hook is observability (a heartbeat write); a bug in it must never
    crash the polling loop. Any exception is logged with its traceback and
    swallowed — exactly the fault-isolation rule the loop applies to a work
    item (CODE_GUIDELINES §6.4).
    """
    if on_cycle is None:
        return
    try:
        on_cycle(outcome)
    except Exception:
        # rationale: per-cycle hook boundary — a heartbeat-callback bug is
        # isolated so the daemon's real polling loop survives it.
        log.exception("on_cycle hook failed", daemon=daemon_name)


def _safe_item_summary(item: object) -> str:
    """
    Best-effort string for logging a work item.

    The daemons usually pass dicts (Paperless documents) into the threadpool, but
    tests may pass arbitrary objects.
    """
    try:
        if isinstance(item, dict):
            if "id" in item:
                return f"doc_id={item.get('id')}"
            return f"dict_keys={sorted(item.keys())}"
        return str(item)
    except (TypeError, ValueError, AttributeError):
        # The only failures str()/sorted()/repr() formatting can realistically
        # raise: unorderable dict keys (TypeError), a __str__/__repr__ that
        # raises (TypeError/ValueError/AttributeError). A genuine programming
        # bug outside that set is not swallowed.
        return "<unprintable>"
