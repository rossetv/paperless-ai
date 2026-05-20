"""Frozen dataclasses for the search pipeline's public API surface.

These shapes travel between every stage of the pipeline — planner, retriever,
synthesiser, refinement, and core. Raw dicts and sqlite3.Row objects never
cross a stage boundary.

No stage imports Pydantic; validation happens only at the HTTP boundary in
api.py (CODE_GUIDELINES.md §5.6).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FilterCandidates:
    """Free-text filter guesses emitted by the planner (spec §6.1).

    The planner emits unresolved text; core.py resolves each candidate against
    the taxonomy table and drops anything that does not match — making
    hallucinated filters a code-level guarantee rather than a prompt concern.

    Attributes:
        correspondent: Free-text correspondent guess, or None.
        document_type: Free-text document-type guess, or None.
        tags: Tuple of free-text tag guesses (may be empty).
        date_from: ISO-8601 lower date bound, or None.
        date_to: ISO-8601 upper date bound, or None.
    """

    correspondent: str | None
    document_type: str | None
    tags: tuple[str, ...]
    date_from: str | None
    date_to: str | None


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """Structured output of the planner stage (spec §6.1).

    Attributes:
        semantic_queries: 1–3 rephrasings of the user query for vector search.
        keyword_terms: Exact terms or identifiers for FTS5 keyword search.
        filter_candidates: Free-text filter guesses to be resolved in code.
        sub_questions: Decomposed sub-questions for multi-hop retrieval.
    """

    semantic_queries: tuple[str, ...]
    keyword_terms: tuple[str, ...]
    filter_candidates: FilterCandidates
    sub_questions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A single chunk returned by the retriever after RRF fusion.

    Attributes:
        chunk_id: The chunks.id (== chunks_fts rowid) for this hit.
        document_id: The parent document's Paperless id.
        text: The chunk text, passed to the synthesiser as context.
        page_hint: Source page number for citations, or None.
        rrf_score: Reciprocal Rank Fusion score (higher is better).
    """

    chunk_id: int
    document_id: int
    text: str
    page_hint: int | None
    rrf_score: float


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """A ranked source document in the final search result (spec §6.4).

    Attributes:
        document_id: The Paperless document id.
        title: Document title resolved from the index, or None.
        correspondent: Correspondent display name resolved from taxonomy, or None.
        document_type: Document-type display name resolved from taxonomy, or None.
        created: Document creation date in UTC ISO-8601, or None.
        snippet: Representative text excerpt for display in the UI.
        paperless_url: Deep-link URL to the document in Paperless-ngx.
        score: Relevance score (higher is better).
    """

    document_id: int
    title: str | None
    correspondent: str | None
    document_type: str | None
    created: str | None
    snippet: str
    paperless_url: str
    score: float


@dataclass(frozen=True, slots=True)
class SearchStats:
    """Pipeline execution statistics returned with every SearchResult.

    Attributes:
        llm_calls: Number of LLM calls made (planner + synthesiser; max 3).
        latency_ms: Wall-clock time for the full pipeline in milliseconds.
        refined: Whether the bounded refinement loop was triggered.
    """

    llm_calls: int
    latency_ms: int
    refined: bool


@dataclass(frozen=True, slots=True)
class SearchResult:
    """The complete output of core.answer() (spec §6.4).

    Attributes:
        answer: Synthesised prose answer to the user's query.
        sources: Ranked source documents cited in the answer.
        plan: The query plan produced by the planner, for UI transparency.
        stats: Execution statistics, for UI transparency and debugging.
    """

    answer: str
    sources: tuple[SourceDocument, ...]
    plan: QueryPlan
    stats: SearchStats


# ---------------------------------------------------------------------------
# Discriminated synthesiser outcome (spec §6.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Answered:
    """The synthesiser produced a complete answer with source citations.

    Attributes:
        answer: The synthesised prose answer.
        citations: Tuple of document ids cited in the answer.
    """

    answer: str
    citations: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class NeedsMore:
    """The synthesiser determined retrieval was insufficient to answer.

    core.py uses this signal to trigger the single allowed refinement pass.

    Attributes:
        adjustment: A description of how the query plan should be adjusted
            to retrieve more relevant context.
    """

    adjustment: str


#: Discriminated union returned by the synthesiser.
#: Use isinstance(outcome, Answered) / isinstance(outcome, NeedsMore) to narrow.
AnswerOutcome = Answered | NeedsMore
