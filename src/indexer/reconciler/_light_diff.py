"""Steady-state diff: skip watermark-page documents unchanged since indexing.

The sync pages a light ``{id, modified}`` projection and fetches a full
document only when its ``modified`` differs from the store's, so the recurring
overlap re-inclusion of classifier-PATCHed documents costs no OCR transfer.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

import structlog

from common.clock import normalise_paperless_timestamp, parse_paperless_timestamp
from common.paperless import PAPERLESS_CALL_EXCEPTIONS, PaperlessDocument
from indexer.reconciler._fanout import _index_documents
from indexer.worker import IndexOutcome

if TYPE_CHECKING:
    from concurrent.futures import ThreadPoolExecutor

    from common.paperless import PaperlessClient
    from indexer.worker import DocumentIndexer
    from store.models import IndexState

log = structlog.get_logger(__name__)

_LIGHT_DIFF_FIELDS: tuple[str, ...] = ("id", "modified")


class _LightDocumentRow(TypedDict):
    """A light ``{id, modified}`` Paperless projection row.

    ``modified`` may be absent on a malformed upstream row.
    """

    id: int
    modified: NotRequired[str | None]


def _is_unchanged(existing: IndexState | None, projected_modified: str | None) -> bool:
    """True when the document is stored and its normalised ``modified`` matches.

    Paperless bumps ``modified`` on every save, so equality means nothing
    changed. Fail-safe: two different instants cannot normalise to the same
    string, and a format that fails to match only costs a redundant fetch.
    """
    if existing is None:
        return False
    return normalise_paperless_timestamp(projected_modified) == existing.modified


def _diff_light_page(
    pool: ThreadPoolExecutor,
    indexer: DocumentIndexer,
    paperless: PaperlessClient,
    light_rows: Iterable[_LightDocumentRow],
    index_state: dict[int, IndexState],
) -> tuple[dict[int, IndexOutcome | None], set[int], datetime | None]:
    """Skip unchanged rows; fetch and index only new or changed documents.

    Every row, skipped or not, feeds the running ``modified`` maximum, or a
    skipped boundary document would re-enter forever. Returns
    ``(outcomes, page_ids, latest_modified)``; skipped ids are absent from
    *outcomes*.
    """
    outcomes: dict[int, IndexOutcome | None] = {}
    page_ids: set[int] = set()
    latest_modified: datetime | None = None
    to_fetch: list[int] = []

    for row in light_rows:
        document_id = row["id"]
        page_ids.add(document_id)
        latest_modified = _fold_modified(
            latest_modified, row.get("modified"), document_id
        )
        if _is_unchanged(index_state.get(document_id), row.get("modified")):
            continue
        to_fetch.append(document_id)

    if to_fetch:
        skipped = len(page_ids) - len(to_fetch)
        log.info(
            "reconcile.steady_state_skipped",
            skipped=skipped,
            to_fetch=len(to_fetch),
        )
        changed_documents = _fetch_full_documents(paperless, to_fetch, outcomes)
        outcomes.update(_index_documents(pool, indexer, changed_documents, index_state))
    else:
        log.info("reconcile.steady_state_all_unchanged", skipped=len(page_ids))

    return outcomes, page_ids, latest_modified


def _fetch_full_documents(
    paperless: PaperlessClient,
    document_ids: list[int],
    outcomes: dict[int, IndexOutcome | None],
) -> list[PaperlessDocument]:
    """Fetch each changed document in full.

    A fetch failure is recorded as a ``None`` outcome in *outcomes*, so the
    failed-document map retries it next cycle.
    """
    fetched: list[PaperlessDocument] = []
    for document_id in document_ids:
        try:
            fetched.append(
                cast("PaperlessDocument", paperless.get_document(document_id))
            )
        except PAPERLESS_CALL_EXCEPTIONS:
            log.exception(
                "reconcile.changed_document_fetch_failed", document_id=document_id
            )
            outcomes[document_id] = None
    return fetched


def _fold_modified(
    latest: datetime | None, raw: str | None, document_id: int | None
) -> datetime | None:
    """Fold one raw ``modified`` string into the running maximum *latest*.

    A missing value is ignored; an unparseable one is logged and ignored, so a
    malformed upstream timestamp never aborts the watermark advance.
    """
    if not raw:
        return latest
    parsed = parse_paperless_timestamp(raw)
    if parsed is None:
        log.warning(
            "reconcile.unparseable_modified", document_id=document_id, modified=raw
        )
        return latest
    if latest is None or parsed > latest:
        return parsed
    return latest
