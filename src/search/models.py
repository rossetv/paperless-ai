"""Frozen dataclasses passed between the search pipeline's stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from common.llm import LlmCallUsage as LlmCallUsage  # re-exported for consumers
from search.relevance import RelevanceTier
from store.models import SearchFilters

#: ``"exploratory"`` lets the synthesiser return :class:`NeedsMore`;
#: ``"final"`` coerces it to :class:`Answered`.
SearchMode = Literal["exploratory", "final"]

#: Why a no-match result was produced, so the UI can show a tailored message:
#: ``"empty_retrieval"`` (no chunks), ``"weak_relevance"`` (best vector
#: similarity below the gate threshold), ``"judge_rejected"`` (the relevance
#: judge dropped every candidate).
NoMatchReason = Literal["empty_retrieval", "weak_relevance", "judge_rejected"]


@dataclass(frozen=True, slots=True)
class FilterCandidates:
    """Free-text filter guesses emitted by the planner.

    The core resolves each against the taxonomy and drops anything that does not
    match, so a hallucinated filter is stopped in code, not by the prompt. Dates
    are ISO-8601.
    """

    correspondent: str | None
    document_type: str | None
    tags: tuple[str, ...]
    date_from: str | None
    date_to: str | None


#: The "no filters at all" :class:`FilterCandidates`.
EMPTY_FILTER_CANDIDATES = FilterCandidates(
    correspondent=None,
    document_type=None,
    tags=(),
    date_from=None,
    date_to=None,
)


@dataclass(frozen=True, slots=True)
class PlannedSpec:
    """One planned search as the planner emits it — free-text filter GUESSES, not ids.

    mode selects the retrieval kind. ``semantic`` carries text to embed; ``keyword``
    carries FTS terms. ``filter_guess`` holds unresolved name/date guesses that code
    later resolves against the taxonomy and the deterministic date extractor.
    """

    mode: Literal["semantic", "keyword"]
    semantic: str | None
    keywords: tuple[str, ...]
    filter_guess: FilterCandidates
    rationale: str


@dataclass(frozen=True, slots=True)
class RetrievalSpec:
    """A resolved search (taxonomy ids, validated ISO dates) ready for the store."""

    mode: Literal["semantic", "keyword"]
    semantic: str | None
    keywords: tuple[str, ...]
    filters: SearchFilters
    rationale: str


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    """The planner's structured output: scoped searches, or a clarify signal."""

    specs: tuple[PlannedSpec, ...]
    clarify: ClarifyNeeded | None = None


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A single chunk returned by the retriever after RRF fusion.

    Attributes:
        chunk_id: The chunks.id (== chunks_fts rowid) for this hit.
        vector_similarity: Best absolute vector similarity
            (``1 / (1 + cosine_distance)``) across the vector passes, or None for
            a keyword-only hit. Unlike ``rrf_score`` it is absolute, not
            rank-based, and feeds the relevance tier.
    """

    chunk_id: int
    document_id: int
    text: str
    page_hint: int | None
    rrf_score: float
    vector_similarity: float | None = None


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """A ranked source document in the final search result.

    Attributes:
        score: RRF fused score, used for ranking only; the UI shows
            ``relevance_tier`` instead because the RRF score reads as a tiny
            number even for a perfect hit.
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
    call was local.

    Attributes:
        prices_as_of: The price book's effective date (``YYYY-MM-DD``), shown as
            "prices as of <date>".
        prices_source: ``"bundled"`` for the seed, or the refresh URL; ``""``
            only on the zero-cost default instance.
    """

    tokens: TokenUsage
    usd: float | None
    local: bool
    llm_calls: int
    prices_as_of: str | None = None
    prices_source: str = ""


@dataclass(frozen=True, slots=True)
class SearchStats:
    """Pipeline execution statistics returned with every SearchResult.

    Attributes:
        llm_calls: Number of LLM calls attempted. A stage that degrades after
            every model failed still counts, so on a degraded query this can
            exceed the number of calls billed.
        refined: Whether the bounded refinement loop was triggered.
    """

    llm_calls: int
    latency_ms: int
    refined: bool
    trace: SearchTrace = SearchTrace(phases=())
    cost: CostSummary = CostSummary(
        tokens=TokenUsage(0, 0, 0, 0), usd=None, local=False, llm_calls=0
    )


@dataclass(frozen=True, slots=True)
class SearchResult:
    """The complete output of core.answer().

    Attributes:
        outcome_kind: ``"answered"``, ``"clarify"`` (the planner judged the query
            too vague), or ``"no_match"`` (nothing relevant enough to answer from).
    """

    answer: str
    sources: tuple[SourceDocument, ...]
    plan: RetrievalPlan
    stats: SearchStats
    outcome_kind: Literal["answered", "clarify", "no_match"] = "answered"
    no_match_reason: NoMatchReason | None = None
    """Why the result is a no-match — ``None`` for ``"answered"`` and ``"clarify"`` results.

    Set on every ``"no_match"`` result to let the UI render a tailored message:
    ``"empty_retrieval"`` when the retriever found no chunks at all,
    ``"weak_relevance"`` when the Layer-2 gate rejected weak chunks, and
    ``"judge_rejected"`` when the Layer-3 judge dropped every candidate.
    """
    candidate_count: int | None = None
    """Number of distinct candidate documents considered before the no-match bail.

    ``None`` for ``"answered"`` and ``"clarify"`` results.  Matches the
    "Retrieving N documents" count in the retrieve trace phase so the UI message
    agrees with what the trace shows:
    - ``0`` for ``"empty_retrieval"`` (no documents were retrieved);
    - the distinct-document count over the retrieved chunks for
      ``"weak_relevance"`` and ``"judge_rejected"``.
    """


@dataclass(frozen=True, slots=True)
class Answered:
    """The synthesiser produced an answer; ``citations`` are document ids."""

    answer: str
    citations: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class NeedsMore:
    """Retrieval was insufficient; ``adjustment`` says how to re-plan.

    Triggers a refinement pass, bounded by SEARCH_MAX_REFINEMENTS.
    """

    adjustment: str


AnswerOutcome = Answered | NeedsMore


@dataclass(frozen=True, slots=True)
class ClarifyNeeded:
    """The planner judged the query too vague to search.

    The core returns it as a "be more specific" result without retrieving.
    """

    reason: str


PlanOutcome = RetrievalPlan | ClarifyNeeded


@dataclass(frozen=True, slots=True)
class JudgeCandidate:
    """One document offered to the relevance judge: its metadata and a snippet.

    The metadata lets the judge match the asked period or entity rather than
    the snippet text alone. A ``None`` field is left out of the prompt.
    """

    document_id: int
    snippet: str
    title: str | None = None
    created: str | None = None
    correspondent: str | None = None
    document_type: str | None = None


@dataclass(frozen=True, slots=True)
class DocVerdict:
    """The judge's per-document verdict: keep/drop, a reason, and a score.

    ``reason`` is empty when SEARCH_JUDGE_RATIONALES is off, or a short
    (length-capped) justification when on. It is model-generated text, rendered
    as escaped text on the client.

    ``score`` is the judge's confidence in [0, 1] and only ranks sources;
    ``keep`` alone decides. A degraded verdict keeps every document so a broken
    judge can never block an answer.
    """

    document_id: int
    keep: bool
    reason: str
    score: float = 0.0


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """The relevance judge's verdict — one :class:`DocVerdict` per candidate.

    An all-drop verdict with ``degraded=False`` means nothing is relevant and the
    core bails. On any judge failure every candidate is kept with
    ``degraded=True``.
    """

    verdicts: tuple[DocVerdict, ...]
    degraded: bool = False

    @property
    def relevant_document_ids(self) -> frozenset[int]:
        """Derive the set of kept document ids from the per-document verdicts."""
        return frozenset(v.document_id for v in self.verdicts if v.keep)


@dataclass(frozen=True, slots=True)
class RetrievalSignal:
    """Absolute relevance signals the RRF score discards.

    Lets the core decide, without another LLM call, whether the chunks are
    strong enough to synthesise from. ``best_vector_similarity`` is ``None``
    when no vector search ran or returned results.
    """

    best_vector_similarity: float | None
    has_keyword_hit: bool


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    """The full OCR text of one document, capped, for the MCP ``fetch_documents`` tool.

    ``total_chars`` is the untruncated length and ``returned_chars`` what
    ``content`` holds. On a per-id failure ``error`` carries a sanitised message
    and ``content`` is empty, so one bad id never fails the batch.
    """

    document_id: int
    title: str | None
    page_count: int | None
    paperless_url: str
    content: str
    truncated: bool
    total_chars: int
    returned_chars: int
    error: str | None = None
