"""Classification daemon entry point.

Configuration is re-read from ``app.db`` before every poll, so a saved change
takes effect on the next cycle without a restart.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from typing import Iterable

import structlog

from appdb.connection import connect as connect_app_db
from appdb.schema import ensure_schema
from common.bootstrap import bootstrap_daemon
from common.circuit_breaker import HALTED_DETAIL, WriteBackCircuitBreaker
from common.concurrency import llm_limiter
from common.config import Settings, app_db_path_from_env, current_settings
from common.daemon_loop import CycleOutcome, run_polling_threadpool
from common.heartbeat import Heartbeat, run_stall_ticker
from common.document_iter import iter_documents_by_pipeline_tag
from common.library_setup import setup_libraries
from common.logging_config import configure_logging
from common.paperless import PaperlessClient
from common.per_document import WriteBackOutcome, run_per_document
from .provider import ClassificationProvider
from .taxonomy import TaxonomyCache
from .worker import ClassificationProcessor

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class _DaemonState:
    """The classifier daemon's config-derived resources, swapped on a config change.

    The loop callbacks close over this holder rather than a bare ``Settings``,
    so a reload between polls is picked up without rebuilding the loop. The
    taxonomy client lives here too because a Paperless URL or token change needs
    a fresh httpx session.
    """

    settings: Settings
    list_client: PaperlessClient
    taxonomy_client: PaperlessClient
    taxonomy_cache: TaxonomyCache
    app_db_path: str


def _reload_if_changed(
    state: _DaemonState, circuit_breaker: WriteBackCircuitBreaker
) -> None:
    """Rebuild config-derived resources before a poll if the config changed.

    ``current_settings()`` returns the same cached object while the config is
    unchanged, so the ``is`` check is the steady-state cost. A change also
    resets the write-back circuit breaker: it is the operator's signal that a
    halting fault (e.g. a bad tag id) may now be fixed.

    ``POLL_INTERVAL`` and ``DOCUMENT_WORKERS`` are fixed when the loop starts,
    so those two keys need a restart; every other key hot-loads.
    """
    latest = current_settings(state.app_db_path)
    if latest is state.settings:
        return
    log.info("classifier.config_reloaded")
    circuit_breaker.reset()
    state.list_client.close()
    state.taxonomy_client.close()
    configure_logging(latest)
    setup_libraries(latest)
    llm_limiter.init(latest.LLM_MAX_CONCURRENT)
    state.settings = latest
    state.list_client = PaperlessClient(latest)
    state.taxonomy_client = PaperlessClient(latest)
    state.taxonomy_cache = TaxonomyCache(
        state.taxonomy_client, latest.CLASSIFY_TAXONOMY_LIMIT
    )


def _process_document(
    doc: dict[str, object], settings: Settings, taxonomy_cache: TaxonomyCache
) -> WriteBackOutcome | None:
    """Process a single Paperless document with its own HTTP session and provider."""
    return run_per_document(
        doc,
        settings,
        lambda d, paperless: ClassificationProcessor(
            d, paperless, ClassificationProvider(settings), taxonomy_cache, settings
        ),
    )


def _process_and_record(
    doc: dict[str, object],
    state: _DaemonState,
    circuit_breaker: WriteBackCircuitBreaker,
) -> None:
    """Process a document, then report its write-back outcome to the breaker.

    A saved result clears the failure streak; a permanently-rejected one extends
    it. Outcomes that wrote nothing back (skipped, requeued) leave the breaker
    untouched.
    """
    outcome = _process_document(doc, state.settings, state.taxonomy_cache)
    if outcome is WriteBackOutcome.SAVED:
        circuit_breaker.record_success()
    elif outcome is WriteBackOutcome.QUARANTINED:
        circuit_breaker.record_failure()


def _iter_docs_to_classify(
    list_client: PaperlessClient, settings: Settings
) -> Iterable[dict[str, object]]:
    return iter_documents_by_pipeline_tag(
        list_client,
        pre_tag_id=settings.CLASSIFY_PRE_TAG_ID,
        post_tag_id=settings.CLASSIFY_POST_TAG_ID,
        processing_tag_id=settings.CLASSIFY_PROCESSING_TAG_ID,
        context="classify-iter",
    )


def main() -> None:
    """Bootstrap and run the classification daemon."""
    result = bootstrap_daemon(
        get_processing_tag_id=lambda s: s.CLASSIFY_PROCESSING_TAG_ID,
        get_pre_tag_id=lambda s: s.CLASSIFY_PRE_TAG_ID,
    )
    if result is None:
        sys.exit(1)
    settings, list_client = result

    log.info(
        "Starting classification daemon",
        classify_pre_tag_id=settings.CLASSIFY_PRE_TAG_ID,
        classify_post_tag_id=settings.CLASSIFY_POST_TAG_ID,
        poll_interval=settings.POLL_INTERVAL,
        document_workers=settings.DOCUMENT_WORKERS,
        llm_provider=settings.LLM_PROVIDER,
        classify_models=settings.CLASSIFY_MODELS,
        classify_processing_tag_id=settings.CLASSIFY_PROCESSING_TAG_ID,
    )

    # PaperlessClient is not thread-safe, but this one is shared safely: the
    # TaxonomyCache is its only caller and every access runs under the cache's
    # RLock.
    taxonomy_client = PaperlessClient(settings)
    taxonomy_cache = TaxonomyCache(taxonomy_client, settings.CLASSIFY_TAXONOMY_LIMIT)

    app_db_path = app_db_path_from_env()
    state = _DaemonState(
        settings=settings,
        list_client=list_client,
        taxonomy_client=taxonomy_client,
        taxonomy_cache=taxonomy_cache,
        app_db_path=app_db_path,
    )

    # Halts the daemon if Paperless rejects write-backs repeatedly, so a
    # systemic failure cannot burn one LLM call per queued document. It lives
    # for the process, outside _DaemonState; a config reload resets it.
    circuit_breaker = WriteBackCircuitBreaker()

    app_db = connect_app_db(app_db_path)
    ensure_schema(app_db)
    heartbeat = Heartbeat(name="classifier", conn=app_db)

    def _on_cycle(outcome: CycleOutcome) -> None:
        """Write the classifier daemon's heartbeat after every poll cycle."""
        poll_in_flight.clear()
        if outcome.halted:
            heartbeat.beat(detail=HALTED_DETAIL)
        elif outcome.idle:
            heartbeat.beat_idle()
        else:
            heartbeat.beat(
                detail=f"classifying {outcome.processed} document(s)",
                processed_delta=outcome.processed,
            )

    def _before_poll() -> None:
        _reload_if_changed(state, circuit_breaker)
        poll_in_flight.set()

    # A poll can block far past the heartbeat staleness window (the flex
    # capacity-429 wait parks every worker), and _on_cycle only beats after the
    # poll returns. The stall ticker beats meanwhile so the dashboard does not
    # show "stopped". It opens its own app.db connection because sqlite
    # connections must not cross threads.
    poll_in_flight = threading.Event()
    ticker_stop = threading.Event()

    def _run_stall_ticker() -> None:
        conn = connect_app_db(app_db_path)
        try:
            run_stall_ticker(
                Heartbeat(name="classifier", conn=conn),
                in_flight=poll_in_flight,
                stop=ticker_stop,
                detail="classifying — waiting on a slow upstream call",
            )
        finally:
            conn.close()

    ticker_thread = threading.Thread(
        target=_run_stall_ticker, name="classifier-stall-ticker", daemon=True
    )
    ticker_thread.start()

    try:
        run_polling_threadpool(
            daemon_name="classifier",
            fetch_work=lambda: list(
                _iter_docs_to_classify(state.list_client, state.settings)
            ),
            process_item=lambda doc: _process_and_record(doc, state, circuit_breaker),
            before_each_batch=lambda _: state.taxonomy_cache.refresh(),
            before_each_poll=_before_poll,
            poll_interval_seconds=state.settings.POLL_INTERVAL,
            max_workers=state.settings.DOCUMENT_WORKERS,
            on_cycle=_on_cycle,
            halt_check=lambda: HALTED_DETAIL if circuit_breaker.is_tripped() else None,
        )
    finally:
        ticker_stop.set()
        ticker_thread.join(timeout=5)
        state.list_client.close()
        state.taxonomy_client.close()
        app_db.close()


if __name__ == "__main__":
    main()
