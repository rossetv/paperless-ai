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
    """Find documents with a stale processing-lock tag and re-queue them.

    The sweep is **unconditional**: it strips the processing-lock tag from
    *every* document that carries it, with no age or owner check. That is the
    right move for the single-instance crash-recovery case it was written for —
    a daemon that died mid-document leaves an orphan lock no live worker owns,
    and re-queuing it is exactly what recovers the work.

    It is **unsafe with multiple replicas sharing one processing tag**, though
    (the multi-instance topology CODE_GUIDELINES §1.12 blesses for the tag
    daemons). The lock tag carries no timestamp, so a restarting replica cannot
    tell a peer's *live* lock from a genuinely *stale* one — it steals the live
    lock and the document is re-processed, re-spending LLM tokens, on every
    rolling restart. Until the lock tag grows a timestamp to grace-period
    against, the only safe control is to disable the sweep on a multi-replica
    deployment.

    Args:
        client: The Paperless client used to query and update documents.
        processing_tag_id: The processing-lock tag to sweep, or ``None`` to skip
            (no lock tag configured — nothing to recover).
        pre_tag_id: The queue tag re-added so a recovered document is picked up
            again on the next poll.
        recovery_enabled: Whether the sweep should run. ``None`` (the bootstrap
            default) resolves the ``STALE_LOCK_RECOVERY`` flag from the current
            settings — ``True`` by default, preserving single-instance
            crash-recovery behaviour. Pass an explicit bool to override (tests,
            or a caller that has already resolved the flag).

    Returns:
        The number of documents whose stale lock was recovered. ``0`` when the
        sweep is disabled, no lock tag is configured, or nothing was stuck.
    """
    if processing_tag_id is None:
        return 0

    if recovery_enabled is None:
        recovery_enabled = current_settings().STALE_LOCK_RECOVERY
    if not recovery_enabled:
        # Disabled deliberately for a multi-replica deployment: an unconditional
        # sweep here would steal peers' live locks (see the docstring). Log once
        # so the operator can see the orphan-recovery safety net is off by choice.
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

        # Remove lock tag and ensure the queue tag is present.
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
