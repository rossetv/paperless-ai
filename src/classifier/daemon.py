"""Classification daemon entry point."""

from __future__ import annotations

from typing import Iterable

import structlog

from common.bootstrap import bootstrap_daemon
from common.config import Settings
from common.daemon_loop import run_polling_threadpool
from common.paperless import PaperlessClient
from common.document_iter import iter_documents_by_pipeline_tag
from .provider import ClassificationProvider
from .taxonomy import TaxonomyCache
from .worker import ClassificationProcessor


def _process_document(
    doc: dict, settings: Settings, taxonomy_cache: TaxonomyCache
) -> None:
    """Process a single Paperless document with its own HTTP session and provider."""
    # Each thread gets its own PaperlessClient (and thus its own HTTP session)
    # because httpx sessions are not thread-safe.
    paperless = PaperlessClient(settings)
    classifier = ClassificationProvider(settings)
    try:
        processor = ClassificationProcessor(
            doc, paperless, classifier, taxonomy_cache, settings,
        )
        processor.process()
    finally:
        paperless.close()


def _iter_docs_to_classify(
    list_client: PaperlessClient, settings: Settings
) -> Iterable[dict]:
    """Yield documents that should be classified."""
    return iter_documents_by_pipeline_tag(
        list_client,
        pre_tag_id=settings.CLASSIFY_PRE_TAG_ID,
        post_tag_id=settings.CLASSIFY_POST_TAG_ID,
        processing_tag_id=settings.CLASSIFY_PROCESSING_TAG_ID,
        context="classify-iter",
    )


def main() -> None:
    """
    Bootstrap and run the classification daemon.

    Uses the shared bootstrap sequence, creates a shared
    :class:`TaxonomyCache`, then enters the polling loop.
    """
    result = bootstrap_daemon(
        get_processing_tag_id=lambda s: s.CLASSIFY_PROCESSING_TAG_ID,
        get_pre_tag_id=lambda s: s.CLASSIFY_PRE_TAG_ID,
    )
    if result is None:
        return
    settings, list_client = result

    log = structlog.get_logger(__name__)
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

    taxonomy_client = PaperlessClient(settings)
    taxonomy_cache = TaxonomyCache(taxonomy_client, settings.CLASSIFY_TAXONOMY_LIMIT)

    try:
        run_polling_threadpool(
            daemon_name="classifier",
            fetch_work=lambda: list(_iter_docs_to_classify(list_client, settings)),
            process_item=lambda doc: _process_document(doc, settings, taxonomy_cache),
            before_each_batch=lambda _: taxonomy_cache.refresh(),
            poll_interval_seconds=settings.POLL_INTERVAL,
            max_workers=settings.DOCUMENT_WORKERS,
        )
    finally:
        list_client.close()
        taxonomy_client.close()


if __name__ == "__main__":
    main()
