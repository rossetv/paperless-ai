"""Pydantic wire models for the search HTTP API (spec §7.1).

The request/response shapes for ``POST /api/search`` and the converters between
them and the internal :mod:`search.models` dataclasses. This is one of the
boundary modules of the :mod:`search.wire` package — Pydantic lives here and at
the other wire modules, never in the pipeline (``CODE_GUIDELINES.md`` §5.6).

Allowed deps: pydantic, search.models, store (SearchFilters).
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator

from store import SearchFilters

if TYPE_CHECKING:
    from search.models import Cost, PhaseRecord, SearchResult, TokenUsage

# The documented maximum length of a search query / question (§10.4).  Long
# enough for any reasonable natural-language question; short enough to bound
# the token cost of an injected mega-prompt.  Applied identically at the HTTP
# boundary (``SearchRequest.query``) and the MCP boundary (``mcp_server``) so
# both surfaces enforce one limit (CODE_GUIDELINES §3.5).
MAX_QUERY_LENGTH = 4000

# The minimum length of a search query *after trimming* surrounding whitespace
# (§10.4/§10.6).  An empty or whitespace-only query carries no intent yet would
# still be dispatched into the bounded LLM pipeline — up to three chat calls —
# burning budget for nothing.  Rejecting it at the boundary (a 422 over REST, a
# structured error over MCP) is the cheap abuse defence.  Enforced identically
# at both surfaces via :func:`normalise_query`.
MIN_QUERY_LENGTH = 1


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class FilterRequest(BaseModel):
    """Optional filters supplied in a search request (spec §7.1).

    Every field defaults to absent; only the fields present in the request body
    are forwarded to the pipeline.  Extra keys are ignored — both the HTTP and
    the MCP boundary are lenient on unrecognised fields.
    """

    date_from: str | None = None
    date_to: str | None = None
    correspondent_id: int | None = None
    document_type_id: int | None = None
    tag_ids: list[int] = Field(default_factory=list)


def normalise_query(query: str) -> str:
    """Trim a query and reject it when nothing meaningful remains (§10.4).

    The single normalisation point for a search query, shared by the HTTP
    boundary (:class:`SearchRequest`) and the MCP boundary
    (``search.mcp_server``) so both surfaces apply one rule (§1.3): strip the
    surrounding whitespace, then reject an empty result. Returning the trimmed
    value means the pipeline only ever sees a normalised query.

    Args:
        query: The raw query string from the request body or tool call.

    Returns:
        The trimmed query.

    Raises:
        ValueError: When *query* is empty or whitespace-only after trimming,
            or longer than :data:`MAX_QUERY_LENGTH`.
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

    # max_length bounds the *raw* payload before trimming so an enormous
    # all-whitespace body is rejected by the cheap Pydantic constraint without
    # building the trimmed copy; normalise_query then trims and rejects an
    # empty result (§10.4/§10.6, HTTP-04/HTTP-07).
    query: str = Field(max_length=MAX_QUERY_LENGTH)
    filters: FilterRequest | None = None

    @field_validator("query")
    @classmethod
    def _normalise_query(cls, query: str) -> str:
        """Trim the query and reject an empty/whitespace-only one (§10.4)."""
        return normalise_query(query)


# ---------------------------------------------------------------------------
# Response sub-models
# ---------------------------------------------------------------------------


class SourceDocumentResponse(BaseModel):
    """One ranked source document in the search response.

    ``score`` is the rank-based RRF score, kept for ranking/MCP consumers but
    not shown in the web UI (it reads as a misleadingly tiny number);
    ``relevance_tier`` is the qualitative match strength the UI renders as a
    badge.
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


class QueryPlanResponse(BaseModel):
    """The query plan for UI transparency (spec §7.1)."""

    semantic_queries: list[str]
    keyword_terms: list[str]
    sub_questions: list[str]


class SearchStatsResponse(BaseModel):
    """Execution statistics for UI transparency and debugging."""

    llm_calls: int
    latency_ms: int
    refined: bool


class TokenUsageResponse(BaseModel):
    """Token counts for one or more LLM calls (spec §Telemetry).

    Mirrors :class:`~search.models.TokenUsage`: ``reasoning`` is a subset of
    ``completion`` (reasoning tokens bill as output) and must never be added to
    the cost separately; ``total`` is the API's ``total_tokens``.
    """

    prompt: int
    completion: int
    reasoning: int
    total: int


class CostResponse(BaseModel):
    """A priced cost for a phase (spec §Telemetry).

    ``usd`` is ``None`` for an unknown/unpriced model (the UI shows "—") and
    ``local`` is ``True`` for a local (Ollama) provider, where the cost is
    genuinely zero. Mirrors :class:`~search.models.Cost`.
    """

    usd: float | None
    local: bool


class PhaseRecordResponse(BaseModel):
    """One completed pipeline phase, for the live trace (spec §Telemetry).

    ``tokens``/``cost`` are ``None`` for the non-LLM phases (retrieve, gate,
    cache). ``detail`` is a per-phase free-form map the SPA renders (the
    planner's rewritten query, the judge's per-document verdicts, …). Mirrors
    :class:`~search.models.PhaseRecord`.
    """

    phase: str
    label: str
    detail: dict[str, object]
    tokens: TokenUsageResponse | None
    cost: CostResponse | None
    ms: int


class SearchTraceResponse(BaseModel):
    """The ordered per-phase trace assembled during a search (spec §Telemetry).

    Mirrors :class:`~search.models.SearchTrace`.
    """

    phases: list[PhaseRecordResponse]


class CostSummaryResponse(BaseModel):
    """Whole-query token + dollar-cost totals (spec §Telemetry).

    ``usd`` is ``None`` when any LLM call was unpriced-and-not-local (there is
    no honest total to show); ``local`` is ``True`` when every billed call was
    local. Mirrors :class:`~search.models.CostSummary`.
    """

    tokens: TokenUsageResponse
    usd: float | None
    local: bool
    llm_calls: int


class SearchResponse(BaseModel):
    """Response body for POST /api/search."""

    answer: str
    sources: list[SourceDocumentResponse]
    plan: QueryPlanResponse
    stats: SearchStatsResponse
    trace: SearchTraceResponse
    """The ordered per-phase reasoning trace (spec §Telemetry).

    Always produced now — the core assembles it on every result (empty for a
    Layer-1 clarify short-circuit). The SPA folds it into the "How this answer
    was found" disclosure; MCP/REST consumers may ignore it.
    """
    cost: CostSummaryResponse
    """Whole-query token + dollar-cost totals (spec §Telemetry).

    Always produced now. ``usd`` is ``None`` when the spend cannot be honestly
    priced (an unknown, non-local model); zero tokens price to ``$0.0``.
    """
    outcome_kind: Literal["answered", "clarify", "no_match"] = "answered"
    """Discriminator for the result type (spec §7.1).

    ``"answered"`` — the synthesiser produced a full answer with sources.
    ``"clarify"``  — the query was too vague; the answer carries a nudge
                     message and sources is empty (Layer 1 fail-fast).
    ``"no_match"`` — retrieval was too weak to synthesise from; the answer
                     carries a nudge message and sources is empty (Layer 2
                     fail-fast).
    """


# ---------------------------------------------------------------------------
# Mapping functions (wire model ⇄ dataclass)
# ---------------------------------------------------------------------------


def to_search_filters(filters: FilterRequest | None) -> SearchFilters | None:
    """Convert a validated :class:`FilterRequest` to the store input shape.

    The single converter from the wire filter shape to
    :class:`~store.models.SearchFilters`, reused by the HTTP ``/api/search``
    handler and the MCP server so both surfaces translate filters identically
    (``CODE_GUIDELINES.md`` §1.3).

    Args:
        filters: The validated filter model from a search request, or ``None``
            when the request carried no filters.

    Returns:
        A :class:`~store.models.SearchFilters` instance, or ``None`` when
        *filters* is ``None`` — meaning no filters are applied.
    """
    if filters is None:
        return None
    return SearchFilters(
        date_from=filters.date_from,
        date_to=filters.date_to,
        correspondent_id=filters.correspondent_id,
        document_type_id=filters.document_type_id,
        tag_ids=tuple(filters.tag_ids),
    )


def _to_token_usage(usage: TokenUsage | None) -> TokenUsageResponse | None:
    """Map a pipeline :class:`~search.models.TokenUsage` to the wire shape.

    ``None`` passes straight through — a non-LLM phase carries no token usage.
    """
    if usage is None:
        return None
    return TokenUsageResponse(
        prompt=usage.prompt,
        completion=usage.completion,
        reasoning=usage.reasoning,
        total=usage.total,
    )


def _to_cost(cost: Cost | None) -> CostResponse | None:
    """Map a pipeline :class:`~search.models.Cost` to the wire shape.

    ``None`` passes straight through — a non-LLM phase carries no cost.
    """
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
    """Convert a :class:`~search.models.SearchResult` to the wire model.

    This is the explicit, tested boundary conversion (``CODE_GUIDELINES.md``
    §5.6).  No Pydantic model leaks into the pipeline; no raw pipeline type
    leaks into the HTTP response.

    Args:
        result: The frozen dataclass produced by :meth:`~search.core.SearchCore.answer`.

    Returns:
        A :class:`SearchResponse` ready to serialise as JSON.
    """
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
        semantic_queries=list(result.plan.semantic_queries),
        keyword_terms=list(result.plan.keyword_terms),
        sub_questions=list(result.plan.sub_questions),
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
    )
    return SearchResponse(
        answer=result.answer,
        sources=sources,
        plan=plan,
        stats=stats,
        trace=trace,
        cost=cost,
        outcome_kind=result.outcome_kind,
    )
