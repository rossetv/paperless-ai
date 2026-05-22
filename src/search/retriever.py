"""Hybrid retriever with Reciprocal Rank Fusion for the search pipeline.

Combines vector search and keyword search results from the store into a single
ranked list of RetrievedChunk objects using Reciprocal Rank Fusion (RRF), then
returns the top-K documents' chunks ordered by fused score.

Also exposes ``resolve_filters``, which translates free-text filter candidates
(from the planner) into a ``SearchFilters`` instance by matching against the
real taxonomy.  UI-supplied filters bypass resolution entirely and are
authoritative (spec §6.1).

Allowed deps: store.reader (SearchFilters, StoreReader), store.models (ChunkHit,
    FacetSet, TaxonomyEntry), search.models (FilterCandidates, QueryPlan,
    RetrievedChunk), common.config (Settings), common.embeddings (EmbeddingClient,
    EMBEDDING_FAILURE_EXCEPTIONS).
Forbidden: no sqlite3, no FastAPI, no direct openai calls or imports — the
    OpenAI SDK is an implementation detail of common.embeddings.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import TYPE_CHECKING

import structlog

from common.embeddings import EMBEDDING_FAILURE_EXCEPTIONS
from search.models import FilterCandidates, QueryPlan, RetrievedChunk
from store.models import ChunkHit, FacetSet, TaxonomyEntry
from store.reader import SearchFilters, StoreReader

if TYPE_CHECKING:
    from common.config import Settings
    from common.embeddings import EmbeddingClient

log = structlog.get_logger(__name__)

# Reciprocal Rank Fusion smoothing constant (spec §6.2, CODE_GUIDELINES §3.5).
# The canonical value of 60 was established empirically in the original RRF paper
# (Cormack, Clarke, Buettcher 2009) and is the standard default for hybrid search.
_RRF_K = 60


# ---------------------------------------------------------------------------
# Filter resolution
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    """Normalise a string for fuzzy taxonomy matching.

    Applies:
    1. Unicode NFKC normalisation (collapses ligatures, compatibility chars).
    2. Lower-case folding.
    3. Removal of all non-alphanumeric characters (strips punctuation,
       hyphens, spaces, trailing dots, etc.).

    This makes "npower." == "npower" and "Gas-Bill" == "gas bill" == "gasbill".
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


def _match_name(
    candidate: str,
    entries: Sequence[TaxonomyEntry],
) -> int | None:
    """Resolve *candidate* against *entries*, returning the matched id or None.

    Resolution order:
    1. Exact string match on ``entry.name``.
    2. Normalised match via ``_normalise`` applied to both sides.

    If neither pass matches, returns ``None`` — the candidate is dropped, never
    guessed at a wrong id (spec §6.1).
    """
    # Pass 1: exact match.
    for entry in entries:
        if entry.name == candidate:
            return entry.id

    # Pass 2: case- and punctuation-normalised match.
    normalised_candidate = _normalise(candidate)
    for entry in entries:
        if _normalise(entry.name) == normalised_candidate:
            return entry.id

    return None


def resolve_filters(
    candidates: FilterCandidates,
    facets: FacetSet,
    *,
    ui_filters: SearchFilters | None,
) -> SearchFilters:
    """Resolve free-text planner candidates into a SearchFilters instance.

    If ``ui_filters`` is provided, it is returned as-is — UI filters are
    authoritative and bypass free-text resolution entirely (spec §6.1).

    Otherwise, each non-None candidate is resolved against ``facets``:
    - Exact name match is tried first.
    - Normalised (case- and punctuation-folded) match is tried second.
    - Anything that does NOT resolve to a real taxonomy id is dropped.

    Date candidates (``date_from`` / ``date_to``) pass through unchanged
    regardless of taxonomy resolution.

    Args:
        candidates: Free-text filter guesses from the planner.
        facets: Current taxonomy from ``StoreReader.list_facets()``.
        ui_filters: User-supplied explicit filters; overrides resolution when set.

    Returns:
        A SearchFilters instance ready to pass to StoreReader search methods.
    """
    # UI filters are authoritative — bypass resolution entirely.
    if ui_filters is not None:
        return ui_filters

    # Resolve correspondent.
    correspondent_id: int | None = None
    if candidates.correspondent is not None:
        correspondent_id = _match_name(candidates.correspondent, facets.correspondents)
        if correspondent_id is None:
            log.debug(
                "retriever.filter_candidate_dropped",
                kind="correspondent",
                candidate=candidates.correspondent,
            )

    # Resolve document type.
    document_type_id: int | None = None
    if candidates.document_type is not None:
        document_type_id = _match_name(candidates.document_type, facets.document_types)
        if document_type_id is None:
            log.debug(
                "retriever.filter_candidate_dropped",
                kind="document_type",
                candidate=candidates.document_type,
            )

    # Resolve tags — keep only those that resolve; drop the rest.
    resolved_tag_ids: list[int] = []
    for tag_candidate in candidates.tags:
        tag_id = _match_name(tag_candidate, facets.tags)
        if tag_id is not None:
            resolved_tag_ids.append(tag_id)
        else:
            log.debug(
                "retriever.filter_candidate_dropped",
                kind="tag",
                candidate=tag_candidate,
            )

    return SearchFilters(
        date_from=candidates.date_from,
        date_to=candidates.date_to,
        correspondent_id=correspondent_id,
        document_type_id=document_type_id,
        tag_ids=tuple(resolved_tag_ids),
    )


# ---------------------------------------------------------------------------
# RRF fusion
# ---------------------------------------------------------------------------


def _fuse_with_rrf(
    ranked_lists: list[list[ChunkHit]],
) -> tuple[dict[int, float], dict[int, ChunkHit]]:
    """Apply Reciprocal Rank Fusion across all ranked lists.

    Each chunk's fused score is the sum of ``1 / (_RRF_K + rank)`` over every
    ranked list it appears in, where ``rank`` is 1-based (position 0 in the
    list → rank 1, position 1 → rank 2, …).

    Using 1-based ranks is the standard RRF convention from the original paper
    (Cormack et al., 2009): ``score = Σ 1 / (k + r)``, where r ∈ {1, 2, …}.
    Position 0 therefore contributes ``1 / (60 + 1) = 1/61``.

    Args:
        ranked_lists: Any number of ranked lists; each is ordered best-first.

    Returns:
        A pair of ``{chunk_id: fused_score}`` and ``{chunk_id: ChunkHit}``,
        where the ChunkHit is the one from the first list the chunk appeared
        in.  Two plain dicts replace a mutable accumulator dataclass
        (CODE_GUIDELINES §1.3).
    """
    fused_score: dict[int, float] = {}
    first_hit: dict[int, ChunkHit] = {}

    for ranked_list in ranked_lists:
        for position, hit in enumerate(ranked_list):
            # 1-based rank: position 0 → rank 1.
            rank = position + 1
            contribution = 1.0 / (_RRF_K + rank)
            if hit.chunk_id in fused_score:
                # Accumulate the score; keep the first-seen ChunkHit.
                fused_score[hit.chunk_id] += contribution
            else:
                fused_score[hit.chunk_id] = contribution
                first_hit[hit.chunk_id] = hit

    return fused_score, first_hit


def _top_document_ids(
    fused_score: dict[int, float],
    first_hit: dict[int, ChunkHit],
    top_k: int,
) -> set[int]:
    """Return the ids of the *top_k* documents by their best chunk's score.

    A document may contribute several fused chunks; its rank is decided by the
    single highest fused score among them.  The ``top_k`` documents by that
    best score are returned as an id set.

    Args:
        fused_score: ``{chunk_id: fused_score}`` from :func:`_fuse_with_rrf`.
        first_hit: ``{chunk_id: ChunkHit}`` from :func:`_fuse_with_rrf`, used
            to resolve each chunk to its parent document.
        top_k: How many documents to keep.

    Returns:
        The set of the ``top_k`` highest-scoring documents' ids.
    """
    doc_best_score: dict[int, float] = {}
    for chunk_id, score in fused_score.items():
        document_id = first_hit[chunk_id].document_id
        if score > doc_best_score.get(document_id, -1.0):
            doc_best_score[document_id] = score

    ranked_doc_ids = sorted(doc_best_score.items(), key=lambda kv: kv[1], reverse=True)
    return {document_id for document_id, _ in ranked_doc_ids[:top_k]}


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------


class Retriever:
    """Hybrid retriever combining vector search, keyword search, and RRF.

    For each semantic query and sub-question in the plan, embeds the text and
    runs ``StoreReader.vector_search``.  For the keyword terms, runs
    ``StoreReader.keyword_search``.  All resulting ranked lists are fused with
    Reciprocal Rank Fusion.  Chunks are grouped by document; each document's
    score is its best chunk's fused score.  The top ``settings.SEARCH_TOP_K``
    documents are returned as ``RetrievedChunk`` objects ordered by fused score
    (highest first).

    Args:
        settings: Application settings; ``SEARCH_TOP_K`` is used.
        store_reader: The read-side store interface.
        embedding_client: The embedding client for query vectorisation.
    """

    def __init__(
        self,
        settings: Settings,
        store_reader: StoreReader,
        embedding_client: EmbeddingClient,
    ) -> None:
        self._settings = settings
        self._store_reader = store_reader
        self._embedding_client = embedding_client

    def _embed_queries(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts*, degrading to an empty result on any embedding failure.

        ``EmbeddingClient.embed`` can fail two ways — a non-retryable error (a
        bad/expired key, a 400) or a retryable one (an embedding-endpoint
        outage, sustained rate limiting) that exhausted its own retries.  Both
        are named by ``EMBEDDING_FAILURE_EXCEPTIONS``.  A search must not 500
        because the embedding backend is down: this catches that tuple, logs a
        warning, and returns ``[]`` so the query simply contributes no
        vector-search results — retrieval then falls through to its existing
        empty path (finding C3).

        Args:
            texts: The semantic queries and sub-questions to embed.

        Returns:
            One vector per input, or ``[]`` when embedding failed entirely.
        """
        try:
            return self._embedding_client.embed(texts)
        except EMBEDDING_FAILURE_EXCEPTIONS as exc:
            log.warning(
                "retriever.embedding_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                query_count=len(texts),
            )
            return []

    def retrieve(
        self,
        plan: QueryPlan,
        filters: SearchFilters,
    ) -> list[RetrievedChunk]:
        """Run hybrid retrieval and return top-K documents' chunks.

        Embeds all semantic queries and sub-questions in a single batch call
        (one round-trip to the embedding API), then runs vector search for each
        resulting embedding.  Runs keyword search once for all keyword terms.
        All ranked lists are fused with RRF.

        Groups fused chunks by document_id; each document is represented by its
        highest-scoring chunk.  Returns the top ``SEARCH_TOP_K`` documents'
        chunks, ordered by fused score descending.

        Args:
            plan: The query plan produced by the planner.
            filters: Pre-resolved SearchFilters to narrow the candidate set.

        Returns:
            A list of RetrievedChunk objects, one per chunk from the top-K
            documents, sorted by rrf_score descending.  Empty if no chunks are
            found.
        """
        top_k = self._settings.SEARCH_TOP_K
        ranked_lists: list[list[ChunkHit]] = []

        # Collect all texts that need embedding in one batch.
        texts_to_embed: list[str] = list(plan.semantic_queries) + list(
            plan.sub_questions
        )

        if texts_to_embed:
            embeddings = self._embed_queries(texts_to_embed)
            for embedding in embeddings:
                hits = self._store_reader.vector_search(embedding, top_k, filters)
                if hits:
                    ranked_lists.append(hits)

        # Keyword search over all keyword terms combined.
        if plan.keyword_terms:
            keyword_hits = self._store_reader.keyword_search(
                list(plan.keyword_terms), top_k, filters
            )
            if keyword_hits:
                ranked_lists.append(keyword_hits)

        if not ranked_lists:
            return []

        fused_score, first_hit = _fuse_with_rrf(ranked_lists)

        if not fused_score:
            return []

        top_doc_ids = _top_document_ids(fused_score, first_hit, top_k)

        # Collect all chunks from the top-K documents.
        chunks: list[RetrievedChunk] = [
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id=first_hit[chunk_id].document_id,
                text=first_hit[chunk_id].text,
                page_hint=first_hit[chunk_id].page_hint,
                rrf_score=score,
            )
            for chunk_id, score in fused_score.items()
            if first_hit[chunk_id].document_id in top_doc_ids
        ]

        # Sort highest fused score first.
        chunks.sort(key=lambda chunk: chunk.rrf_score, reverse=True)

        log.debug(
            "retriever.retrieve.complete",
            ranked_lists_count=len(ranked_lists),
            fused_chunks=len(fused_score),
            top_k=top_k,
            returned_chunks=len(chunks),
        )

        return chunks
