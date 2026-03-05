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

from typing import TYPE_CHECKING, Generator

import httpx
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
    except (OSError, httpx.HTTPError, ValueError):
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
# Document iteration with tag filtering
# ---------------------------------------------------------------------------

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

def finalize_document_with_error(
    client: PaperlessClient,
    doc_id: int,
    tags: set[int],
    settings: Settings,
    log: structlog.stdlib.BoundLogger,
    *,
    content: str | None = None,
) -> None:
    """
    Mark a document as errored, remove all pipeline tags, and optionally
    update the document content.

    This is the shared error-finalisation routine used by both the OCR and
    classification workers.

    Args:
        client:   Paperless API client.
        doc_id:   Document ID to update.
        tags:     Current tag set (will be cleaned of pipeline tags).
        settings: Application settings (consulted for pipeline/error tag IDs).
        log:      Structured logger for the calling module.
        content:  If provided, the Paperless ``content`` field is also updated
                  (e.g. when the OCR output contains refusal markers that should
                  be visible to human reviewers).
    """
    updated = clean_pipeline_tags(tags, settings)
    if settings.ERROR_TAG_ID:
        updated.add(settings.ERROR_TAG_ID)

    if content is not None:
        client.update_document(doc_id, content, list(updated))
    else:
        client.update_document_metadata(doc_id, tags=list(updated))

    if settings.ERROR_TAG_ID:
        log.warning(
            "Marked document with error tag",
            doc_id=doc_id,
            error_tag_id=settings.ERROR_TAG_ID,
        )
    else:
        log.warning(
            "Error finalised; removed pipeline tags (no error tag configured)",
            doc_id=doc_id,
        )


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
