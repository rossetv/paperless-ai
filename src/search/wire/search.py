"""Pydantic wire models for the search HTTP API (spec §7.1).

The request/response shapes for ``POST /api/search`` and the converters between
them and the internal :mod:`search.models` dataclasses. This is one of the
boundary modules of the :mod:`search.wire` package — Pydantic lives here and at
the other wire modules, never in the pipeline (``CODE_GUIDELINES.md`` §5.6).

Allowed deps: pydantic, search.models, store (SearchFilters).
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from store import SearchFilters

if TYPE_CHECKING:
    from search.models import SearchResult

# The documented maximum length of a search query / question (§10.4).  Long
# enough for any reasonable natural-language question; short enough to bound
# the token cost of an injected mega-prompt.  Applied identically at the HTTP
# boundary (``SearchRequest.query``) and the MCP boundary (``mcp_server``) so
# both surfaces enforce one limit (CODE_GUIDELINES §3.5).
MAX_QUERY_LENGTH = 4000


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


class SearchRequest(BaseModel):
    """Body for POST /api/search."""

    query: str = Field(max_length=MAX_QUERY_LENGTH)
    filters: FilterRequest | None = None


# ---------------------------------------------------------------------------
# Response sub-models
# ---------------------------------------------------------------------------


class SourceDocumentResponse(BaseModel):
    """One ranked source document in the search response."""

    document_id: int
    title: str | None
    correspondent: str | None
    document_type: str | None
    created: str | None
    snippet: str
    paperless_url: str
    score: float


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


class SearchResponse(BaseModel):
    """Response body for POST /api/search."""

    answer: str
    sources: list[SourceDocumentResponse]
    plan: QueryPlanResponse
    stats: SearchStatsResponse


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
    return SearchResponse(answer=result.answer, sources=sources, plan=plan, stats=stats)
