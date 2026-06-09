"""Frozen dataclasses for the search pipeline's public API surface.

These shapes travel between every stage of the pipeline — planner, retriever,
synthesiser, refinement, and core. Raw dicts and sqlite3.Row objects never
cross a stage boundary.

No stage imports Pydantic; validation happens only at the HTTP boundary in
api.py (CODE_GUIDELINES.md §5.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from common.llm import LlmCallUsage as LlmCallUsage  # re-exported for consumers
from search.relevance import RelevanceTier

#: The synthesiser's two operating modes (spec §6.3).  ``"exploratory"`` lets
#: the model return :class:`NeedsMore`; ``"final"`` coerces it to
#: :class:`Answered`.  A :data:`~typing.Literal` makes a typo at any of the
#: four call layers a type error rather than a silent runtime fallthrough.
SearchMode = Literal["exploratory", "final"]


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


#: The canonical "no filters at all" :class:`FilterCandidates`.  The planner
#: fallback, ``broaden_plan``, and tests all need an all-``None`` instance;
#: sharing one well-known value avoids re-constructing it ad hoc at every site
#: (``CODE_GUIDELINES.md`` §3.5).  Safe to share — ``FilterCandidates`` is
#: frozen, so the singleton cannot be mutated.
EMPTY_FILTER_CANDIDATES = FilterCandidates(
    correspondent=None,
    document_type=None,
    tags=(),
    date_from=None,
    date_to=None,
)


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
        vector_similarity: Best absolute vector similarity
            (``1 / (1 + cosine_distance)``) for this chunk across the vector
            passes, or None when it was retrieved by keyword search alone.
            Feeds the per-document relevance tier; unlike ``rrf_score`` it is an
            absolute signal, not a rank-based one.
    """

    chunk_id: int
    document_id: int
    text: str
    page_hint: int | None
    rrf_score: float
    vector_similarity: float | None = None


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
        score: RRF fused score, used for ranking (higher is better). Not shown
            in the UI — it is rank-based and reads as a misleadingly tiny number
            even for a perfect hit; the qualitative ``relevance_tier`` is
            displayed instead.
        relevance_tier: Qualitative match strength — "strong" / "good" /
            "partial" / "weak" — derived from the document's absolute vector
            similarity. What the UI renders as the relevance badge.
    """

    document_id: int
    title: str | None
    correspondent: str | None
    document_type: str | None
    created: str | None
    snippet: str
    paperless_url: str
    score: float
    relevance_tier: RelevanceTier = "good"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token counts for one or more LLM calls. ``reasoning`` is a subset of
    ``completion`` (reasoning tokens bill as output); ``total`` == prompt +
    completion (the API's ``total_tokens``)."""

    prompt: int
    completion: int
    reasoning: int
    total: int


@dataclass(frozen=True, slots=True)
class Cost:
    """A priced cost. ``usd`` is None for an unknown/unpriced model; ``local`` is
    True for a local (Ollama) provider, where cost is genuinely zero."""

    usd: float | None
    local: bool


@dataclass(frozen=True, slots=True)
class PhaseRecord:
    """One completed pipeline phase, for the trace. ``tokens``/``cost`` are None
    for non-LLM phases (retrieve, gate, cache)."""

    phase: str
    label: str
    detail: dict[str, object]
    tokens: TokenUsage | None
    cost: Cost | None
    ms: int


@dataclass(frozen=True, slots=True)
class SearchTrace:
    """The ordered per-phase trace assembled during a search."""

    phases: tuple[PhaseRecord, ...]


@dataclass(frozen=True, slots=True)
class CostSummary:
    """Whole-query token + cost totals. ``usd`` is None when any LLM call was
    unpriced-and-not-local (no honest total). ``local`` is True when every billed
    call was local."""

    tokens: TokenUsage
    usd: float | None
    local: bool
    llm_calls: int


@dataclass(frozen=True, slots=True)
class SearchStats:
    """Pipeline execution statistics returned with every SearchResult.

    Attributes:
        llm_calls: Number of LLM calls *attempted* (planner + synthesiser; max
            3). A stage that degrades to its fallback after every model failed
            is counted here too, so on a degraded query this can exceed the
            number of calls actually billed; on a successful query they match.
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
        outcome_kind: Discriminator for the result type — ``"answered"`` (the
            synthesiser produced an answer), ``"clarify"`` (the planner judged
            the query too vague, Layer 1 fail-fast), or ``"no_match"`` (the
            retrieved chunks were too weak to synthesise from, Layer 2
            fail-fast).  Defaults to ``"answered"`` so all existing
            constructions stay valid without changes.
    """

    answer: str
    sources: tuple[SourceDocument, ...]
    plan: QueryPlan
    stats: SearchStats
    outcome_kind: Literal["answered", "clarify", "no_match"] = "answered"


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


# ---------------------------------------------------------------------------
# Planner fail-fast signal (Layer 1) — spec §7.1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClarifyNeeded:
    """The planner judged the query too vague/insufficient to search (Layer 1).

    Returned by the planner *instead of* a :class:`QueryPlan`; the core
    surfaces it as a 'be more specific' result without retrieving or
    synthesising.

    Attributes:
        reason: A human-readable explanation of why the query was rejected.
    """

    reason: str


#: Discriminated union returned by the planner stage.
#: Use isinstance(outcome, QueryPlan) / isinstance(outcome, ClarifyNeeded) to narrow.
PlanOutcome = QueryPlan | ClarifyNeeded


# ---------------------------------------------------------------------------
# Relevance judge shapes (Layer 3) — spec §7.3
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JudgeCandidate:
    """One document offered to the relevance judge: its id and a best-chunk snippet."""

    document_id: int
    snippet: str


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """The relevance judge's verdict.

    ``relevant_document_ids`` are the documents to keep. An empty set with
    ``degraded=False`` means "nothing is relevant" → the core bails. On any judge
    failure the verdict carries the full candidate set with ``degraded=True``
    (fail-open: keep everything), so a broken judge never suppresses an answer.
    """

    relevant_document_ids: frozenset[int]
    degraded: bool = False


# ---------------------------------------------------------------------------
# Retrieval quality signal (Layer 2) — spec §7.2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RetrievalSignal:
    """Absolute relevance signals the RRF score discards (Layer 2).

    The retriever attaches this to its output so the core can decide whether
    the retrieved chunks are strong enough to synthesise from without an
    additional LLM call.

    Attributes:
        best_vector_similarity: Best raw vector similarity across the retrieved
            chunks (higher = closer), or ``None`` when no vector search ran or
            returned results.
        has_keyword_hit: ``True`` when the FTS5 keyword search returned a
            genuine match.
    """

    best_vector_similarity: float | None
    has_keyword_hit: bool
