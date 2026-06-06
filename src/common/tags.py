"""Tag extraction, hygiene, and pipeline-tag lifecycle helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from .paperless import PAPERLESS_CALL_EXCEPTIONS, PaperlessClient

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
    except PAPERLESS_CALL_EXCEPTIONS:
        log.exception(
            "Failed to refresh document tags; using cached tags",
            doc_id=doc_id,
            context=context,
        )
        if fallback_doc is not None:
            return extract_tags(
                fallback_doc, doc_id=doc_id, context=f"{context}-fallback"
            )
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
    if processing_tag_id is not None:
        updated.discard(processing_tag_id)
    try:
        client.update_document_metadata(doc_id, tags=updated)
    except PAPERLESS_CALL_EXCEPTIONS:
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
    if tag_id is None:
        return
    try:
        latest = client.get_document(doc_id)
    except PAPERLESS_CALL_EXCEPTIONS:
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
        client.update_document_metadata(doc_id, tags=tags)
    except PAPERLESS_CALL_EXCEPTIONS:
        log.exception(
            "Failed to release processing tag",
            doc_id=doc_id,
            processing_tag_id=tag_id,
            purpose=purpose,
        )


def finalise_document_with_error(
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
    stripped = clean_pipeline_tags(tags, settings)
    updated = set(stripped)
    if settings.ERROR_TAG_ID is not None:
        updated.add(settings.ERROR_TAG_ID)

    try:
        _write_finalised_tags(client, doc_id, updated, content)
    except PAPERLESS_CALL_EXCEPTIONS:
        log.exception(
            "Failed to finalise document with error tag",
            doc_id=doc_id,
            error_tag_id=settings.ERROR_TAG_ID,
        )
        # If the error tag itself is what Paperless rejected (a stale or deleted
        # ERROR_TAG_ID is a permanent 4xx), the write above will fail on every
        # poll — and because the queue (pre) tag is never removed, the document
        # is reprocessed forever, re-spending LLM tokens. Fall back to stripping
        # the pipeline tags *without* the error tag so the document at least
        # leaves the queue and the loop stops. A transient failure fails here too
        # and is left for the next poll to retry.
        if settings.ERROR_TAG_ID is None:
            return
        try:
            _write_finalised_tags(client, doc_id, stripped, content)
        except PAPERLESS_CALL_EXCEPTIONS:
            log.exception(
                "Fallback de-queue also failed; document remains queued",
                doc_id=doc_id,
            )
            return
        log.error(
            "Could not apply error tag; removed pipeline tags to stop "
            "reprocessing loop. Check that ERROR_TAG_ID is a valid tag.",
            doc_id=doc_id,
            error_tag_id=settings.ERROR_TAG_ID,
        )
        return

    if settings.ERROR_TAG_ID is not None:
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


def _write_finalised_tags(
    client: PaperlessClient,
    doc_id: int,
    tags: set[int],
    content: str | None,
) -> None:
    """Write the finalised tag set, replacing content too when supplied."""
    if content is not None:
        client.update_document(doc_id, content, tags)
    else:
        client.update_document_metadata(doc_id, tags=tags)


def pipeline_tag_ids(settings: Settings) -> set[int]:
    """Collect all configured pipeline tag IDs from *settings*."""
    ids: set[int] = {
        settings.PRE_TAG_ID,
        settings.POST_TAG_ID,
        settings.CLASSIFY_PRE_TAG_ID,
    }
    for optional_tag in (
        settings.OCR_PROCESSING_TAG_ID,
        settings.CLASSIFY_PROCESSING_TAG_ID,
        settings.CLASSIFY_POST_TAG_ID,
        settings.ERROR_TAG_ID,
    ):
        if optional_tag is not None:
            ids.add(optional_tag)
    return ids


def clean_pipeline_tags(tags: set[int], settings: Settings) -> set[int]:
    """Return a copy of *tags* with all automation-pipeline tag IDs removed."""
    return tags - pipeline_tag_ids(settings)
