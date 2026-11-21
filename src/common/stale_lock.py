"""Startup sweep to recover documents stuck with stale processing-lock tags."""

from __future__ import annotations

import structlog

from .config import current_settings
from .paperless import PAPERLESS_CALL_EXCEPTIONS, PaperlessClient
from .tags import extract_tags

log = structlog.get_logger(__name__)


def recover_stale_locks(
    client: PaperlessClient,
    *,
    processing_tag_id: int | None,
    pre_tag_id: int,
    recovery_enabled: bool | None = None,
) -> int:
    """Strip the processing-lock tag from every document and re-queue it.

    There is no age or owner check: this recovers the orphan locks a crashed
    daemon leaves behind. With several replicas sharing one processing tag it
    would steal a peer's live lock (the tag has no timestamp) and re-spend LLM
    tokens, so such deployments must disable it via ``STALE_LOCK_RECOVERY``.
    *recovery_enabled* ``None`` reads that setting.

    Returns the number of documents recovered.
    """
    if processing_tag_id is None:
        return 0

    if recovery_enabled is None:
        recovery_enabled = current_settings().STALE_LOCK_RECOVERY
    if not recovery_enabled:
        log.info(
            "Stale-lock recovery disabled; skipping startup sweep",
            processing_tag_id=processing_tag_id,
        )
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

        updated = set(tags)
        updated.discard(processing_tag_id)
        updated.add(pre_tag_id)
        try:
            client.update_document_metadata(doc_id, tags=updated)
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
