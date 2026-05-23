"""Classification daemon entry point.

Configuration is loaded from the application database (``app.db``) layered
over the environment by :func:`common.bootstrap.bootstrap_daemon` (web-redesign
spec §5). The daemon imports no database package directly — it remains barred
from ``store``; the only database access is the ``appdb`` read inside the
shared bootstrap.
"""

from __future__ import annotations

from typing import Iterable

import structlog

from common.bootstrap import bootstrap_daemon
from common.config import Settings
from common.daemon_loop import run_polling_threadpool
from common.paperless import PaperlessClient
from common.document_iter import iter_documents_by_pipeline_tag
from common.per_document import run_per_document
from .provider import ClassificationProvider
from .taxonomy import TaxonomyCache
from .worker import ClassificationProcessor


def _process_document(
    doc: dict, settings: Settings, taxonomy_cache: TaxonomyCache
) -> None:
    """Process a single Paperless document with its own HTTP session and provider."""
    run_per_document(
        doc,
        settings,
        lambda d, paperless: ClassificationProcessor(
            d, paperless, ClassificationProvider(settings), taxonomy_cache, settings
        ),
    )


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

    # One long-lived taxonomy client is shared across all worker threads via
    # the TaxonomyCache. A PaperlessClient is not itself thread-safe
    # (CODE_GUIDELINES §8.3), but the cache is the *only* caller of this client
    # and every one of its accesses runs under the cache's RLock — so no two
    # threads ever touch the shared httpx session concurrently. This is the
    # documented exception to the per-thread-client rule, not a violation.
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
