"""Pydantic request/response models for the search HTTP API (spec §7.1).

This package is the **HTTP boundary** of the search server: it is the only place
Pydantic models live in the search package (``CODE_GUIDELINES.md`` §5.6). Once an
HTTP request is validated here, the internal pipeline works entirely with frozen
dataclasses from :mod:`search.models` and :mod:`store.models`; once a result
leaves the pipeline, the ``to_*`` converters here map it back to the wire shape.

The boundary was a single 1187-line module that mixed eight unrelated feature
areas; it is now split one concept per file (§3.1, §3.3), with this thin
``__init__`` re-exporting every public name so ``from search.wire import X`` is
unchanged for every importer:

- :mod:`~search.wire.search` — ``POST /api/search`` models + converters.
- :mod:`~search.wire.library` — Library browse models + the browse-query converter.
- :mod:`~search.wire.facets` — facets, stats, taxonomy, recent-search models.
- :mod:`~search.wire.accounts` — login / setup / user models + converter.
- :mod:`~search.wire.api_keys` — API-key models + converter.
- :mod:`~search.wire.settings` — Settings API models + payload bounds.
- :mod:`~search.wire.index_dashboard` — Index dashboard models.

Allowed deps: pydantic, search.models, search.validation, search.api_keys
    (scope constants), store (SearchFilters), store.models, common.paperless_types.
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

from search.wire.accounts import (
    CreateUserRequest,
    LoginRequest,
    SetupRequest,
    SetupStatusResponse,
    UpdateUserRequest,
    UserEnvelope,
    UserListResponse,
    UserResponse,
    to_user_response,
)
from search.wire.api_keys import (
    ApiKeyEnvelope,
    ApiKeyListResponse,
    ApiKeyResponse,
    CreateApiKeyRequest,
    CreatedApiKeyResponse,
    UpdateApiKeyRequest,
    to_api_key_response,
)
from search.wire.facets import (
    FacetsResponse,
    PublicStatsResponse,
    RecentSearchEntry,
    RecentSearchesResponse,
    StatsResponse,
    TaxonomyCreateRequest,
    TaxonomyEntryResponse,
    TaxonomyItemResponse,
    paperless_item_to_response,
    to_facets_response,
    to_stats_response,
)
from search.wire.index_dashboard import (
    DaemonStatusResponse,
    FailedDocumentResponse,
    IndexActivityResponse,
    IndexFailedResponse,
    IndexStatusResponse,
    RebuildResponse,
    ReconcileCycleResponse,
)
from search.wire.library import (
    MAX_PAGE_NUMBER,
    MAX_PAGE_SIZE,
    BrowseSort,
    DocumentListResponse,
    DocumentPatchRequest,
    DocumentSummaryResponse,
    to_document_browse_query,
    to_document_list_response,
    to_document_summary_response,
)
from search.wire.search import (
    MAX_QUERY_LENGTH,
    MIN_QUERY_LENGTH,
    CostResponse,
    CostSummaryResponse,
    FilterRequest,
    PhaseRecordResponse,
    QueryPlanResponse,
    SearchRequest,
    SearchResponse,
    SearchStatsResponse,
    SearchTraceResponse,
    SourceDocumentResponse,
    TokenUsageResponse,
    normalise_query,
    to_search_filters,
    to_search_response,
)
from search.wire.settings import (
    MAX_PAPERLESS_URL_LENGTH,
    MAX_SETTINGS_KEYS,
    MAX_SETTINGS_VALUE_LENGTH,
    SettingItemResponse,
    SettingsResponse,
    TestConnectionRequest,
    TestConnectionResponse,
    UpdateSettingsRequest,
)

__all__ = [
    "MAX_PAGE_NUMBER",
    "MAX_PAGE_SIZE",
    "MAX_PAPERLESS_URL_LENGTH",
    "MAX_QUERY_LENGTH",
    "MIN_QUERY_LENGTH",
    "MAX_SETTINGS_KEYS",
    "MAX_SETTINGS_VALUE_LENGTH",
    "ApiKeyEnvelope",
    "ApiKeyListResponse",
    "ApiKeyResponse",
    "BrowseSort",
    "CostResponse",
    "CostSummaryResponse",
    "CreateApiKeyRequest",
    "CreateUserRequest",
    "CreatedApiKeyResponse",
    "DaemonStatusResponse",
    "DocumentListResponse",
    "DocumentPatchRequest",
    "DocumentSummaryResponse",
    "FacetsResponse",
    "FailedDocumentResponse",
    "FilterRequest",
    "IndexActivityResponse",
    "IndexFailedResponse",
    "IndexStatusResponse",
    "LoginRequest",
    "PhaseRecordResponse",
    "PublicStatsResponse",
    "QueryPlanResponse",
    "RebuildResponse",
    "ReconcileCycleResponse",
    "RecentSearchEntry",
    "RecentSearchesResponse",
    "SearchRequest",
    "SearchResponse",
    "SearchStatsResponse",
    "SearchTraceResponse",
    "SettingItemResponse",
    "SettingsResponse",
    "SetupRequest",
    "SetupStatusResponse",
    "SourceDocumentResponse",
    "StatsResponse",
    "TaxonomyCreateRequest",
    "TaxonomyEntryResponse",
    "TaxonomyItemResponse",
    "TestConnectionRequest",
    "TestConnectionResponse",
    "TokenUsageResponse",
    "UpdateApiKeyRequest",
    "UpdateSettingsRequest",
    "UpdateUserRequest",
    "UserEnvelope",
    "UserListResponse",
    "UserResponse",
    "paperless_item_to_response",
    "normalise_query",
    "to_api_key_response",
    "to_document_browse_query",
    "to_document_list_response",
    "to_document_summary_response",
    "to_facets_response",
    "to_search_filters",
    "to_search_response",
    "to_stats_response",
    "to_user_response",
]
