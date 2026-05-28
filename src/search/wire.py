# rationale: CODE_GUIDELINES §5.6 requires all Pydantic models to live here —
# a single, intentional exception to the 500-line ceiling. Splitting this file
# would scatter the wire boundary across modules, defeating the point of the
# rule. Every new feature appends its models to this file.

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
    :class:`SearchResponse`, :class:`FacetsResponse`, :class:`StatsResponse`,
    :class:`RecentSearchesResponse`, :class:`DocumentListResponse`

Mapping functions (wire model ⇄ internal dataclass):
    :func:`to_search_filters` (request → store input shape),
    :func:`to_search_response`, :func:`to_facets_response`,
    :func:`to_stats_response`, :func:`to_document_list_response`

Constants:
    :data:`MAX_QUERY_LENGTH` — the documented maximum query length, applied at
    every search boundary (HTTP and MCP).

Allowed deps: pydantic, search.models, store (SearchFilters), store.models,
    search.api_keys (scope constants only).
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from search.api_keys import _VALID_SCOPES as _VALID_API_KEY_SCOPES_SET
from search.validation import (
    validate_display_name,
    validate_email,
    validate_password,
    validate_role,
    validate_username,
)
from store import SearchFilters
from store.models import DocumentBrowseQuery, DocumentSummary

if TYPE_CHECKING:
    from appdb.api_keys import ApiKey
    from appdb.users import User
    from common.paperless_types import PaperlessItem
    from search.models import SearchResult
    from store.models import DocumentPage, FacetSet, IndexStats

# The documented maximum length of a search query / question (§10.4).  Long
# enough for any reasonable natural-language question; short enough to bound
# the token cost of an injected mega-prompt.  Applied identically at the HTTP
# boundary (``SearchRequest.query``) and the MCP boundary (``mcp_server``) so
# both surfaces enforce one limit (CODE_GUIDELINES §3.5).
MAX_QUERY_LENGTH = 4000

# The maximum Library page size accepted by ``GET /api/documents``.  Bounds
# the row count one request can pull from the index and the JSON payload
# size; the Library UI's pager never asks for more.  Applied at the HTTP
# boundary via ``Query(le=MAX_PAGE_SIZE)`` and re-asserted in the parser.
MAX_PAGE_SIZE = 100

# The maximum ``page`` number accepted by ``GET /api/documents``.  Without
# this bound a caller can send ``page=9_999_999_999`` producing a 9.9e11-row
# ``OFFSET`` that holds the StoreReader lock for a measurable duration on every
# query.  10 000 × 100 (MAX_PAGE_SIZE) = 1 000 000 rows — far more than any
# realistic Paperless instance.
MAX_PAGE_NUMBER = 10_000


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


class DocumentSummaryResponse(BaseModel):
    """One document in the Library list (web-redesign §5).

    The full per-document payload the Library card renders: identity, the
    resolved taxonomy display names, the document date, the tag names, the
    page count, and the deep-link URL into Paperless. The ``paperless_url``
    field makes :class:`DocumentSummaryResponse` shape-compatible with
    :class:`SourceDocumentResponse` from the perspective of the frontend, so
    both Library cards and search-result cards can render the same open-in-
    Paperless link without conditional logic.
    """

    id: int
    title: str | None
    correspondent: str | None
    document_type: str | None
    created: str | None
    tags: list[str]
    page_count: int | None
    paperless_url: str


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


class DocumentListResponse(BaseModel):
    """Response body for GET /api/documents — one page of the Library.

    Attributes:
        documents: The document summaries for this page, in sort order.
        total: The total number of documents matching the request's filters,
            ignoring pagination — drives the UI pager.
        page: The 1-based page number this response represents.
        page_size: The page size that produced this response.
    """

    documents: list[DocumentSummaryResponse]
    total: int
    page: int
    page_size: int


class RecentSearchEntry(BaseModel):
    """One entry in GET /api/recent-searches — a single past search."""

    query: str
    created_at: str


class RecentSearchesResponse(BaseModel):
    """Response body for GET /api/recent-searches — the user's history."""

    searches: list[RecentSearchEntry]


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


def to_document_summary_response(
    summary: DocumentSummary, *, paperless_url: str
) -> DocumentSummaryResponse:
    """Convert one store :class:`~store.models.DocumentSummary` to the wire model.

    The explicit, tested boundary conversion (``CODE_GUIDELINES.md`` §5.6).
    *paperless_url* is the fully-qualified deep-link into Paperless for this
    document; callers construct it from ``settings.PAPERLESS_URL`` so this
    function remains free of I/O and configuration knowledge.

    Args:
        summary: The store dataclass to convert.
        paperless_url: The fully-qualified Paperless deep-link URL for the
            document, e.g. ``https://paperless.example/documents/42/``.

    Returns:
        A :class:`DocumentSummaryResponse` ready to serialise as JSON.
    """
    return DocumentSummaryResponse(
        id=summary.id,
        title=summary.title,
        correspondent=summary.correspondent,
        document_type=summary.document_type,
        created=summary.created,
        tags=list(summary.tags),
        page_count=summary.page_count,
        paperless_url=paperless_url,
    )


def to_document_list_response(
    page: DocumentPage,
    *,
    page_number: int,
    page_size: int,
    paperless_base_url: str,
) -> DocumentListResponse:
    """Convert a store :class:`~store.models.DocumentPage` to the wire model.

    The explicit, tested boundary conversion (``CODE_GUIDELINES.md`` §5.6):
    no Pydantic model leaks into the store layer, no store dataclass leaks
    into the HTTP response.  *page_number* and *page_size* are supplied by the
    handler (which derived them from the validated query parameters) rather
    than recomputed here, so this function is a pure field copy.

    *paperless_base_url* is used to construct the ``paperless_url`` deep-link
    for each document; the caller strips any trailing slash before passing it
    so the per-document URLs are consistently formatted.

    Args:
        page: The browse page from
            :meth:`~store.reader.StoreReader.list_documents`.
        page_number: The 1-based page number this response represents.
        page_size: The page size that produced *page*.
        paperless_base_url: The Paperless base URL with no trailing slash,
            e.g. ``https://paperless.example``. Prepended to each document's
            ``/documents/{id}/`` path.

    Returns:
        A :class:`DocumentListResponse` ready to serialise as JSON.
    """
    return DocumentListResponse(
        documents=[
            to_document_summary_response(
                s, paperless_url=f"{paperless_base_url}/documents/{s.id}/"
            )
            for s in page.documents
        ],
        total=page.total,
        page=page_number,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Taxonomy wire models (web-redesign, Task 8)
# ---------------------------------------------------------------------------


class TaxonomyItemResponse(BaseModel):
    """A correspondent, document type, or tag, as exposed to the SPA."""

    id: int
    name: str
    document_count: int = 0


class TaxonomyCreateRequest(BaseModel):
    """Body for ``POST /api/correspondents`` | ``/api/document-types`` | ``/api/tags``."""

    name: str


def _paperless_item_to_response(item: "PaperlessItem") -> TaxonomyItemResponse:
    """Convert one Paperless taxonomy item to the wire shape.

    The Paperless API exposes the usage count under one of three field names
    depending on version — ``document_count`` / ``documents_count`` /
    ``documents`` (the last being a list of document ids).  We accept all three
    and coerce strings to int defensively.  When only a ``documents`` list is
    present we report 0: the list may be truncated on listing endpoints and
    inferring the count from it would be misleading.

    Args:
        item: A :class:`~common.paperless_types.PaperlessItem` dict as
            returned by :meth:`~common.paperless.PaperlessClient.list_correspondents`
            and its siblings.

    Returns:
        A :class:`TaxonomyItemResponse` ready to serialise as JSON.
    """
    raw: object = item.get("document_count")
    if raw is None:
        raw = item.get("documents_count")
    if raw is None:
        # ``documents`` is a list of referencing document ids; we intentionally
        # treat this as an unknown count rather than inferring len(list).
        raw = 0
    if isinstance(raw, str):
        raw = int(raw) if raw.isdigit() else 0
    return TaxonomyItemResponse(id=item["id"], name=item["name"], document_count=int(raw))


# ---------------------------------------------------------------------------
# Account request models (web-redesign §4.6)
# ---------------------------------------------------------------------------


class DocumentPatchRequest(BaseModel):
    """Body for ``PATCH /api/documents/{id}``.

    Every field is optional — only fields present in the request are passed
    through to Paperless. An empty body is a valid no-op.
    """

    title: str | None = None
    correspondent_id: int | None = None
    document_type_id: int | None = None
    document_date: str | None = None
    tags: list[int] | None = None
    notes: str | None = None
    archive_serial_number: int | None = None


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


# ---------------------------------------------------------------------------
# API-key wire models (web-redesign §5; Wave 3)
# ---------------------------------------------------------------------------


def _validate_scope_list(value: list[str]) -> list[str]:
    """Reject any scope outside the documented three.

    Delegates to :data:`search.api_keys._VALID_SCOPES` — the single source of
    truth — so a future scope addition only needs to be made in one place.
    Shared by :class:`CreateApiKeyRequest` and :class:`UpdateApiKeyRequest`.
    """
    unknown = set(value) - _VALID_API_KEY_SCOPES_SET
    if unknown:
        raise ValueError(f"unknown scope(s): {sorted(unknown)}")
    return value


class CreateApiKeyRequest(BaseModel):
    """The body of ``POST /api/api-keys`` — request a new key.

    Attributes:
        name: A human label, 1-100 characters.
        scopes: A non-empty list drawn from ``api``/``mcp``/``admin``.
        expires_at: An optional ISO-8601 UTC expiry; omitted = never expires.
    """

    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1)
    expires_at: str | None = None

    @field_validator("scopes")
    @classmethod
    def _scopes_are_valid(cls, value: list[str]) -> list[str]:
        """Reject any scope outside the documented three."""
        return _validate_scope_list(value)


class UpdateApiKeyRequest(BaseModel):
    """The body of ``PATCH /api/api-keys/{id}`` — edit a key.

    Every field is optional: the caller sends only what it wants changed, and
    an absent field is left untouched (an empty body is a valid no-op edit).
    The immutable fields — the key itself, its owner, its prefix — can never
    be edited; only ``name``, ``scopes`` and ``expires_at`` are mutable.

    A *supplied* field still has to be valid: ``name`` cannot be empty and
    ``scopes`` cannot be empty or contain an unknown scope. To leave a field
    unchanged, omit it rather than sending an empty value.

    ``expires_at`` is special: ``None`` is itself a meaningful value — it
    means "this key never expires" — so the route handler distinguishes
    "clear the expiry" (``expires_at`` present and ``null``) from "leave the
    expiry unchanged" (``expires_at`` absent) via Pydantic's
    ``model_fields_set``, not the parsed value. See ``_update_api_key`` in
    Task W3B15.

    Attributes:
        name: A new human label, 1-100 characters, or ``None``/absent.
        scopes: A new non-empty scope list, or ``None``/absent.
        expires_at: A new ISO-8601 UTC expiry; ``null`` clears the expiry;
            absent leaves it unchanged.
    """

    name: str | None = Field(default=None, min_length=1, max_length=100)
    scopes: list[str] | None = Field(default=None, min_length=1)
    expires_at: str | None = None

    @field_validator("scopes")
    @classmethod
    def _scopes_are_valid(cls, value: list[str] | None) -> list[str] | None:
        """Reject any scope outside the documented three, when supplied."""
        if value is None:
            return None
        return _validate_scope_list(value)


class ApiKeyResponse(BaseModel):
    """One API key in an HTTP response — never carries the secret.

    Mirrors :class:`appdb.api_keys.ApiKey` minus ``key_hash``: the hash is a
    server-side secret and must never cross the wire. The dataclass column
    ``owner_user_id`` is exposed here as ``owner_id`` (the wire layer must
    not leak the DB column name), and ``owner_name`` — the owning user's
    display name — is added; it is resolved from the ``users`` table by the
    caller, since the key row itself only stores the owner's id.
    """

    id: int
    name: str
    key_prefix: str
    owner_id: int
    owner_name: str
    scopes: list[str]
    created_at: str
    expires_at: str | None
    last_used_at: str | None
    revoked_at: str | None
    request_count: int


class ApiKeyListResponse(BaseModel):
    """The body of ``GET /api/api-keys`` — a list of keys."""

    keys: list[ApiKeyResponse]


class ApiKeyEnvelope(BaseModel):
    """The body of ``PATCH /api/api-keys/{id}`` — one key, no secret.

    The updated key after an edit. Unlike :class:`CreatedApiKeyResponse` it
    carries **no** ``secret`` — editing a key never re-reveals it.
    """

    api_key: ApiKeyResponse


class CreatedApiKeyResponse(BaseModel):
    """The body of ``POST /api/api-keys`` — the one-time key reveal.

    ``secret`` is the full raw ``sk-pls-...`` key, returned **exactly once**
    at creation. No other endpoint ever returns it; the client must store it
    immediately. ``api_key`` is the persisted metadata (no secret).
    """

    api_key: ApiKeyResponse
    secret: str


def to_api_key_response(api_key: ApiKey, owner_name: str) -> ApiKeyResponse:
    """Map an :class:`appdb.api_keys.ApiKey` to its wire shape.

    Copies every public field and **omits** ``key_hash`` — the hash is a
    secret and never appears in a response. The stored comma-separated
    ``scopes`` string is split into a list for the JSON shape. The dataclass
    ``owner_user_id`` becomes the wire ``owner_id``; the owner's display name
    is not on the key row, so the caller resolves it from the ``users`` table
    and supplies it as *owner_name*.

    Args:
        api_key: The persisted key row.
        owner_name: The owning user's display name (the caller looks the
            owner up in the ``users`` table; falls back to the username when
            no display name is set).

    Returns:
        The :class:`ApiKeyResponse` for the HTTP layer.
    """
    scope_list = [s for s in api_key.scopes.split(",") if s]
    return ApiKeyResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        owner_id=api_key.owner_user_id,
        owner_name=owner_name,
        scopes=scope_list,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
        revoked_at=api_key.revoked_at,
        request_count=api_key.request_count,
    )


# ---------------------------------------------------------------------------
# Settings API models (web-redesign spec §5, Wave 4)
# ---------------------------------------------------------------------------


class SettingItemResponse(BaseModel):
    """One configuration key as returned by ``GET``/``PUT /api/settings``.

    A secret key's *value* is masked by the route handler before this model
    is built — this model never does the masking itself.

    Attributes:
        key: The canonical config key (an env-var name).
        value: The effective string value, or ``None`` when the key is on its
            coded default. For a secret key this is the masked placeholder.
            Always a string on the wire — the frontend parses it per the
            field's type (number / bool / CSV list).
        source: ``database`` / ``environment`` / ``default``.
        is_secret: Whether the key holds a secret (the UI offers a reveal).
        requires_reindex: Whether changing this key requires re-indexing every
            document — true for the chunking / embedding-model keys
            (:data:`common.config.REINDEX_KEYS`). The UI shows a re-index
            warning for exactly these keys. There is no restart concept:
            Wave 4 hot-loads every config change.
        default_value: The coded default as a string, or ``None`` for secrets
            and optional keys that have no meaningful coded default. The
            frontend uses this to display the default when ``source`` is
            ``"default"`` and ``value`` is ``None``.
    """

    key: str
    value: str | None
    source: str
    is_secret: bool
    requires_reindex: bool
    default_value: str | None = None


class SettingsResponse(BaseModel):
    """Body of ``GET /api/settings`` and ``PUT /api/settings``.

    The full list of config keys and their state. ``PUT`` returns this same
    shape — the re-read configuration — so the Settings screen refreshes
    itself from the one response with no second fetch.
    """

    settings: list[SettingItemResponse]


# Bounds on the ``PUT /api/settings`` body. These are deliberately generous
# for legitimate use — an admin save changes a handful of keys, never a 100k
# blob — and narrow enough that an over-large or buggy payload cannot fill
# the SQLite write or pin out other writers for the busy-timeout window.
MAX_SETTINGS_KEYS = 100
MAX_SETTINGS_VALUE_LENGTH = 8 * 1024

# Bound on the ``POST /api/settings/test-connection`` URL. 2K is long enough
# for any legitimate Paperless URL (the standard caps URIs at 2048) and short
# enough that a paste-bombed value is rejected at the boundary.
MAX_PAPERLESS_URL_LENGTH = 2048


class UpdateSettingsRequest(BaseModel):
    """Body of ``PUT /api/settings`` — the configuration changes to apply.

    Every value is a string: the ``config`` table stores raw strings and
    ``common.config`` parses them. ``changes`` may be empty (a no-op save).

    The mapping itself is bounded by :data:`MAX_SETTINGS_KEYS`; each value is
    bounded by :data:`MAX_SETTINGS_VALUE_LENGTH`. An over-large payload is
    rejected at the boundary rather than reaching the SQLite write — a
    defence against an accidentally-pasted 10MB blob or a compromised admin
    session DoS-ing the write lock for the busy-timeout window.
    """

    changes: dict[str, str] = Field(max_length=MAX_SETTINGS_KEYS)

    @field_validator("changes")
    @classmethod
    def _bound_value_lengths(cls, value: dict[str, str]) -> dict[str, str]:
        """Reject any single value longer than :data:`MAX_SETTINGS_VALUE_LENGTH`.

        Pydantic ``Field(max_length=...)`` on ``dict[str, str]`` bounds the
        *number of keys*, not the length of each value — that has to be done
        in a validator. We reject as a 422 rather than truncate; silently
        truncating a configuration value would be far worse than refusing it.
        """
        for key, val in value.items():
            if len(val) > MAX_SETTINGS_VALUE_LENGTH:
                raise ValueError(
                    f"value for {key!r} exceeds the {MAX_SETTINGS_VALUE_LENGTH}-"
                    "character limit"
                )
        return value


class TestConnectionRequest(BaseModel):
    """Body of ``POST /api/settings/test-connection``.

    The Settings screen sends the *live form values* so an admin can verify a
    Paperless connection before saving it.

    Attributes:
        paperless_url: The Paperless base URL to probe. An empty string means
            "use the stored URL". Must be ``http://`` or ``https://`` when
            non-empty; user-info in the URL (``http://user:pw@host``) is
            rejected so a probe cannot be tricked into smuggling credentials
            through the URL.
        paperless_token: The Paperless API token to probe with. An empty
            string means "use the stored token" — the Settings screen sends
            an empty token when the user has not replaced the masked one.
    """

    paperless_url: str = Field(max_length=MAX_PAPERLESS_URL_LENGTH)
    paperless_token: str = Field(max_length=MAX_SETTINGS_VALUE_LENGTH)

    @field_validator("paperless_url")
    @classmethod
    def _check_paperless_url(cls, value: str) -> str:
        """Require ``http(s)://`` and reject userinfo on a non-empty URL.

        An empty string is the documented "use the stored URL" sentinel and
        passes through untouched. Non-empty values must be an absolute
        ``http``/``https`` URL — file://, ftp://, gopher:// and similar
        schemes are not Paperless, and a userinfo segment would otherwise let
        a compromised admin smuggle a stored credential into a probe target.
        """
        if not value:
            return value
        # rationale: a deliberately narrow scheme check rather than a full
        # URL parser; the test-connection probe is admin-only and we only
        # care that the value targets HTTP(S) and carries no userinfo.
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("paperless_url must start with http:// or https://")
        # urllib.parse imported here so wire.py keeps a flat top-of-module —
        # the validator is only hit on a non-empty URL.
        from urllib.parse import urlparse  # noqa: PLC0415

        parsed = urlparse(value)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("paperless_url must not contain credentials")
        if not parsed.hostname:
            raise ValueError("paperless_url must include a host")
        return value


class TestConnectionResponse(BaseModel):
    """Body of ``POST /api/settings/test-connection`` — the round-trip result.

    Attributes:
        ok: Whether the Paperless API responded successfully to an
            authenticated request.
        document_count: The document count Paperless reported on success; 0
            when the probe failed.
        detail: A human-readable outcome — a success note or the failure
            reason (an HTTP status, a connection error).
    """

    ok: bool
    document_count: int
    detail: str


# Maps the public ``sort`` query-parameter values to the store's sort keys.
# The public API exposes ``added`` (a friendly name); the store column is
# ``indexed_at``.  ``created`` and ``title`` are identical on both sides.
_BROWSE_SORT_ALIASES: dict[str, str] = {
    "created": "created",
    "title": "title",
    "added": "indexed_at",
}


def to_document_browse_query(
    *,
    page: int,
    page_size: int,
    sort: str,
    descending: bool,
    text: str | None,
    date_from: str | None,
    date_to: str | None,
    correspondent_id: int | None,
    document_type_id: int | None,
    tag_ids: list[int],
) -> DocumentBrowseQuery:
    """Map validated HTTP query parameters to a store browse query.

    The single converter from the ``GET /api/documents`` query string to
    :class:`~store.models.DocumentBrowseQuery`.  *page* and *page_size* are
    already range-checked by FastAPI's ``Query`` constraints on the handler;
    this function trusts those bounds and derives the zero-based ``offset``.

    The public ``sort`` value is translated through
    :data:`_BROWSE_SORT_ALIASES` — the API name ``added`` maps to the store
    column ``indexed_at``; ``created`` and ``title`` pass through.

    Args:
        page: The 1-based page number (FastAPI enforces ``>= 1``).
        page_size: Rows per page (FastAPI enforces ``1..MAX_PAGE_SIZE``).
        sort: One of ``created``, ``title``, ``added``.
        descending: True for a descending sort, False for ascending.
        text: Optional in-library text query, or None.
        date_from: Optional inclusive ISO-8601 lower date bound, or None.
        date_to: Optional inclusive ISO-8601 upper date bound, or None.
        correspondent_id: Optional correspondent filter id, or None.
        document_type_id: Optional document-type filter id, or None.
        tag_ids: Tag-id filter list; empty means no tag restriction.

    Returns:
        The :class:`~store.models.DocumentBrowseQuery` for the store reader.

    Raises:
        ValueError: *sort* is not a recognised sort name.
    """
    store_sort = _BROWSE_SORT_ALIASES.get(sort)
    if store_sort is None:
        allowed = ", ".join(sorted(_BROWSE_SORT_ALIASES))
        raise ValueError(f"unknown sort {sort!r}; expected one of {allowed}")
    return DocumentBrowseQuery(
        text=text,
        date_from=date_from,
        date_to=date_to,
        correspondent_id=correspondent_id,
        document_type_id=document_type_id,
        tag_ids=tuple(tag_ids),
        sort=store_sort,
        descending=descending,
        offset=(page - 1) * page_size,
        limit=page_size,
    )


# ---------------------------------------------------------------------------
# Index dashboard API models (web-redesign spec §5, Wave 6)
# ---------------------------------------------------------------------------


class DaemonStatusResponse(BaseModel):
    """One daemon's tile in the Index dashboard.

    Attributes:
        name: The daemon name — ocr / classifier / indexer / search.
        state: The derived state — running / idle / stopped.
        detail: A short human string describing what the daemon last did.
        processed_count: The daemon's monotonic throughput counter.
        last_heartbeat: ISO-8601 UTC timestamp of the daemon's last
            heartbeat — a long-past value for a daemon that never ran.
    """

    name: str
    state: str
    detail: str
    processed_count: int
    last_heartbeat: str


class IndexStatusResponse(BaseModel):
    """Body of ``GET /api/index/status`` — daemon health and per-daemon tiles.

    Attributes:
        health: The overall verdict — ok / degraded / down.
        daemons: One :class:`DaemonStatusResponse` per known daemon (always
            four).
    """

    health: str
    daemons: list[DaemonStatusResponse]


class ReconcileCycleResponse(BaseModel):
    """One reconcile/sweep cycle in the Index dashboard's activity list.

    Attributes:
        id: The cycle's id — also its chronological order.
        kind: ``sync`` or ``sweep``.
        started_at: ISO-8601 UTC timestamp the cycle began.
        finished_at: ISO-8601 UTC timestamp the cycle ended.
        ok: Whether the cycle completed without aborting or erroring.
        summary: The cycle's count map (the SyncReport/SweepReport fields).
        detail: A short human one-liner describing the outcome.
    """

    id: int
    kind: str
    started_at: str
    finished_at: str
    ok: bool
    summary: dict[str, int]
    detail: str


class IndexActivityResponse(BaseModel):
    """Body of ``GET /api/index/activity`` — recent reconcile cycles."""

    cycles: list[ReconcileCycleResponse]


class FailedDocumentResponse(BaseModel):
    """One document the indexer has failed to index.

    Attributes:
        document_id: The Paperless document id.
        title: The document's title, or ``None`` when it has no indexed row.
        failure_count: How many consecutive cycles it has failed.
    """

    document_id: int
    title: str | None
    failure_count: int


class IndexFailedResponse(BaseModel):
    """Body of ``GET /api/index/failed`` — the failed-document list."""

    documents: list[FailedDocumentResponse]


class RebuildResponse(BaseModel):
    """Body of ``POST /api/index/rebuild`` — the rebuild-trigger outcome.

    Attributes:
        accepted: Whether the rebuild request was accepted and triggered.
        detail: A human-readable note describing what happens next.
    """

    accepted: bool
    detail: str
