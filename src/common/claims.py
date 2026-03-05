"""Processing-lock tag claiming with refresh-before / verify-after semantics."""

from __future__ import annotations

import structlog

from .paperless import PaperlessClient
from .tags import extract_tags

log = structlog.get_logger(__name__)


def claim_processing_tag(
    *,
    paperless_client: PaperlessClient,
    doc_id: int,
    tag_id: int | None,
    purpose: str,
) -> bool:
    """Add a processing-lock tag and verify it persists (best-effort lock).

    Returns ``True`` on success, ``False`` if already claimed or on error.
    Returns ``True`` immediately when *tag_id* is ``None`` (lock not configured).
    """
    if not tag_id:
        return True

    try:
        latest = paperless_client.get_document(doc_id)
    except Exception:
        log.exception(
            "Failed to refresh document before claiming processing tag",
            doc_id=doc_id,
            processing_tag_id=tag_id,
            purpose=purpose,
        )
        return False

    current_tags = extract_tags(latest, doc_id=doc_id, context=f"{purpose}-claim")
    if tag_id in current_tags:
        log.info(
            "Document already claimed",
            doc_id=doc_id,
            processing_tag_id=tag_id,
            purpose=purpose,
        )
        return False

    updated_tags = set(current_tags)
    updated_tags.add(tag_id)
    try:
        paperless_client.update_document_metadata(doc_id, tags=list(updated_tags))
    except Exception:
        log.exception(
            "Failed to claim processing tag",
            doc_id=doc_id,
            processing_tag_id=tag_id,
            purpose=purpose,
        )
        return False

    try:
        verified = paperless_client.get_document(doc_id)
    except Exception:
        log.exception(
            "Failed to refresh document after claiming processing tag",
            doc_id=doc_id,
            processing_tag_id=tag_id,
            purpose=purpose,
        )
        return False

    verified_tags = extract_tags(verified, doc_id=doc_id, context=f"{purpose}-verify")
    if tag_id not in verified_tags:
        log.warning(
            "Processing tag claim could not be verified",
            doc_id=doc_id,
            processing_tag_id=tag_id,
            purpose=purpose,
        )
        return False

    log.info(
        "Claimed document",
        doc_id=doc_id,
        processing_tag_id=tag_id,
        purpose=purpose,
    )
    return True
