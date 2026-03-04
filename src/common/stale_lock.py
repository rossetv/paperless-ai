"""
Stale Processing-Lock Recovery
==============================

When a daemon crashes mid-processing, documents may be left with a
processing-lock tag but no active worker.  No daemon will pick them up
again because the lock tag causes them to be skipped.

This module provides a startup sweep that finds and releases stale locks,
re-queuing the affected documents so they are processed on the next poll.
"""

from __future__ import annotations

import structlog

from .paperless import PaperlessClient
from .tags import extract_tags

log = structlog.get_logger(__name__)


def recover_stale_locks(
    client: PaperlessClient,
    *,
    processing_tag_id: int | None,
    pre_tag_id: int,
) -> int:
    """Find documents with a stale processing-lock tag and re-queue them.

    At startup no workers are running, so every document carrying the
    processing-lock tag is stale by definition.  For each such document
    we remove the lock tag and ensure the pre-tag is present so it
    re-enters the queue.

    Args:
        client: A :class:`PaperlessClient` instance.
        processing_tag_id: The processing-lock tag ID.  If ``None`` or
            ``0``, recovery is skipped (locks are not configured).
        pre_tag_id: The queue tag to re-add for re-processing.

    Returns:
        The number of documents recovered.
    """
    if not processing_tag_id:
        return 0

    recovered = 0
    try:
        docs = list(client.get_documents_by_tag(processing_tag_id))
    except Exception:
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
        except Exception:
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
