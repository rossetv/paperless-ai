"""Source-document assembly for the search result (spec §6.4).

The retriever returns fused :class:`~search.models.RetrievedChunk` objects; the
public :class:`~search.models.SearchResult` carries ranked
:class:`~search.models.SourceDocument` objects instead. This module owns that
one transformation — group chunks by document (best score + a snippet from the
best chunk), resolve correspondent / document-type names via a single
``StoreReader.get_documents`` look-up, and attach a Paperless deep-link — so
``core.py`` stays a thin orchestrator (one concept per file, CODE_GUIDELINES
§3.2).

Every function here is pure given its arguments: the store reader and the
public base URL are passed in, not reached for, so the assembly is trivially
testable and ``core`` keeps ownership of the collaborators.

Allowed deps: search.models, search.relevance, store.models, store.reader,
    standard library.
Forbidden: no FastAPI, no MCP, no LLM/HTTP calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from search.models import RetrievedChunk, SourceDocument
from search.relevance import RelevanceTier, relevance_tier

if TYPE_CHECKING:
    from store.models import IndexedDocument
    from store.reader import StoreReader

# The maximum number of characters of chunk text shown as a source snippet in
# the UI.  A snippet is a preview, not the whole chunk; ~280 chars is roughly
# three lines and enough to judge relevance.
_SNIPPET_MAX_CHARS = 280


def assemble_sources(
    chunks: list[RetrievedChunk],
    store_reader: StoreReader,
    paperless_public_url: str,
) -> tuple[SourceDocument, ...]:
    """Build ranked SourceDocuments from the retrieved chunks.

    Groups chunks by document (keeping each document's best fused score, a
    snippet from its highest-scoring chunk, and its best absolute vector
    similarity), resolves correspondent and document-type names via one
    ``get_documents`` look-up, builds a Paperless deep-link, and derives the
    qualitative relevance tier from the similarity. Documents are ordered by
    score, highest first.

    Args:
        chunks: The fused chunks from retrieval (may be empty).
        store_reader: The read-side store, queried once for the documents'
            taxonomy-resolved metadata.
        paperless_public_url: The browser-facing Paperless base URL, already
            stripped of any trailing slash, used to build each deep-link.

    Returns:
        The ranked source documents, highest score first.
    """
    if not chunks:
        return ()

    best_score, snippet, best_similarity = _best_chunk_per_document(chunks)
    document_ids = list(best_score.keys())
    indexed = store_reader.get_documents(document_ids)
    indexed_by_id = {document.id: document for document in indexed}

    sources = [
        _build_source(
            document_id=document_id,
            score=best_score[document_id],
            snippet=snippet[document_id],
            tier=relevance_tier(best_similarity.get(document_id)),
            indexed=indexed_by_id.get(document_id),
            paperless_public_url=paperless_public_url,
        )
        for document_id in document_ids
    ]
    sources.sort(key=lambda source: source.score, reverse=True)
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

    A document can be missing from the index look-up if it was pruned between
    retrieval and assembly — a rare race. The source is still returned (the
    chunk text is real); only the taxonomy-resolved fields fall back to None.
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
    """Return the Paperless-ngx web deep-link for *document_id*.

    Built from ``PAPERLESS_PUBLIC_URL`` — the browser-facing base — not
    ``PAPERLESS_URL``, which may be an internal API address the user's browser
    cannot resolve. The base is stored already stripped of any trailing slash
    (see ``Settings.from_environment``); the document detail route in the
    Paperless-ngx UI is ``/documents/{id}/``.
    """
    return f"{paperless_public_url}/documents/{document_id}/"


def _best_chunk_per_document(
    chunks: list[RetrievedChunk],
) -> tuple[dict[int, float], dict[int, str], dict[int, float | None]]:
    """Reduce chunks to each document's best score, snippet, and similarity.

    A document may contribute several chunks; its source score is the highest
    fused score among them and its snippet is drawn from that best chunk. Its
    similarity is the highest absolute vector similarity across its chunks —
    tracked independently of the rrf_score winner, and ``None`` only when every
    contributing chunk was keyword-only. Iteration order does not matter — only
    strict comparisons decide the winners, so the reduction is deterministic.

    Returns:
        A triple of ``{document_id: best_score}``, ``{document_id: snippet}``,
        and ``{document_id: best_vector_similarity | None}``.
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
            # Ensure a keyword-only document still has an entry (None → the
            # keyword-only tier default), without clobbering a real similarity.
            best_similarity.setdefault(chunk.document_id, None)
    return best_score, snippet, best_similarity


def _snippet(text: str) -> str:
    """Return a UI-display snippet — the chunk text trimmed to a preview.

    Collapses internal whitespace runs (OCR text is often ragged) and caps the
    length at ``_SNIPPET_MAX_CHARS`` with an ellipsis when truncated.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= _SNIPPET_MAX_CHARS:
        return collapsed
    return collapsed[:_SNIPPET_MAX_CHARS].rstrip() + "…"
