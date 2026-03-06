"""Startup sweep to recover documents stuck with stale processing-lock tags."""

from __future__ import annotations

import structlog

from .paperless import PAPERLESS_CALL_EXCEPTIONS, PaperlessClient
from .tags import extract_tags

log = structlog.get_logger(__name__)


def recover_stale_locks(
    client: PaperlessClient,
    *,
    processing_tag_id: int | None,
    pre_tag_id: int,
) -> int:
    """Find documents with a stale processing-lock tag and re-queue them."""
    if not processing_tag_id:
        return 0

    recovered = 0
    try:
        docs = list(client.get_documents_by_tag(processing_tag_id))
    except PAPERLESS_CALL_EXCEPTIONS:
        log.exception(
            "Failed to query documents with processing-lock tag",
            processing_tag_id=processing_tag_id,
        )
        return 0

    for doc in docs:
        doc_id = doc.get("id")
        if not isinstance(doc_id, int):
            continue

        tags = extract_tags(doc, doc_id=doc_id, context="stale-lock-recovery")

        # Remove lock tag and ensure the queue tag is present.
        updated = set(tags)
        updated.discard(processing_tag_id)
        updated.add(pre_tag_id)
        try:
            client.update_document_metadata(doc_id, tags=list(updated))
            recovered += 1
            log.info(
                "Recovered stale processing lock",
                doc_id=doc_id,
                processing_tag_id=processing_tag_id,
                pre_tag_id=pre_tag_id,
            )
        except PAPERLESS_CALL_EXCEPTIONS:
            log.exception(
                "Failed to recover stale processing lock",
                doc_id=doc_id,
                processing_tag_id=processing_tag_id,
            )

    if recovered:
        log.info(
            "Stale lock recovery complete",
            recovered=recovered,
            processing_tag_id=processing_tag_id,
        )
    return recovered
