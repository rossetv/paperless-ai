"""Pydantic request/response models for the search HTTP API (spec §7.1).

This module is the **only** place Pydantic models exist in the search package
(``CODE_GUIDELINES.md`` §5.6).  Once an HTTP request is validated here, the
internal pipeline works entirely with frozen dataclasses from
:mod:`search.models` and :mod:`store.models`.

Public surface
--------------
Request models:
    :class:`LoginRequest`, :class:`FilterRequest`, :class:`SearchRequest`

Response models:
    :class:`SearchResponse`, :class:`FacetsResponse`, :class:`StatsResponse`

Mapping functions (wire model ⇄ internal dataclass):
    :func:`to_search_filters` (request → store input shape),
    :func:`to_search_response`, :func:`to_facets_response`,
    :func:`to_stats_response`

Constants:
    :data:`MAX_QUERY_LENGTH` — the documented maximum query length, applied at
    every search boundary (HTTP and MCP).

Allowed deps: pydantic, search.models, store (SearchFilters), store.models.
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from search.validation import (
    validate_display_name,
    validate_email,
    validate_password,
    validate_role,
    validate_username,
)
from store import SearchFilters

if TYPE_CHECKING:
    from appdb.users import User
    from search.models import SearchResult
    from store.models import FacetSet, IndexStats

# The documented maximum length of a search query / question (§10.4).  Long
# enough for any reasonable natural-language question; short enough to bound
# the token cost of an injected mega-prompt.  Applied identically at the HTTP
# boundary (``SearchRequest.query``) and the MCP boundary (``mcp_server``) so
# both surfaces enforce one limit (CODE_GUIDELINES §3.5).
MAX_QUERY_LENGTH = 4000


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Body for ``POST /api/auth/login`` — username/password credentials.

    Replaces the Wave 0 ``{api_key}`` body. ``remember`` selects the session
    lifetime: ticked → seven days, un-ticked → eight hours (spec §4.4).
    """

    username: str
    password: str
    remember: bool = False

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        """Reject a username that breaks the length/charset contract."""
        return validate_username(value)

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        """Reject a password shorter than the minimum length."""
        return validate_password(value)


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


class TaxonomyEntryResponse(BaseModel):
    """A single taxonomy entry as returned to the browser."""

    kind: str
    id: int
    name: str


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


# ---------------------------------------------------------------------------
# Top-level response models
# ---------------------------------------------------------------------------


class SearchResponse(BaseModel):
    """Response body for POST /api/search."""

    answer: str
    sources: list[SourceDocumentResponse]
    plan: QueryPlanResponse
    stats: SearchStatsResponse


class FacetsResponse(BaseModel):
    """Response body for GET /api/facets."""

    correspondents: list[TaxonomyEntryResponse]
    document_types: list[TaxonomyEntryResponse]
    tags: list[TaxonomyEntryResponse]
    earliest: str | None
    latest: str | None


class StatsResponse(BaseModel):
    """Response body for GET /api/stats."""

    document_count: int
    chunk_count: int
    last_reconcile_at: str | None
    embedding_model: str | None


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


def to_facets_response(facets: FacetSet) -> FacetsResponse:
    """Convert a :class:`~store.models.FacetSet` to the wire model.

    Args:
        facets: The frozen dataclass from :meth:`~store.reader.StoreReader.list_facets`.

    Returns:
        A :class:`FacetsResponse` ready to serialise as JSON.
    """
    return FacetsResponse(
        correspondents=[
            TaxonomyEntryResponse(kind=e.kind, id=e.id, name=e.name)
            for e in facets.correspondents
        ],
        document_types=[
            TaxonomyEntryResponse(kind=e.kind, id=e.id, name=e.name)
            for e in facets.document_types
        ],
        tags=[
            TaxonomyEntryResponse(kind=e.kind, id=e.id, name=e.name)
            for e in facets.tags
        ],
        earliest=facets.earliest,
        latest=facets.latest,
    )


def to_stats_response(stats: IndexStats) -> StatsResponse:
    """Convert an :class:`~store.models.IndexStats` to the wire model.

    Args:
        stats: The frozen dataclass from :meth:`~store.reader.StoreReader.get_stats`.

    Returns:
        A :class:`StatsResponse` ready to serialise as JSON.
    """
    return StatsResponse(
        document_count=stats.document_count,
        chunk_count=stats.chunk_count,
        last_reconcile_at=stats.last_reconcile_at,
        embedding_model=stats.embedding_model,
    )


# ---------------------------------------------------------------------------
# Account request models (web-redesign §4.6)
# ---------------------------------------------------------------------------


class SetupRequest(BaseModel):
    """Body for ``POST /api/setup`` — the setup token plus the first admin."""

    token: str
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        """Reject an admin username that breaks the contract."""
        return validate_username(value)

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        """Reject an admin password shorter than the minimum length."""
        return validate_password(value)


class CreateUserRequest(BaseModel):
    """Body for ``POST /api/users`` — a new account created by an admin."""

    username: str
    password: str
    role: str
    display_name: str | None = None
    email: str | None = None

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        """Reject a username that breaks the length/charset contract."""
        return validate_username(value)

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        """Reject a password shorter than the minimum length."""
        return validate_password(value)

    @field_validator("role")
    @classmethod
    def _check_role(cls, value: str) -> str:
        """Reject a role outside the admin/member/readonly enum."""
        return validate_role(value)

    @field_validator("display_name")
    @classmethod
    def _check_display_name(cls, value: str | None) -> str | None:
        """Reject a display name longer than the cap."""
        return validate_display_name(value)

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str | None) -> str | None:
        """Reject an email that does not look like an address."""
        return validate_email(value)


class UpdateUserRequest(BaseModel):
    """Body for ``PATCH /api/users/{id}`` — a partial account update.

    Every field is optional; only those present are applied. ``status``
    accepts ``active`` or ``suspended``; ``password`` triggers a reset.
    """

    display_name: str | None = None
    email: str | None = None
    role: str | None = None
    status: str | None = None
    password: str | None = None

    @field_validator("role")
    @classmethod
    def _check_role(cls, value: str | None) -> str | None:
        """Reject a role outside the enum when one is supplied."""
        return value if value is None else validate_role(value)

    @field_validator("status")
    @classmethod
    def _check_status(cls, value: str | None) -> str | None:
        """Reject a status outside active/suspended when one is supplied."""
        if value is not None and value not in ("active", "suspended"):
            raise ValueError("status must be 'active' or 'suspended'")
        return value

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str | None) -> str | None:
        """Reject a too-short password when one is supplied."""
        return value if value is None else validate_password(value)

    @field_validator("display_name")
    @classmethod
    def _check_display_name(cls, value: str | None) -> str | None:
        """Reject a display name longer than the cap when one is supplied."""
        return validate_display_name(value)

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str | None) -> str | None:
        """Reject an email that does not look like an address when supplied."""
        return validate_email(value)


# ---------------------------------------------------------------------------
# Account response models (web-redesign §4.6)
# ---------------------------------------------------------------------------


class UserResponse(BaseModel):
    """A user as returned to the browser — never carries the password hash."""

    id: int
    username: str
    display_name: str | None
    email: str | None
    role: str
    status: str
    created_at: str
    last_login_at: str | None


class UserEnvelope(BaseModel):
    """The ``{"user": User}`` envelope for single-user responses."""

    user: UserResponse


class UserListResponse(BaseModel):
    """The ``{"users": [User, ...]}`` envelope for ``GET /api/users``."""

    users: list[UserResponse]


class SetupStatusResponse(BaseModel):
    """Response body for ``GET /api/setup/status``."""

    needed: bool


class PublicStatsResponse(BaseModel):
    """Response body for ``GET /api/stats/public`` — splash counts only."""

    document_count: int
    chunk_count: int


def to_user_response(user: User) -> UserResponse:
    """Convert an :class:`appdb.users.User` to its public wire shape.

    The single boundary mapper from the internal user dataclass to the HTTP
    response. It deliberately drops ``password_hash``, ``updated_at`` and
    ``password_changed_at`` — none of which belongs in an API response.

    Args:
        user: The internal user dataclass.

    Returns:
        A :class:`UserResponse` safe to serialise to JSON.
    """
    return UserResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )
