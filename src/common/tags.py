"""Tag extraction, hygiene, and pipeline-tag lifecycle helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import structlog

from .paperless import PaperlessClient

if TYPE_CHECKING:
    from .config import Settings

log = structlog.get_logger(__name__)


def extract_tags(doc: dict, *, doc_id: int, context: str) -> set[int]:
    """Extract tag IDs from a Paperless document dict, handling malformed data."""
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
    """Fetch current tags from the API, falling back to a cached copy on error."""
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


def remove_stale_queue_tag(
    client: PaperlessClient,
    doc_id: int,
    tags: set[int],
    *,
    pre_tag_id: int,
    processing_tag_id: int | None = None,
) -> None:
    """Remove queue/processing tags that should no longer be on a document."""
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


def release_processing_tag(
    client: PaperlessClient,
    doc_id: int,
    tag_id: int | None,
    *,
    purpose: str,
) -> None:
    """Remove a processing-lock tag after processing. Best-effort, never propagates errors."""
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


def finalize_document_with_error(
    client: PaperlessClient,
    doc_id: int,
    tags: set[int],
    settings: Settings,
    *,
    content: str | None = None,
) -> None:
    """
    Mark a document as errored, remove all pipeline tags, and optionally
    update the document content.
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
    """Return a copy of *tags* with all automation-pipeline tag IDs removed."""
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
