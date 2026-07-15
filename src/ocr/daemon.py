"""OCR daemon entry point.

Configuration is loaded from the application database (``app.db``) layered
over the environment by :func:`common.bootstrap.bootstrap_daemon` (web-redesign
spec §5), and **re-checked at the top of every poll** via
:func:`common.config.current_settings` so a saved configuration change takes
effect on the next cycle with no restart. The daemon imports ``appdb`` for
configuration hot-load and heartbeat bootstrap but remains barred from
``store``; it accesses no search-index tables directly.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Iterable

import structlog

from appdb.connection import connect as connect_app_db
from appdb.schema import ensure_schema
from common.bootstrap import bootstrap_daemon
from common.circuit_breaker import HALTED_DETAIL, WriteBackCircuitBreaker
from common.concurrency import llm_limiter
from common.config import Settings, current_settings
from common.daemon_loop import CycleOutcome, run_polling_threadpool
from common.heartbeat import Heartbeat, run_stall_ticker
from common.document_iter import iter_documents_by_pipeline_tag
from common.library_setup import setup_libraries
from common.logging_config import configure_logging
from common.paperless import PaperlessClient
from common.per_document import WriteBackOutcome, run_per_document
from .provider import OcrProvider
from .worker import OcrProcessor

log = structlog.get_logger(__name__)


@dataclass
class _DaemonState:
    """The OCR daemon's config-derived resources, swapped on a config change.

    ``fetch_work`` / ``process_item`` close over this holder rather than a
    bare ``Settings``, so a hot-reload between polls is picked up by the next
    poll without rebuilding the loop (web-redesign §5).
    """

    settings: Settings
    list_client: PaperlessClient
    app_db_path: str


def _reload_if_changed(
    state: _DaemonState, circuit_breaker: WriteBackCircuitBreaker
) -> None:
    """The before-each-poll hook: rebuild config-derived resources on a change.

    ``current_settings()`` returns the SAME cached object when the config is
    unchanged, so the ``is`` check is the steady-state cost. On a change it
    closes the old Paperless client, rebuilds logging / libraries / the LLM
    limiter and the client, points *state* at the new configuration, and resets
    the write-back circuit breaker — a config change is the operator's signal
    that a halting fault (e.g. a bad tag id) may now be fixed, so the daemon
    resumes.

    ``poll_interval_seconds`` and ``max_workers`` are read once at loop
    construction — :func:`common.daemon_loop.run_polling_threadpool` fixes
    them for the loop's life; a change to ``POLL_INTERVAL`` /
    ``DOCUMENT_WORKERS`` is the one class of change that does *not* hot-load
    for the tag daemons (the loop's cadence and pool size are structural).
    Every other key hot-loads.
    """
    latest = current_settings(state.app_db_path)
    if latest is state.settings:
        return
    log.info("ocr.config_reloaded")
    circuit_breaker.reset()
    state.list_client.close()
    configure_logging(latest)
    setup_libraries(latest)
    llm_limiter.init(latest.LLM_MAX_CONCURRENT)
    state.settings = latest
    state.list_client = PaperlessClient(latest)


def _process_document(doc: dict, settings: Settings) -> WriteBackOutcome | None:
    """Process a single Paperless document with its own HTTP session and provider."""
    return run_per_document(
        doc,
        settings,
        lambda d, paperless: OcrProcessor(
            d, paperless, OcrProvider(settings), settings
        ),
    )


def _process_and_record(
    doc: dict, settings: Settings, circuit_breaker: WriteBackCircuitBreaker
) -> None:
    """Process a document, then report its write-back outcome to the breaker.

    A saved transcription clears the failure streak; a permanently-rejected one
    extends it. Outcomes that wrote nothing back (skipped, no pages) leave the
    breaker untouched.
    """
    outcome = _process_document(doc, settings)
    if outcome is WriteBackOutcome.SAVED:
        circuit_breaker.record_success()
    elif outcome is WriteBackOutcome.QUARANTINED:
        circuit_breaker.record_failure()


def _iter_docs_to_ocr(
    list_client: PaperlessClient, settings: Settings
) -> Iterable[dict]:
    return iter_documents_by_pipeline_tag(
        list_client,
        pre_tag_id=settings.PRE_TAG_ID,
        post_tag_id=settings.POST_TAG_ID,
        processing_tag_id=settings.OCR_PROCESSING_TAG_ID,
        context="ocr-iter",
    )


def main() -> None:
    """Bootstrap and run the OCR daemon until shutdown is requested."""
    result = bootstrap_daemon(
        get_processing_tag_id=lambda s: s.OCR_PROCESSING_TAG_ID,
        get_pre_tag_id=lambda s: s.PRE_TAG_ID,
    )
    if result is None:
        return
    settings, list_client = result

    log.info(
        "Starting daemon",
        pre_tag_id=settings.PRE_TAG_ID,
        post_tag_id=settings.POST_TAG_ID,
        poll_interval=settings.POLL_INTERVAL,
        ocr_dpi=settings.OCR_DPI,
        ocr_max_side=settings.OCR_MAX_SIDE,
        ocr_image_detail=settings.OCR_IMAGE_DETAIL,
        ocr_reasoning_effort=settings.OCR_REASONING_EFFORT,
        page_workers=settings.PAGE_WORKERS,
        document_workers=settings.DOCUMENT_WORKERS,
        llm_provider=settings.LLM_PROVIDER,
        ocr_models=settings.OCR_MODELS,
        ocr_processing_tag_id=settings.OCR_PROCESSING_TAG_ID,
    )

    # APP_DB_PATH is the location the hot-load accessor watches every poll.
    # Resolved here and threaded down so the hook never re-reads os.environ.
    app_db_path = os.environ.get("APP_DB_PATH", "/data/app.db")
    state = _DaemonState(
        settings=settings, list_client=list_client, app_db_path=app_db_path
    )

    # Halts the daemon if Paperless rejects write-backs repeatedly, so a
    # systemic failure cannot burn one LLM call per queued document. Process-
    # lifetime, not config-derived: it survives a hot-reload and is only reset
    # by one (see _reload_if_changed), so it lives here rather than in _DaemonState.
    circuit_breaker = WriteBackCircuitBreaker()

    # The Index dashboard heartbeat (web-redesign spec §5). Reuse the
    # already-resolved app_db_path rather than re-reading the env var.
    app_db = connect_app_db(app_db_path)
    ensure_schema(app_db)
    heartbeat = Heartbeat(name="ocr", conn=app_db)

    def _on_cycle(outcome: CycleOutcome) -> None:
        """Write the OCR daemon's heartbeat after every poll cycle."""
        poll_in_flight.clear()
        if outcome.halted:
            heartbeat.beat(detail=HALTED_DETAIL)
        elif outcome.idle:
            heartbeat.beat_idle()
        else:
            heartbeat.beat(
                detail=f"processing {outcome.processed} document(s)",
                processed_delta=outcome.processed,
            )

    def _before_poll() -> None:
        _reload_if_changed(state, circuit_breaker)
        poll_in_flight.set()

    # A poll cycle can legitimately block far past the heartbeat staleness
    # window — the flex capacity-429 wait parks every worker until OpenAI has
    # capacity — and _on_cycle only beats AFTER the poll returns. The stall
    # ticker beats while a cycle is in flight so the dashboard shows a long
    # wait as working, not "stopped". Its thread owns its own app.db
    # connection (sqlite connections must not cross threads).
    poll_in_flight = threading.Event()
    ticker_stop = threading.Event()

    def _run_stall_ticker() -> None:
        conn = connect_app_db(app_db_path)
        try:
            run_stall_ticker(
                Heartbeat(name="ocr", conn=conn),
                in_flight=poll_in_flight,
                stop=ticker_stop,
                detail="processing — waiting on a slow upstream call",
            )
        finally:
            conn.close()

    ticker_thread = threading.Thread(
        target=_run_stall_ticker, name="ocr-stall-ticker", daemon=True
    )
    ticker_thread.start()

    try:
        run_polling_threadpool(
            daemon_name="ocr",
            fetch_work=lambda: list(
                _iter_docs_to_ocr(state.list_client, state.settings)
            ),
            process_item=lambda doc: _process_and_record(
                doc, state.settings, circuit_breaker
            ),
            poll_interval_seconds=state.settings.POLL_INTERVAL,
            max_workers=state.settings.DOCUMENT_WORKERS,
            before_each_poll=_before_poll,
            on_cycle=_on_cycle,
            halt_check=lambda: HALTED_DETAIL if circuit_breaker.is_tripped() else None,
        )
    finally:
        ticker_stop.set()
        ticker_thread.join(timeout=5)
        state.list_client.close()
        app_db.close()


if __name__ == "__main__":
    main()
