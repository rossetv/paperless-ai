"""
Tag Lifecycle Operations
========================

Shared helpers for extracting, cleaning, and managing Paperless-ngx document
tags throughout the OCR and classification pipelines.

Both daemons need to:
- extract a document's current tags from the API response,
- remove stale queue tags when a document is already processed,
- claim and release processing-lock tags,
- strip all pipeline tags before marking a document as errored.

This module centralises those operations so the daemons and workers stay thin
and the tag logic lives in exactly one place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from .paperless import PaperlessClient

if TYPE_CHECKING:
    from .config import Settings

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Tag extraction
# ---------------------------------------------------------------------------

def extract_tags(doc: dict, *, doc_id: int, context: str) -> set[int]:
    """
    Extract the set of tag IDs from a Paperless document payload.

    Handles missing, ``None``, and non-list ``tags`` fields gracefully so
    callers never have to worry about the shape of the API response.

    Args:
        doc:     Raw document dict from the Paperless API.
        doc_id:  Document ID for log context.
        context: Short label for the calling code path (e.g. ``"ocr-claim"``).

    Returns:
        A ``set[int]`` of tag IDs.  Empty when the field is missing or invalid.
    """
    tags = doc.get("tags", []) or []
    if not isinstance(tags, list):
        log.warning(
            "Document tags field was not a list; treating as empty",
            doc_id=doc_id,
            context=context,
        )
        return set()
    return set(tags)


def get_latest_tags(
    client: PaperlessClient,
    doc_id: int,
    *,
    fallback_doc: dict | None = None,
    context: str = "get-latest-tags",
) -> set[int]:
    """
    Fetch the latest tag set for a document, falling back to a cached copy.

    This is used before updating tags to avoid overwriting concurrent changes.
    If the network call fails and *fallback_doc* is provided, the tags from
    that cached document dict are returned instead.
    """
    try:
        latest = client.get_document(doc_id)
    except Exception:
        log.exception(
            "Failed to refresh document tags; using cached tags",
            doc_id=doc_id,
            context=context,
        )
        if fallback_doc is not None:
            return extract_tags(fallback_doc, doc_id=doc_id, context=f"{context}-fallback")
        return set()
    return extract_tags(latest, doc_id=doc_id, context=context)


# ---------------------------------------------------------------------------
# Stale queue-tag hygiene
# ---------------------------------------------------------------------------

def remove_stale_queue_tag(
    client: PaperlessClient,
    doc_id: int,
    tags: set[int],
    *,
    pre_tag_id: int,
    processing_tag_id: int | None = None,
) -> None:
    """
    Remove a queue tag (and optionally a processing-lock tag) that should
    no longer be present on a document.

    Called by the daemon's document iterator when it discovers a document
    that already has the "done" tag but still carries the "queued" tag.
    """
    updated = set(tags)
    updated.discard(pre_tag_id)
    if processing_tag_id:
        updated.discard(processing_tag_id)
    try:
        client.update_document_metadata(doc_id, tags=list(updated))
    except Exception:
        log.exception(
            "Failed to remove stale queue tag",
            doc_id=doc_id,
            pre_tag_id=pre_tag_id,
        )
    else:
        log.info(
            "Removed stale queue tag from already-processed document",
            doc_id=doc_id,
            pre_tag_id=pre_tag_id,
        )


# ---------------------------------------------------------------------------
# Processing-lock tag lifecycle
# ---------------------------------------------------------------------------

def release_processing_tag(
    client: PaperlessClient,
    doc_id: int,
    tag_id: int | None,
    *,
    purpose: str,
) -> None:
    """
    Remove a processing-lock tag after a worker finishes with a document.

    Does nothing when *tag_id* is ``None`` or ``0`` (i.e. the lock is not
    configured).  Failures are logged but never propagated — releasing the
    lock is best-effort.
    """
    if not tag_id:
        return
    try:
        latest = client.get_document(doc_id)
    except Exception:
        log.exception(
            "Failed to refresh document before releasing processing tag",
            doc_id=doc_id,
            processing_tag_id=tag_id,
            purpose=purpose,
        )
        return
    tags = extract_tags(latest, doc_id=doc_id, context=f"{purpose}-release")
    if tag_id not in tags:
        return
    tags.discard(tag_id)
    try:
        client.update_document_metadata(doc_id, tags=list(tags))
    except Exception:
        log.exception(
            "Failed to release processing tag",
            doc_id=doc_id,
            processing_tag_id=tag_id,
            purpose=purpose,
        )


# ---------------------------------------------------------------------------
# Pipeline tag cleanup
# ---------------------------------------------------------------------------

def clean_pipeline_tags(tags: set[int], settings: Settings) -> set[int]:
    """
    Return a copy of *tags* with all automation-pipeline tag IDs removed.

    This is used when a document needs to leave the pipeline (e.g. on error)
    without being re-queued.  User-assigned tags are preserved.

    The following settings fields are consulted:
    ``PRE_TAG_ID``, ``POST_TAG_ID``, ``CLASSIFY_PRE_TAG_ID``,
    ``CLASSIFY_POST_TAG_ID``, ``OCR_PROCESSING_TAG_ID``,
    ``CLASSIFY_PROCESSING_TAG_ID``, ``ERROR_TAG_ID``.
    """
    cleaned = set(tags)
    # Always-present pipeline tags
    cleaned.discard(settings.PRE_TAG_ID)
    cleaned.discard(settings.POST_TAG_ID)
    cleaned.discard(settings.CLASSIFY_PRE_TAG_ID)
    # Optional pipeline tags — only discard when configured
    for optional_tag in (
        settings.OCR_PROCESSING_TAG_ID,
        settings.CLASSIFY_PROCESSING_TAG_ID,
        settings.CLASSIFY_POST_TAG_ID,
        settings.ERROR_TAG_ID,
    ):
        if optional_tag:
            cleaned.discard(optional_tag)
    return cleaned
