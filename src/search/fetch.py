"""Full-document fetch assembly for the MCP ``fetch_documents`` tool (spec §4.3).

Pure given its arguments — the Paperless client, the store reader, the public
base URL, and the cap — exactly like :mod:`search.sources`. For each requested
id it fetches the canonical full OCR text from Paperless, caps it, and wraps it
with local metadata (title, page count, deep-link).

A per-id failure becomes an error-carrying :class:`~search.models.FetchedDocument`
rather than an exception, so one bad id cannot fail the whole batch. A 404 from
Paperless (unknown / deleted id) is reported as ``"not found"``; any other fault
is logged with its traceback server-side and reported as the sanitised
``"fetch failed"`` — no internal detail reaches the client (CODE_GUIDELINES §6.4).

Allowed deps: search.models, search.sources, common.paperless, store.reader,
    httpx, standard library. Forbidden: no FastAPI, no MCP, no LLM calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import structlog

from search.models import FetchedDocument
from search.sources import _paperless_url

if TYPE_CHECKING:
    from common.paperless import PaperlessClient
    from store.reader import StoreReader

log = structlog.get_logger(__name__)


def assemble_fetched(
    ids: list[int],
    paperless_client: PaperlessClient,
    store_reader: StoreReader,
    paperless_public_url: str,
    max_chars: int,
) -> list[FetchedDocument]:
    """Fetch and assemble full OCR text for each id, one result per id.

    Args:
        ids: Document ids to fetch (already validated/bounded by the caller).
        paperless_client: A per-request client; the caller owns its lifecycle
            (opening and closing it).
        store_reader: The local index, for wrapper metadata (title, page count).
        paperless_public_url: Browser-facing Paperless base URL (no trailing
            slash) for the deep-links.
        max_chars: Per-document character cap; longer content is truncated and
            flagged.

    Returns:
        One :class:`~search.models.FetchedDocument` per id, in request order.
    """
    results: list[FetchedDocument] = []
    for doc_id in ids:
        url = _paperless_url(paperless_public_url, doc_id)
        try:
            doc = paperless_client.get_document(doc_id)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 404:
                results.append(_error(doc_id, url, "not found"))
            else:
                log.exception("mcp.fetch_documents_error", document_id=doc_id)
                results.append(_error(doc_id, url, "fetch failed"))
            continue
        except Exception:
            log.exception("mcp.fetch_documents_error", document_id=doc_id)
            results.append(_error(doc_id, url, "fetch failed"))
            continue

        content = doc.get("content") or ""
        total = len(content)
        truncated = total > max_chars
        body = content[:max_chars] if truncated else content

        # Prefer the local index's resolved metadata; fall back to the Paperless
        # response for a document present upstream but not (yet) indexed.
        summary = store_reader.get_document_summary(doc_id)
        title = summary.title if summary is not None else doc.get("title")
        page_count = (
            summary.page_count if summary is not None else doc.get("page_count")
        )

        results.append(
            FetchedDocument(
                document_id=doc_id,
                title=title,
                page_count=page_count,
                paperless_url=url,
                content=body,
                truncated=truncated,
                total_chars=total,
                returned_chars=len(body),
            )
        )
    return results


def _error(doc_id: int, url: str, message: str) -> FetchedDocument:
    """Build a failure result for one id — empty content, sanitised message."""
    return FetchedDocument(
        document_id=doc_id,
        title=None,
        page_count=None,
        paperless_url=url,
        content="",
        truncated=False,
        total_chars=0,
        returned_chars=0,
        error=message,
    )
