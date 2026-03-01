"""
Paperless-ngx Classification Daemon
===================================

Entry point for the classification daemon.

Polls Paperless-ngx for documents that have been OCR'd (tagged with
``CLASSIFY_PRE_TAG_ID``) and classifies them using an LLM, applying metadata
updates (title, correspondent, document type, tags, date, language, person).
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
from .provider import ClassificationProvider
from .taxonomy import TaxonomyCache
from .worker import ClassificationProcessor


def _iter_docs_to_classify(
    list_client: PaperlessClient, settings: Settings
) -> Iterable[dict]:
    """
    Yield documents that should be classified.

    Tag hygiene: if a document already has the classify-post-tag but still
    carries the classify-pre-tag, the stale tags are removed and the document
    is skipped.  Documents already claimed by a processing-lock tag are also
    skipped.
    """
    log = structlog.get_logger(__name__)
    for doc in list_client.get_documents_by_tag(settings.CLASSIFY_PRE_TAG_ID):
        doc_id = doc.get("id")
        if not isinstance(doc_id, int):
            log.warning("Skipping document without integer id", doc_id=doc_id)
            continue

        tags = extract_tags(doc, doc_id=doc_id, context="classify-iter")

        # Already classified — remove stale queue and processing tags
        if settings.CLASSIFY_POST_TAG_ID and settings.CLASSIFY_POST_TAG_ID in tags:
            if settings.CLASSIFY_PRE_TAG_ID in tags:
                remove_stale_queue_tag(
                    list_client,
                    doc_id,
                    tags,
                    pre_tag_id=settings.CLASSIFY_PRE_TAG_ID,
                    processing_tag_id=settings.CLASSIFY_PROCESSING_TAG_ID,
                )
            continue

        # Already claimed by another worker
        if (
            settings.CLASSIFY_PROCESSING_TAG_ID
            and settings.CLASSIFY_PROCESSING_TAG_ID in tags
        ):
            continue

        yield doc


def main() -> None:
    """
    Bootstrap and run the classification daemon.

    Loads settings, configures logging and LLM libraries, creates a shared
    :class:`TaxonomyCache`, then enters the polling loop.
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
        "Starting classification daemon",
        classify_pre_tag_id=settings.CLASSIFY_PRE_TAG_ID,
        classify_post_tag_id=settings.CLASSIFY_POST_TAG_ID,
        poll_interval=settings.POLL_INTERVAL,
        document_workers=settings.DOCUMENT_WORKERS,
        llm_provider=settings.LLM_PROVIDER,
        ai_models=settings.AI_MODELS,
        classify_processing_tag_id=settings.CLASSIFY_PROCESSING_TAG_ID,
    )

    list_client = PaperlessClient(settings)
    taxonomy_client = PaperlessClient(settings)
    taxonomy_cache = TaxonomyCache(taxonomy_client, settings.CLASSIFY_TAXONOMY_LIMIT)

    def process_document(doc: dict) -> None:
        paperless = PaperlessClient(settings)
        classifier = ClassificationProvider(settings)
        try:
            processor = ClassificationProcessor(
                doc, paperless, classifier, taxonomy_cache, settings,
            )
            processor.process()
        finally:
            paperless.close()

    try:
        run_polling_threadpool(
            daemon_name="classifier",
            fetch_work=lambda: list(_iter_docs_to_classify(list_client, settings)),
            process_item=process_document,
            before_each_batch=lambda _: taxonomy_cache.refresh(),
            poll_interval_seconds=settings.POLL_INTERVAL,
            max_workers=settings.DOCUMENT_WORKERS,
        )
    finally:
        list_client.close()
        taxonomy_client.close()


if __name__ == "__main__":
    main()
