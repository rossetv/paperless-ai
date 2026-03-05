"""OCR daemon entry point."""

from __future__ import annotations

from typing import Iterable

import structlog

from common.bootstrap import bootstrap_daemon
from common.config import Settings
from common.daemon_loop import run_polling_threadpool
from common.paperless import PaperlessClient
from common.document_iter import iter_documents_by_pipeline_tag
from .provider import OpenAIProvider
from .worker import DocumentProcessor


def _process_document(doc: dict, settings: Settings) -> None:
    """
    Process a single Paperless document.

    Each document gets its own HTTP session and OCR provider instance.
    The daemon runs multiple documents concurrently via the thread pool.
    """
    paperless = PaperlessClient(settings)
    ocr_provider = OpenAIProvider(settings)
    try:
        processor = DocumentProcessor(doc, paperless, ocr_provider, settings)
        processor.process()
    finally:
        paperless.close()


def _iter_docs_to_ocr(list_client: PaperlessClient, settings: Settings) -> Iterable[dict]:
    """
    Yield documents that should be OCR'd.

    Delegates to the shared :func:`~common.tags.iter_documents_by_pipeline_tag`
    helper with OCR-specific tag IDs.
    """
    return iter_documents_by_pipeline_tag(
        list_client,
        pre_tag_id=settings.PRE_TAG_ID,
        post_tag_id=settings.POST_TAG_ID,
        processing_tag_id=settings.OCR_PROCESSING_TAG_ID,
        context="ocr-iter",
    )


def main() -> None:
    """
    Bootstrap and run the OCR daemon.

    Uses the shared bootstrap sequence, then enters the polling loop
    that dispatches documents to worker threads.
    """
    result = bootstrap_daemon(
        processing_tag_id_attr="OCR_PROCESSING_TAG_ID",
        pre_tag_id_attr="PRE_TAG_ID",
    )
    if result is None:
        return
    settings, list_client = result

    log = structlog.get_logger(__name__)
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

    try:
        run_polling_threadpool(
            daemon_name="ocr",
            fetch_work=lambda: list(_iter_docs_to_ocr(list_client, settings)),
            process_item=lambda doc: _process_document(doc, settings),
            poll_interval_seconds=settings.POLL_INTERVAL,
            max_workers=settings.DOCUMENT_WORKERS,
        )
    finally:
        list_client.close()


if __name__ == "__main__":
    main()
