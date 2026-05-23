"""OCR daemon entry point.

Configuration is loaded from the application database (``app.db``) layered
over the environment by :func:`common.bootstrap.bootstrap_daemon` (web-redesign
spec §5), and **re-checked at the top of every poll** via
:func:`common.config.current_settings` so a saved configuration change takes
effect on the next cycle with no restart. The daemon imports no database
package directly — it remains barred from ``store``; the only database access
is the ``appdb`` read inside the shared bootstrap and the hot-load accessor.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

import structlog

from common.bootstrap import bootstrap_daemon
from common.concurrency import llm_limiter
from common.config import Settings, current_settings
from common.daemon_loop import run_polling_threadpool
from common.document_iter import iter_documents_by_pipeline_tag
from common.library_setup import setup_libraries
from common.logging_config import configure_logging
from common.paperless import PaperlessClient
from common.per_document import run_per_document
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


def _reload_if_changed(state: _DaemonState) -> None:
    """The before-each-poll hook: rebuild config-derived resources on a change.

    ``current_settings()`` returns the SAME cached object when the config is
    unchanged, so the ``is`` check is the steady-state cost. On a change it
    closes the old Paperless client, rebuilds logging / libraries / the LLM
    limiter and the client, and points *state* at the new configuration.

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
    state.list_client.close()
    configure_logging(latest)
    setup_libraries(latest)
    llm_limiter.init(latest.LLM_MAX_CONCURRENT)
    state.settings = latest
    state.list_client = PaperlessClient(latest)


def _process_document(doc: dict, settings: Settings) -> None:
    """Process a single Paperless document with its own HTTP session and provider."""
    run_per_document(
        doc,
        settings,
        lambda d, paperless: OcrProcessor(
            d, paperless, OcrProvider(settings), settings
        ),
    )


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
        page_workers=settings.PAGE_WORKERS,
        document_workers=settings.DOCUMENT_WORKERS,
        llm_provider=settings.LLM_PROVIDER,
        ai_models=settings.AI_MODELS,
        ocr_processing_tag_id=settings.OCR_PROCESSING_TAG_ID,
    )

    # APP_DB_PATH is the location the hot-load accessor watches every poll.
    # Resolved here and threaded down so the hook never re-reads os.environ.
    app_db_path = os.environ.get("APP_DB_PATH", "/data/app.db")
    state = _DaemonState(
        settings=settings, list_client=list_client, app_db_path=app_db_path
    )

    try:
        run_polling_threadpool(
            daemon_name="ocr",
            fetch_work=lambda: list(
                _iter_docs_to_ocr(state.list_client, state.settings)
            ),
            process_item=lambda doc: _process_document(doc, state.settings),
            poll_interval_seconds=state.settings.POLL_INTERVAL,
            max_workers=state.settings.DOCUMENT_WORKERS,
            before_each_poll=lambda: _reload_if_changed(state),
        )
    finally:
        state.list_client.close()


if __name__ == "__main__":
    main()
