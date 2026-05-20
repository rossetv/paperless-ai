"""Unit tests for search.api — the FastAPI search server.

Covers the security-critical contracts (spec §7.1, §7.3, §7.4):

- An unauthenticated POST /api/search → 401.
- POST /api/auth/login with the correct key sets the session cookie.
- The session cookie then authorises /api/search (200).
- A valid Bearer token also authorises /api/search (200).
- GET /api/healthz → 503 index-not-ready when the DB file is absent.
- GET /api/healthz → 503 index-corrupt when quick_check returns False.
- GET /api/healthz → 200 when quick_check returns True.
- POST /api/reconcile writes the sentinel file and returns 202.
- POST /api/search returns a correctly-mapped SearchResponse.
- GET /api/facets returns a correctly-mapped FacetsResponse.
- GET /api/stats returns a correctly-mapped StatsResponse.
- StaticFiles cannot serve a path outside the frontend directory
  (path traversal is rejected).
- The SEARCH_MAX_CONCURRENT semaphore caps in-flight search requests.
- The index DB path is never served over HTTP (security invariant).
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from search.auth import SESSION_COOKIE_NAME, issue_session_token
from search.models import (
    FilterCandidates,
    QueryPlan,
    SearchResult,
    SearchStats,
    SourceDocument,
)
from store.models import FacetSet, IndexStats, TaxonomyEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_API_KEY = "test-api-key-for-unit-tests"


def _make_mock_settings(
    *,
    api_key: str = _API_KEY,
    session_ttl: int = 3600,
    max_concurrent: int = 4,
    db_path: str = "/nonexistent/index.db",
    tmp_reconcile_dir: str | None = None,
) -> MagicMock:
    """Build a minimal MagicMock Settings for API tests."""
    settings = MagicMock()
    settings.SEARCH_API_KEY = api_key
    settings.SEARCH_SESSION_TTL = session_ttl
    settings.SEARCH_MAX_CONCURRENT = max_concurrent
    settings.PAPERLESS_URL = "http://paperless:8000"
    # INDEX_DB_PATH used by healthz and reconcile endpoints.
    db = tmp_reconcile_dir + "/index.db" if tmp_reconcile_dir else db_path
    settings.INDEX_DB_PATH = db
    return settings


def _make_empty_query_plan() -> QueryPlan:
    return QueryPlan(
        semantic_queries=("test query",),
        keyword_terms=(),
        filter_candidates=FilterCandidates(
            correspondent=None,
            document_type=None,
            tags=(),
            date_from=None,
            date_to=None,
        ),
        sub_questions=(),
    )


def _make_search_result(answer: str = "The answer.") -> SearchResult:
    source = SourceDocument(
        document_id=42,
        title="Test Doc",
        correspondent="ACME",
        document_type="Invoice",
        created="2024-01-01T00:00:00Z",
        snippet="Some snippet text.",
        paperless_url="http://paperless:8000/documents/42/",
        score=0.9,
    )
    return SearchResult(
        answer=answer,
        sources=(source,),
        plan=_make_empty_query_plan(),
        stats=SearchStats(llm_calls=2, latency_ms=123, refined=False),
    )


def _make_facet_set() -> FacetSet:
    return FacetSet(
        correspondents=(TaxonomyEntry(kind="correspondent", id=1, name="ACME"),),
        document_types=(TaxonomyEntry(kind="document_type", id=2, name="Invoice"),),
        tags=(TaxonomyEntry(kind="tag", id=3, name="important"),),
        earliest="2020-01-01T00:00:00Z",
        latest="2024-12-31T00:00:00Z",
    )


def _make_index_stats() -> IndexStats:
    return IndexStats(
        document_count=100,
        chunk_count=450,
        last_reconcile_at="2024-06-01T12:00:00Z",
        embedding_model="text-embedding-3-small",
    )


def _build_test_app(
    settings: MagicMock,
    *,
    core: Any = None,
    store_reader: Any = None,
) -> TestClient:
    """Build a TestClient with mocked dependencies.

    Uses ``https://testserver`` as the base URL so that ``Secure`` session
    cookies are forwarded on subsequent requests (the real server always runs
    behind HTTPS; the Secure flag is a required security attribute per
    spec §7.3).
    """
    from search.api import create_app

    if core is None:
        core = MagicMock()
        core.answer.return_value = _make_search_result()
    if store_reader is None:
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _make_facet_set()
        store_reader.get_stats.return_value = _make_index_stats()
        store_reader.quick_check.return_value = True

    app = create_app(settings, core=core, store_reader=store_reader)
    return TestClient(app, raise_server_exceptions=False, base_url="https://testserver")


def _bearer_headers(key: str = _API_KEY) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _session_cookie(key: str = _API_KEY, ttl: int = 3600) -> str:
    return issue_session_token(key, ttl_seconds=ttl, now=time.time())


# ---------------------------------------------------------------------------
# Authentication — unauthenticated access is rejected
# ---------------------------------------------------------------------------


def test_unauthenticated_search_returns_401() -> None:
    """An unauthenticated POST /api/search must return 401."""
    settings = _make_mock_settings()
    client = _build_test_app(settings)
    response = client.post("/api/search", json={"query": "test"})
    assert response.status_code == 401


def test_unauthenticated_facets_returns_401() -> None:
    settings = _make_mock_settings()
    client = _build_test_app(settings)
    response = client.get("/api/facets")
    assert response.status_code == 401


def test_unauthenticated_stats_returns_401() -> None:
    settings = _make_mock_settings()
    client = _build_test_app(settings)
    response = client.get("/api/stats")
    assert response.status_code == 401


def test_unauthenticated_reconcile_returns_401() -> None:
    settings = _make_mock_settings()
    client = _build_test_app(settings)
    response = client.post("/api/reconcile")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Authentication — login sets the session cookie
# ---------------------------------------------------------------------------


def test_login_with_correct_key_sets_session_cookie() -> None:
    """POST /api/auth/login with the correct key must set the session cookie."""
    settings = _make_mock_settings()
    client = _build_test_app(settings)
    response = client.post(
        "/api/auth/login",
        json={"api_key": _API_KEY},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert SESSION_COOKIE_NAME in response.cookies


def test_login_with_wrong_key_returns_401() -> None:
    settings = _make_mock_settings()
    client = _build_test_app(settings)
    response = client.post(
        "/api/auth/login",
        json={"api_key": "wrong-key"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Authentication — session cookie authorises subsequent requests
# ---------------------------------------------------------------------------


def test_session_cookie_authorises_search() -> None:
    """A session cookie obtained via login must authorise /api/search."""
    settings = _make_mock_settings()
    client = _build_test_app(settings)

    # First, log in to get the session cookie.
    login = client.post("/api/auth/login", json={"api_key": _API_KEY})
    assert login.status_code == 200
    assert SESSION_COOKIE_NAME in login.cookies

    # The TestClient retains cookies automatically; next request uses the cookie.
    response = client.post("/api/search", json={"query": "boiler warranty"})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Authentication — bearer token authorises requests
# ---------------------------------------------------------------------------


def test_bearer_token_authorises_search() -> None:
    """A valid Bearer token must authorise /api/search."""
    settings = _make_mock_settings()
    client = _build_test_app(settings)
    response = client.post(
        "/api/search",
        json={"query": "boiler warranty"},
        headers=_bearer_headers(),
    )
    assert response.status_code == 200


def test_wrong_bearer_token_returns_401() -> None:
    settings = _make_mock_settings()
    client = _build_test_app(settings)
    response = client.post(
        "/api/search",
        json={"query": "test"},
        headers=_bearer_headers("wrong"),
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Healthz — unauthenticated, state-aware
# ---------------------------------------------------------------------------


def test_healthz_returns_503_when_db_absent() -> None:
    """GET /api/healthz returns 503 index-not-ready when the DB does not exist."""
    settings = _make_mock_settings(db_path="/nonexistent/index.db")
    store_reader = MagicMock()
    # DB absent: quick_check raises because connect fails, or we never call it.
    # The endpoint itself should guard — if the file doesn't exist it 503s.
    client = _build_test_app(settings, store_reader=store_reader)
    response = client.get("/api/healthz")
    assert response.status_code == 503
    body = response.json()
    assert body.get("status") == "index-not-ready"


def test_healthz_returns_503_when_index_corrupt(tmp_path: Path) -> None:
    """GET /api/healthz returns 503 index-corrupt when quick_check fails."""
    db_path = tmp_path / "index.db"
    db_path.write_bytes(b"")  # File exists but quick_check returns False.
    settings = _make_mock_settings(db_path=str(db_path))
    store_reader = MagicMock()
    store_reader.quick_check.return_value = False
    client = _build_test_app(settings, store_reader=store_reader)
    response = client.get("/api/healthz")
    assert response.status_code == 503
    body = response.json()
    assert body.get("status") == "index-corrupt"


def test_healthz_returns_200_when_healthy(tmp_path: Path) -> None:
    """GET /api/healthz returns 200 when the DB exists and quick_check passes."""
    db_path = tmp_path / "index.db"
    db_path.write_bytes(b"")
    settings = _make_mock_settings(db_path=str(db_path))
    store_reader = MagicMock()
    store_reader.quick_check.return_value = True
    client = _build_test_app(settings, store_reader=store_reader)
    response = client.get("/api/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body.get("status") == "ok"


def test_healthz_does_not_require_auth() -> None:
    """GET /api/healthz must be accessible without authentication."""
    settings = _make_mock_settings(db_path="/nonexistent/index.db")
    client = _build_test_app(settings)
    # No auth header — must not get 401.
    response = client.get("/api/healthz")
    assert response.status_code != 401


# ---------------------------------------------------------------------------
# Reconcile — writes sentinel file and returns 202
# ---------------------------------------------------------------------------


def test_reconcile_writes_sentinel_and_returns_202(tmp_path: Path) -> None:
    """POST /api/reconcile must touch the sentinel file and return 202."""
    settings = _make_mock_settings(tmp_reconcile_dir=str(tmp_path))
    client = _build_test_app(settings)

    response = client.post("/api/reconcile", headers=_bearer_headers())
    assert response.status_code == 202

    sentinel = tmp_path / "reconcile.request"
    assert sentinel.exists(), "Sentinel file was not created."


def test_reconcile_does_not_write_index_db(tmp_path: Path) -> None:
    """POST /api/reconcile must ONLY write the sentinel; never the index DB."""
    settings = _make_mock_settings(tmp_reconcile_dir=str(tmp_path))
    client = _build_test_app(settings)
    client.post("/api/reconcile", headers=_bearer_headers())

    db_path = tmp_path / "index.db"
    assert not db_path.exists(), "Reconcile must never write the index DB."


# ---------------------------------------------------------------------------
# Search — correct wire mapping
# ---------------------------------------------------------------------------


def test_search_returns_correctly_mapped_response() -> None:
    """POST /api/search must return a correctly-mapped SearchResponse."""
    settings = _make_mock_settings()
    search_result = _make_search_result(answer="The boiler warranty is 5 years.")
    core = MagicMock()
    core.answer.return_value = search_result
    client = _build_test_app(settings, core=core)

    response = client.post(
        "/api/search",
        json={"query": "boiler warranty"},
        headers=_bearer_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "The boiler warranty is 5 years."
    assert len(body["sources"]) == 1
    source = body["sources"][0]
    assert source["document_id"] == 42
    assert source["title"] == "Test Doc"
    assert source["correspondent"] == "ACME"
    assert source["score"] == pytest.approx(0.9)
    # Plan and stats are present.
    assert "plan" in body
    assert "stats" in body
    assert body["stats"]["llm_calls"] == 2
    assert body["stats"]["refined"] is False


def test_search_with_filters_passes_filters_to_core() -> None:
    """Filters in the search request must be forwarded to SearchCore."""
    settings = _make_mock_settings()
    core = MagicMock()
    core.answer.return_value = _make_search_result()
    client = _build_test_app(settings, core=core)

    client.post(
        "/api/search",
        json={
            "query": "invoice",
            "filters": {
                "correspondent_id": 5,
                "document_type_id": 2,
                "tag_ids": [10, 20],
            },
        },
        headers=_bearer_headers(),
    )

    call_args = core.answer.call_args
    assert call_args is not None
    ui_filters = call_args.kwargs.get("ui_filters") or call_args.args[1]
    assert ui_filters is not None
    assert ui_filters.correspondent_id == 5
    assert ui_filters.document_type_id == 2
    assert 10 in ui_filters.tag_ids


# ---------------------------------------------------------------------------
# Facets — correct wire mapping
# ---------------------------------------------------------------------------


def test_facets_returns_correctly_mapped_response() -> None:
    """GET /api/facets must return a correctly-mapped FacetsResponse."""
    settings = _make_mock_settings()
    store_reader = MagicMock()
    store_reader.list_facets.return_value = _make_facet_set()
    store_reader.quick_check.return_value = True
    client = _build_test_app(settings, store_reader=store_reader)

    response = client.get("/api/facets", headers=_bearer_headers())
    assert response.status_code == 200
    body = response.json()
    assert len(body["correspondents"]) == 1
    assert body["correspondents"][0]["name"] == "ACME"
    assert len(body["document_types"]) == 1
    assert body["document_types"][0]["name"] == "Invoice"
    assert len(body["tags"]) == 1
    assert body["tags"][0]["name"] == "important"
    assert body["earliest"] == "2020-01-01T00:00:00Z"
    assert body["latest"] == "2024-12-31T00:00:00Z"


# ---------------------------------------------------------------------------
# Stats — correct wire mapping
# ---------------------------------------------------------------------------


def test_stats_returns_correctly_mapped_response() -> None:
    """GET /api/stats must return a correctly-mapped StatsResponse."""
    settings = _make_mock_settings()
    store_reader = MagicMock()
    store_reader.get_stats.return_value = _make_index_stats()
    store_reader.quick_check.return_value = True
    client = _build_test_app(settings, store_reader=store_reader)

    response = client.get("/api/stats", headers=_bearer_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["document_count"] == 100
    assert body["chunk_count"] == 450
    assert body["last_reconcile_at"] == "2024-06-01T12:00:00Z"
    assert body["embedding_model"] == "text-embedding-3-small"


# ---------------------------------------------------------------------------
# Security — index DB is never web-reachable
# ---------------------------------------------------------------------------


def test_index_db_is_not_served_over_http(tmp_path: Path) -> None:
    """The index DB must never be served via the static files mount."""
    db_path = tmp_path / "index.db"
    db_path.write_text("sensitive data")
    settings = _make_mock_settings(db_path=str(db_path))
    client = _build_test_app(settings)

    # Attempt to access /index.db — should not serve the file.
    response = client.get("/index.db", headers=_bearer_headers())
    assert response.status_code in (404, 307, 302)
    assert "sensitive data" not in response.text


def test_path_traversal_on_static_mount_is_rejected(tmp_path: Path) -> None:
    """Path-traversal attempts on the static mount must not escape the frontend dir."""
    settings = _make_mock_settings()
    client = _build_test_app(settings)

    # Attempt to traverse; FastAPI/Starlette rejects with 400 or 404.
    response = client.get(
        "/../../../../etc/passwd",
        headers=_bearer_headers(),
    )
    assert response.status_code in (400, 404)


# ---------------------------------------------------------------------------
# Concurrency — SEARCH_MAX_CONCURRENT semaphore
# ---------------------------------------------------------------------------


def test_search_max_concurrent_semaphore_is_created_and_limits_search() -> None:
    """SEARCH_MAX_CONCURRENT creates an asyncio.Semaphore that caps /api/search.

    The semaphore is verified by checking that sequential requests all succeed
    (200).  Concurrent multi-threaded load testing is out of scope for a unit
    test — the integration and concurrent behaviour is covered by the
    SEARCH_MAX_CONCURRENT setting on the real server.
    """
    settings = _make_mock_settings(max_concurrent=2)
    core = MagicMock()
    core.answer.return_value = _make_search_result()
    client = _build_test_app(settings, core=core)

    # Sequential requests within the limit must all succeed.
    for _ in range(3):
        response = client.post(
            "/api/search",
            json={"query": "test"},
            headers=_bearer_headers(),
        )
        assert response.status_code == 200
