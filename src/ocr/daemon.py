"""
Paperless-ngx AI OCR Daemon
===========================

Entry point for the OCR daemon.

High-level behaviour
--------------------

1. Poll Paperless-ngx for documents with the *OCR queue tag* (``PRE_TAG_ID``).
2. For each queued document:

   - Download the original file.
   - Convert the file to images (PDF pages or image frames).
   - Transcribe each page using a vision-capable LLM.
   - Upload the transcription back to Paperless (``content`` field).
   - Update tags to move the document through the pipeline.

The exact tags are configured via environment variables (see :class:`Settings`).
"""

from __future__ import annotations

from typing import Iterable

import structlog

from common.config import Settings
from common.library_setup import setup_libraries
from common.daemon_loop import run_polling_threadpool
from common.logging_config import configure_logging
from common.paperless import PaperlessClient
from common.tags import extract_tags, remove_stale_queue_tag
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

    Tag hygiene: if a document already has the post-tag but still carries the
    pre-tag, the stale pre-tag is removed and the document is skipped.
    Documents that already have the processing-lock tag are also skipped to
    reduce duplicate work.
    """
    log = structlog.get_logger(__name__)
    for doc in list_client.get_documents_by_tag(settings.PRE_TAG_ID):
        doc_id = doc.get("id")
        if not isinstance(doc_id, int):
            log.warning("Skipping document without integer id", doc_id=doc_id)
            continue

        tags = extract_tags(doc, doc_id=doc_id, context="ocr-iter")

        # Already processed — remove the stale queue tag
        if settings.POST_TAG_ID in tags:
            if settings.PRE_TAG_ID in tags:
                remove_stale_queue_tag(
                    list_client,
                    doc_id,
                    tags,
                    pre_tag_id=settings.PRE_TAG_ID,
                    processing_tag_id=settings.OCR_PROCESSING_TAG_ID,
                )
            continue

        # Already claimed by another worker
        if settings.OCR_PROCESSING_TAG_ID and settings.OCR_PROCESSING_TAG_ID in tags:
            continue

        yield doc


def main() -> None:
    """
    Bootstrap and run the OCR daemon.

    Loads settings, configures logging and LLM libraries, then enters the
    polling loop that dispatches documents to worker threads.
    """
    log = structlog.get_logger(__name__)

    try:
        settings = Settings()
        configure_logging(settings)
        setup_libraries(settings)
    except ValueError as e:
        log.error("Configuration error", error=e)
        return

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

    list_client = PaperlessClient(settings)
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
