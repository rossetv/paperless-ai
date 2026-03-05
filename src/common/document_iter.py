"""Yields queued documents, filtering out already-done and claimed ones."""

from __future__ import annotations

from typing import Generator

import structlog

from .paperless import PaperlessClient
from .tags import extract_tags, remove_stale_queue_tag

log = structlog.get_logger(__name__)


def iter_documents_by_pipeline_tag(
    client: PaperlessClient,
    *,
    pre_tag_id: int,
    post_tag_id: int | None,
    processing_tag_id: int | None,
    context: str,
) -> Generator[dict, None, None]:
    """
    Yield documents queued for processing, filtering out already-done and claimed docs.

    Both daemons use the same control flow when iterating documents:

    1. Fetch documents by the *pre* (queue) tag.
    2. Skip documents without an integer ``id``.
    3. Skip already-processed documents (those carrying the *post* tag),
       removing the stale *pre* tag as a side-effect.
    4. Skip documents already claimed by another worker (carrying the
       *processing* tag).

    Args:
        client:           Paperless API client used for listing and cleanup.
        pre_tag_id:       The queue tag that marks documents for processing.
        post_tag_id:      The "done" tag.  Documents carrying this are skipped.
        processing_tag_id: The processing-lock tag.  ``None`` or ``0`` to disable.
        context:          Short label for log context (e.g. ``"ocr-iter"``).
    """
    for doc in client.get_documents_by_tag(pre_tag_id):
        doc_id = doc.get("id")
        if not isinstance(doc_id, int):
            log.warning("Skipping document without integer id", doc_id=doc_id)
            continue

        tags = extract_tags(doc, doc_id=doc_id, context=context)

        # Already processed — remove the stale queue tag
        if post_tag_id and post_tag_id in tags:
            if pre_tag_id in tags:
                remove_stale_queue_tag(
                    client,
                    doc_id,
                    tags,
                    pre_tag_id=pre_tag_id,
                    processing_tag_id=processing_tag_id,
                )
            continue

        # Already claimed by another worker
        if processing_tag_id and processing_tag_id in tags:
            continue

        yield doc
