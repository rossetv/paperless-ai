"""Turn retrieved chunks into the ranked source documents of a search result.

Chunks are grouped by document (best score, a snippet from the best chunk),
names are resolved in one store look-up, and each gets a Paperless link.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from search.models import RetrievedChunk, SourceDocument
from search.relevance import RelevanceThresholds, RelevanceTier, relevance_tier

if TYPE_CHECKING:
    from store.models import IndexedDocument
    from store.reader import StoreReader

# About three lines of text: enough to judge relevance.
_SNIPPET_MAX_CHARS = 280


def assemble_sources(
    chunks: list[RetrievedChunk],
    store_reader: StoreReader,
    paperless_public_url: str,
    thresholds: RelevanceThresholds,
    judge_scores: dict[int, float] | None = None,
) -> tuple[SourceDocument, ...]:
    """Build ranked source documents from the retrieved chunks.

    Documents sort by the judge's relevance score when there is one: the judge
    read each document's metadata and snippet, a far stronger signal than the
    rank-based RRF score. A document without a judge score sorts on its RRF
    score, which also breaks ties.

    Args:
        paperless_public_url: The browser-facing Paperless base URL, without
            a trailing slash.
        thresholds: Relevance-badge cut-points, applied to each document's
            best vector similarity.
        judge_scores: ``{document_id: judge_score}``; ``None`` when no judge ran.
    """
    if not chunks:
        return ()

    best_score, snippet, best_similarity = _best_chunk_per_document(chunks)
    document_ids = list(best_score.keys())
    indexed = store_reader.get_documents(document_ids)
    indexed_by_id = {document.id: document for document in indexed}
    scores = judge_scores or {}

    sources = [
        _build_source(
            document_id=document_id,
            score=best_score[document_id],
            snippet=snippet[document_id],
            tier=relevance_tier(best_similarity.get(document_id), thresholds),
            indexed=indexed_by_id.get(document_id),
            paperless_public_url=paperless_public_url,
        )
        for document_id in document_ids
    ]
    sources.sort(
        key=lambda source: (scores.get(source.document_id, source.score), source.score),
        reverse=True,
    )
    return tuple(sources)


def _build_source(
    *,
    document_id: int,
    score: float,
    snippet: str,
    tier: RelevanceTier,
    indexed: IndexedDocument | None,
    paperless_public_url: str,
) -> SourceDocument:
    """Build one SourceDocument, tolerating an absent index row.

    A document pruned between retrieval and assembly has no row; its chunk
    text is still real, so only the metadata fields fall back to None.
    """
    return SourceDocument(
        document_id=document_id,
        title=indexed.title if indexed is not None else None,
        correspondent=indexed.correspondent if indexed is not None else None,
        document_type=indexed.document_type if indexed is not None else None,
        created=indexed.created if indexed is not None else None,
        snippet=snippet,
        paperless_url=_paperless_url(paperless_public_url, document_id),
        score=score,
        relevance_tier=tier,
    )


def _paperless_url(paperless_public_url: str, document_id: int) -> str:
    """Return the Paperless-ngx web link for *document_id*.

    Built from ``PAPERLESS_PUBLIC_URL``, not ``PAPERLESS_URL``, which may be an
    internal address the user's browser cannot resolve.
    """
    return f"{paperless_public_url}/documents/{document_id}/"


def _best_chunk_per_document(
    chunks: list[RetrievedChunk],
) -> tuple[dict[int, float], dict[int, str], dict[int, float | None]]:
    """Reduce chunks to each document's best score, snippet and similarity.

    The snippet comes from the chunk with the best fused score. The similarity
    is the best vector similarity across all its chunks, tracked separately,
    and ``None`` only when every chunk was keyword-only.

    Returns:
        ``{document_id: best_score}``, ``{document_id: snippet}`` and
        ``{document_id: best_vector_similarity | None}``.
    """
    best_score: dict[int, float] = {}
    snippet: dict[int, str] = {}
    best_similarity: dict[int, float | None] = {}
    for chunk in chunks:
        current = best_score.get(chunk.document_id)
        if current is None or chunk.rrf_score > current:
            best_score[chunk.document_id] = chunk.rrf_score
            snippet[chunk.document_id] = _snippet(chunk.text)
        sim = chunk.vector_similarity
        if sim is not None:
            prior = best_similarity.get(chunk.document_id)
            if prior is None or sim > prior:
                best_similarity[chunk.document_id] = sim
        else:
            # Keyword-only chunk: record the document without clobbering a
            # real similarity.
            best_similarity.setdefault(chunk.document_id, None)
    return best_score, snippet, best_similarity


def _snippet(text: str) -> str:
    """Return the chunk text as a preview, whitespace collapsed and capped.

    OCR text is often ragged, hence the whitespace collapse.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= _SNIPPET_MAX_CHARS:
        return collapsed
    return collapsed[:_SNIPPET_MAX_CHARS].rstrip() + "…"
