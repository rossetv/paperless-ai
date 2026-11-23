"""Wire models for ``POST /api/search`` and their converters."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, field_validator

from search.dates import normalise_iso_date
from search.models import NoMatchReason
from store import SearchFilters

if TYPE_CHECKING:
    from search.models import Cost, PhaseRecord, SearchResult, TokenUsage

# Long enough for any real question; short enough to bound the token cost of
# an injected mega-prompt. Shared by REST and MCP.
MAX_QUERY_LENGTH = 4000

# Measured after trimming: a blank query would still spend LLM calls.
MIN_QUERY_LENGTH = 1

# The SQLite integer range: a wider id cannot be bound to a query.
FILTER_ID_MIN = -(2**63)
FILTER_ID_MAX = 2**63 - 1
FilterId = Annotated[int, Field(ge=FILTER_ID_MIN, le=FILTER_ID_MAX)]


def _readable_date(value: str | None) -> str | None:
    """Pass a blank or absent date through; refuse one that cannot be read."""
    if value and value.strip() and normalise_iso_date(value) is None:
        raise ValueError("must be a date in YYYY-MM-DD form")
    return value


# A blank date means no filter; anything else must be readable as a date.
FilterDate = Annotated[str | None, AfterValidator(_readable_date)]


def _library_date(value: str | None) -> str | None:
    """Like :func:`_readable_date`, but by the store's own leading-day parse.

    The Library listing has always honoured compact forms such as
    ``20240101`` and ``2024W014``.
    """
    if value and value.strip():
        try:
            date.fromisoformat(value[:10])
        except ValueError:
            raise ValueError("must be a date in YYYY-MM-DD form") from None
    return value


# The Library listing's date parameter: blank means no filter.
LibraryDate = Annotated[str | None, AfterValidator(_library_date)]


class FilterRequest(BaseModel):
    """Optional filters supplied in a search request; unknown keys are ignored."""

    date_from: FilterDate = None
    date_to: FilterDate = None
    correspondent_id: FilterId | None = None
    document_type_id: FilterId | None = None
    # Same bound as GET /api/documents: an unbounded list is cheap payload bloat.
    tag_ids: list[FilterId] = Field(default_factory=list, max_length=64)


def normalise_query(query: str) -> str:
    """Return the trimmed query, shared by the REST and MCP boundaries.

    Raises:
        ValueError: When *query* is blank or longer than
            :data:`MAX_QUERY_LENGTH`.
    """
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(
            f"query exceeds the maximum length of {MAX_QUERY_LENGTH} characters"
        )
    trimmed = query.strip()
    if len(trimmed) < MIN_QUERY_LENGTH:
        raise ValueError("query must not be empty or whitespace-only")
    return trimmed


class SearchRequest(BaseModel):
    """Body for POST /api/search."""

    # Bounds the raw payload, so a huge all-whitespace body is rejected before
    # a trimmed copy is built.
    query: str = Field(max_length=MAX_QUERY_LENGTH)
    filters: FilterRequest | None = None

    @field_validator("query")
    @classmethod
    def _normalise_query(cls, query: str) -> str:
        """Trim the query and reject a blank one."""
        return normalise_query(query)


class SourceDocumentResponse(BaseModel):
    """One ranked source document in the search response.

    ``score`` is the rank-based RRF score, not shown in the web UI because it
    reads as a misleadingly tiny number; the UI shows ``relevance_tier``.
    """

    document_id: int
    title: str | None
    correspondent: str | None
    document_type: str | None
    created: str | None
    snippet: str
    paperless_url: str
    score: float
    relevance_tier: str


class SpecResponse(BaseModel):
    """One planned search in the query plan, shown to the user.

    Carries the planner's free-text filter guesses, not resolved taxonomy ids.
    """

    mode: str
    semantic: str | None
    keywords: list[str]
    correspondent: str | None
    document_type: str | None
    tags: list[str]
    date_from: str | None
    date_to: str | None
    rationale: str


class QueryPlanResponse(BaseModel):
    """The multi-spec query plan, shown to the user."""

    specs: list[SpecResponse]


class SearchStatsResponse(BaseModel):
    """Execution statistics for UI transparency and debugging."""

    llm_calls: int
    latency_ms: int
    refined: bool


class TokenUsageResponse(BaseModel):
    """Token counts for one or more LLM calls.

    ``reasoning`` is a subset of ``completion`` (reasoning bills as output), so
    it must never be added to the cost separately.
    """

    prompt: int
    completion: int
    reasoning: int
    total: int


class CostResponse(BaseModel):
    """A priced cost for a phase.

    ``usd`` is ``None`` for an unpriced model; ``local`` is ``True`` for a
    local (Ollama) provider, where the cost is genuinely zero.
    """

    usd: float | None
    local: bool


class PhaseRecordResponse(BaseModel):
    """One completed pipeline phase, for the live trace.

    ``tokens``/``cost`` are ``None`` for non-LLM phases. ``detail`` is a
    free-form per-phase map, such as the judge's per-document verdicts.
    """

    phase: str
    label: str
    detail: dict[str, object]
    tokens: TokenUsageResponse | None
    cost: CostResponse | None
    ms: int


class SearchTraceResponse(BaseModel):
    """The ordered per-phase trace assembled during a search."""

    phases: list[PhaseRecordResponse]


class CostSummaryResponse(BaseModel):
    """Whole-query token and dollar-cost totals.

    ``usd`` is ``None`` when any call was unpriced and not local, since there
    is no honest total. ``prices_as_of`` / ``prices_source`` say which price
    table was used (``"bundled"`` or the refresh URL).
    """

    tokens: TokenUsageResponse
    usd: float | None
    local: bool
    llm_calls: int
    prices_as_of: str | None = None
    prices_source: str = ""


class SearchResponse(BaseModel):
    """Response body for POST /api/search."""

    answer: str
    sources: list[SourceDocumentResponse]
    plan: QueryPlanResponse
    stats: SearchStatsResponse
    trace: SearchTraceResponse
    """The ordered per-phase reasoning trace; empty for a clarify result."""
    cost: CostSummaryResponse
    """Whole-query token and dollar totals.

    ``usd`` is ``None`` when an unknown, non-local model makes the spend
    unpriceable.
    """
    outcome_kind: Literal["answered", "clarify", "no_match"] = "answered"
    """``"clarify"`` and ``"no_match"`` carry a nudge message and no sources."""
    no_match_reason: NoMatchReason | None = None
    """Why the result is a no-match — ``None`` for ``"answered"`` and ``"clarify"`` results.

    ``"empty_retrieval"`` — the retriever found no chunks at all.
    ``"weak_relevance"`` — the Layer-2 gate rejected the retrieved chunks.
    ``"judge_rejected"`` — the Layer-3 judge dropped every candidate.
    """
    candidate_count: int | None = None
    """Number of distinct candidate documents considered before the no-match bail.

    ``None`` for ``"answered"`` and ``"clarify"`` results. Matches the
    "Retrieving N documents" count in the retrieve trace phase: ``0`` for
    ``"empty_retrieval"``, otherwise the distinct-document count over the
    retrieved chunks.
    """


def to_search_filters(filters: FilterRequest | None) -> SearchFilters | None:
    """Convert a :class:`FilterRequest` to store filters; shared by REST and MCP."""
    if filters is None:
        return None
    return SearchFilters(
        date_from=normalise_iso_date(filters.date_from) if filters.date_from else None,
        date_to=normalise_iso_date(filters.date_to) if filters.date_to else None,
        correspondent_id=filters.correspondent_id,
        document_type_id=filters.document_type_id,
        tag_ids=tuple(filters.tag_ids),
    )


def _to_token_usage(usage: TokenUsage | None) -> TokenUsageResponse | None:
    """Map a :class:`~search.models.TokenUsage` to the wire shape."""
    if usage is None:
        return None
    return TokenUsageResponse(
        prompt=usage.prompt,
        completion=usage.completion,
        reasoning=usage.reasoning,
        total=usage.total,
    )


def _to_cost(cost: Cost | None) -> CostResponse | None:
    """Map a :class:`~search.models.Cost` to the wire shape."""
    if cost is None:
        return None
    return CostResponse(usd=cost.usd, local=cost.local)


def _to_phase_record(record: PhaseRecord) -> PhaseRecordResponse:
    """Map one pipeline :class:`~search.models.PhaseRecord` to the wire shape."""
    return PhaseRecordResponse(
        phase=record.phase,
        label=record.label,
        detail=record.detail,
        tokens=_to_token_usage(record.tokens),
        cost=_to_cost(record.cost),
        ms=record.ms,
    )


def to_search_response(result: SearchResult) -> SearchResponse:
    """Convert a :class:`~search.models.SearchResult` to the wire model."""
    sources = [
        SourceDocumentResponse(
            document_id=src.document_id,
            title=src.title,
            correspondent=src.correspondent,
            document_type=src.document_type,
            created=src.created,
            snippet=src.snippet,
            paperless_url=src.paperless_url,
            score=src.score,
            relevance_tier=src.relevance_tier,
        )
        for src in result.sources
    ]
    plan = QueryPlanResponse(
        specs=[
            SpecResponse(
                mode=spec.mode,
                semantic=spec.semantic,
                keywords=list(spec.keywords),
                correspondent=spec.filter_guess.correspondent,
                document_type=spec.filter_guess.document_type,
                tags=list(spec.filter_guess.tags),
                date_from=spec.filter_guess.date_from,
                date_to=spec.filter_guess.date_to,
                rationale=spec.rationale,
            )
            for spec in result.plan.specs
        ]
    )
    stats = SearchStatsResponse(
        llm_calls=result.stats.llm_calls,
        latency_ms=result.stats.latency_ms,
        refined=result.stats.refined,
    )
    trace = SearchTraceResponse(
        phases=[_to_phase_record(phase) for phase in result.stats.trace.phases]
    )
    cost_summary = result.stats.cost
    cost = CostSummaryResponse(
        tokens=TokenUsageResponse(
            prompt=cost_summary.tokens.prompt,
            completion=cost_summary.tokens.completion,
            reasoning=cost_summary.tokens.reasoning,
            total=cost_summary.tokens.total,
        ),
        usd=cost_summary.usd,
        local=cost_summary.local,
        llm_calls=cost_summary.llm_calls,
        prices_as_of=cost_summary.prices_as_of,
        prices_source=cost_summary.prices_source,
    )
    return SearchResponse(
        answer=result.answer,
        sources=sources,
        plan=plan,
        stats=stats,
        trace=trace,
        cost=cost,
        outcome_kind=result.outcome_kind,
        no_match_reason=result.no_match_reason,
        candidate_count=result.candidate_count,
    )
