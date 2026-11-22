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
    """Yield documents carrying the *pre* (queue) tag that still need processing.

    Skips documents without an integer id, documents already carrying the
    *post* tag (removing their stale queue tag), and documents claimed by
    another worker. *context* labels log lines.
    """
    # Collected up front: removing the queue tag while paging shifts later pages.
    for doc in list(client.get_documents_by_tag(pre_tag_id)):
        doc_id = doc.get("id")
        if not isinstance(doc_id, int):
            log.warning("Skipping document without integer id", doc_id=doc_id)
            continue

        tags = extract_tags(doc, doc_id=doc_id, context=context)

        if post_tag_id is not None and post_tag_id in tags:
            if pre_tag_id in tags:
                remove_stale_queue_tag(
                    client,
                    doc_id,
                    tags,
                    pre_tag_id=pre_tag_id,
                    processing_tag_id=processing_tag_id,
                )
            continue

        if processing_tag_id is not None and processing_tag_id in tags:
            continue

        yield doc
