"""
Daemon Loop Utilities
=====================

This project ships two long-running processes ("daemons"):

1. OCR daemon: polls Paperless for documents tagged for OCR and uploads text.
2. Classification daemon: polls Paperless for documents tagged for classification
   and enriches Paperless metadata using an LLM.

Both daemons share the same control-flow pattern:

- Poll for work on an interval.
- If work is found, process a batch concurrently.
- Keep running forever (until SIGINT / Ctrl-C).

This module contains a small, reusable loop implementation so the OCR and
classification entrypoints stay thin and easy to read.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, TypeVar

import structlog

log = structlog.get_logger(__name__)

T = TypeVar("T")


def run_polling_threadpool(
    *,
    daemon_name: str,
    fetch_work: Callable[[], list[T]],
    process_item: Callable[[T], None],
    poll_interval_seconds: int,
    max_workers: int,
    before_each_batch: Callable[[list[T]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """
    Run an infinite polling loop and process items concurrently in a thread pool.

    This function intentionally keeps behaviour conservative and predictable:

    - Items are fetched once per loop iteration.
    - Each loop iteration processes at most the current batch.
    - Exceptions raised while processing one item are logged and do not stop
      the daemon.

    Args:
        daemon_name:
            Name used in log messages ("ocr", "classifier", ...).
        fetch_work:
            A function returning the next batch of work items.
        process_item:
            Processes a single work item. Exceptions are caught and logged.
        poll_interval_seconds:
            How long to sleep between polling iterations.
        max_workers:
            ThreadPoolExecutor worker count for processing items in parallel.
        before_each_batch:
            Optional hook invoked once per non-empty batch (e.g. to refresh caches).
        sleep:
            Injectable sleep function (primarily for tests).
    """
    poll_interval_seconds = max(1, int(poll_interval_seconds))
    max_workers = max(1, int(max_workers))

    was_idle = False
    while True:
        try:
            items = fetch_work()
            if not items:
                if not was_idle:
                    log.info("No work found; waiting", daemon=daemon_name)
                was_idle = True
                sleep(poll_interval_seconds)
                continue

            was_idle = False
            if before_each_batch is not None:
                before_each_batch(items)

            log.info(
                "Processing batch",
                daemon=daemon_name,
                item_count=len(items),
                max_workers=max_workers,
            )

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_item = {
                    executor.submit(process_item, item): item for item in items
                }
                for future in as_completed(future_to_item):
                    item = future_to_item[future]
                    try:
                        future.result()
                    except Exception:
                        # Log and continue. The per-item processor decides whether
                        # to mark Paperless tags, retry via next poll, etc.
                        log.exception(
                            "Work item failed",
                            daemon=daemon_name,
                            item=_safe_item_summary(item),
                        )

            sleep(poll_interval_seconds)
        except KeyboardInterrupt:
            log.info("Ctrl-C received; exiting", daemon=daemon_name)
            break
        except Exception:
            log.exception(
                "Unexpected error in daemon loop; sleeping",
                daemon=daemon_name,
                poll_interval_seconds=poll_interval_seconds,
            )
            sleep(poll_interval_seconds)


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
    except Exception:
        return "<unprintable>"

