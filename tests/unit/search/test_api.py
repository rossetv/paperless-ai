"""Unit tests for search.api — the FastAPI search server.

Covers the security-critical contracts (spec §7.1, §7.3, §7.4):

- An unauthenticated POST /api/search → 401; a DB-backed API key Bearer token
  authorises /api/search.
- POST /api/search / GET /api/facets / GET /api/stats return correctly-mapped
  wire responses; POST /api/reconcile writes the sentinel and returns 202.
- The SPA catch-all never serves a path outside the frontend directory, and
  the index DB is never web-reachable.
- main() delegates per-process startup to ``common.bootstrap``.
- POST /api/search returns 422 when query exceeds max length (MINOR 2).

The username/password login handshake and the session-cookie path are
exercised by the account integration suite (spec §4.8). The healthz
three-state endpoint and the SEARCH_MAX_CONCURRENT semaphore are covered in
:mod:`test_api_healthz` (split for the 500-line ceiling, §3.1).

``build_test_client`` (see conftest.py) wraps the real ``create_app`` with a
mock core, a mock store reader, and a fresh in-memory ``app.db``.

Wave 3 note: the legacy SEARCH_API_KEY bearer is retired. Tests that relied on
it now use a minted DB-backed API key or a session cookie.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.helpers.factories import (
    make_facet_set,
    make_index_stats,
    make_search_result,
    make_search_settings,
    make_source_document,
    make_taxonomy_entry,
)
from tests.helpers.search import mint_api_key
from tests.unit.search.conftest import build_test_client

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(
    *, db_path: str = "/nonexistent/index.db", **overrides: object
) -> MagicMock:
    """Build a Settings-like mock for API tests, with a chosen index DB path."""
    return make_search_settings(INDEX_DB_PATH=db_path, **overrides)


def _seed_api_key(settings: MagicMock) -> str:
    """Seed a user and an API key in the app.db at *settings.APP_DB_PATH*.

    Returns the raw key string for use as a Bearer token. The app.db is
    already migrated by ``create_app`` inside ``build_test_client``, so this
    function opens a second connection to the same file to insert the seed
    rows — the established per-request connection pattern.
    """
    from appdb.connection import connect
    from appdb.passwords import hash_password
    from appdb.users import create as create_user

    conn = connect(settings.APP_DB_PATH)
    try:
        user = create_user(
            conn,
            username="api-user",
            password_hash=hash_password("pw"),
            role="member",
        )
        return mint_api_key(conn, owner_user_id=user.id, scopes="api")
    finally:
        conn.close()


def _bearer_headers(raw_key: str) -> dict[str, str]:
    """Return an Authorization header carrying *raw_key* as a Bearer token."""
    return {"Authorization": f"Bearer {raw_key}"}


def _seeded_facets() -> object:
    """A FacetSet with one entry of each taxonomy kind, for the facets test."""
    return make_facet_set(
        correspondents=(
            make_taxonomy_entry(kind="correspondent", entry_id=1, name="ACME"),
        ),
        document_types=(
            make_taxonomy_entry(kind="document_type", entry_id=2, name="Invoice"),
        ),
        tags=(make_taxonomy_entry(kind="tag", entry_id=3, name="important"),),
        earliest="2020-01-01T00:00:00Z",
        latest="2024-12-31T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Authentication — unauthenticated access is rejected
# ---------------------------------------------------------------------------


def test_unauthenticated_search_returns_401() -> None:
    """An unauthenticated POST /api/search must return 401."""
    client = build_test_client(_settings())
    response = client.post("/api/search", json={"query": "test"})
    assert response.status_code == 401


def test_unauthenticated_facets_returns_401() -> None:
    client = build_test_client(_settings())
    assert client.get("/api/facets").status_code == 401


def test_unauthenticated_stats_returns_401() -> None:
    client = build_test_client(_settings())
    assert client.get("/api/stats").status_code == 401


def test_unauthenticated_reconcile_returns_401() -> None:
    client = build_test_client(_settings())
    assert client.post("/api/reconcile").status_code == 401


# ---------------------------------------------------------------------------
# Authentication — bearer token authorises requests
# ---------------------------------------------------------------------------


def test_bearer_token_authorises_search() -> None:
    """A valid DB-backed API key Bearer token must authorise /api/search."""
    settings = _settings()
    client = build_test_client(settings)
    raw_key = _seed_api_key(settings)
    response = client.post(
        "/api/search",
        json={"query": "boiler warranty"},
        headers=_bearer_headers(raw_key),
    )
    assert response.status_code == 200


def test_wrong_bearer_token_returns_401() -> None:
    client = build_test_client(_settings())
    response = client.post(
        "/api/search", json={"query": "test"}, headers=_bearer_headers("wrong")
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Reconcile — writes the sentinel file and returns 202
# ---------------------------------------------------------------------------


def test_reconcile_writes_sentinel_and_returns_202(tmp_path: Path) -> None:
    """POST /api/reconcile must touch the sentinel file and return 202."""
    settings = _settings(db_path=str(tmp_path / "index.db"))
    client = build_test_client(settings)
    raw_key = _seed_api_key(settings)

    response = client.post("/api/reconcile", headers=_bearer_headers(raw_key))
    assert response.status_code == 202
    assert (tmp_path / "reconcile.request").exists(), "Sentinel was not created."


def test_reconcile_does_not_write_index_db(tmp_path: Path) -> None:
    """POST /api/reconcile must ONLY write the sentinel; never the index DB."""
    settings = _settings(db_path=str(tmp_path / "index.db"))
    client = build_test_client(settings)
    raw_key = _seed_api_key(settings)
    client.post("/api/reconcile", headers=_bearer_headers(raw_key))

    assert not (tmp_path / "index.db").exists(), (
        "Reconcile must never write the index DB."
    )


# ---------------------------------------------------------------------------
# Search — correct wire mapping
# ---------------------------------------------------------------------------


def test_search_returns_correctly_mapped_response() -> None:
    """POST /api/search must return a correctly-mapped SearchResponse."""
    core = MagicMock()
    core.answer.return_value = make_search_result(
        answer="The boiler warranty is 5 years.",
        sources=(
            make_source_document(
                document_id=42,
                title="Test Doc",
                correspondent="ACME",
                document_type="Invoice",
                score=0.9,
            ),
        ),
    )
    settings = _settings()
    client = build_test_client(settings, core=core)
    raw_key = _seed_api_key(settings)

    response = client.post(
        "/api/search", json={"query": "boiler warranty"}, headers=_bearer_headers(raw_key)
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
    assert "plan" in body
    assert "stats" in body
    assert body["stats"]["llm_calls"] == 2
    assert body["stats"]["refined"] is False


def test_search_with_filters_passes_filters_to_core() -> None:
    """Filters in the search request must be forwarded to SearchCore."""
    core = MagicMock()
    core.answer.return_value = make_search_result()
    settings = _settings()
    client = build_test_client(settings, core=core)
    raw_key = _seed_api_key(settings)

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
        headers=_bearer_headers(raw_key),
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
    store_reader = MagicMock()
    store_reader.list_facets.return_value = _seeded_facets()
    store_reader.quick_check.return_value = True
    settings = _settings()
    client = build_test_client(settings, store_reader=store_reader)
    raw_key = _seed_api_key(settings)

    response = client.get("/api/facets", headers=_bearer_headers(raw_key))
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
    store_reader = MagicMock()
    store_reader.get_stats.return_value = make_index_stats(
        document_count=100,
        chunk_count=450,
        last_reconcile_at="2024-06-01T12:00:00Z",
        embedding_model="text-embedding-3-small",
    )
    store_reader.quick_check.return_value = True
    settings = _settings()
    client = build_test_client(settings, store_reader=store_reader)
    raw_key = _seed_api_key(settings)

    response = client.get("/api/stats", headers=_bearer_headers(raw_key))
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
    """The index DB must never be served via the SPA static mount.

    The SPA catch-all serves a real file only when it resolves inside
    ``web/dist``; ``/index.db`` does not, so the deep-link catch-all hands
    back the SPA shell (``index.html``) instead. The index DB content is
    never reachable over HTTP — that is the invariant under test.
    """
    db_path = tmp_path / "index.db"
    db_path.write_text("sensitive data")
    # No auth needed — the SPA mount does not enforce authentication;
    # the invariant is about path containment, not auth.
    settings = _settings(db_path=str(db_path))
    client = build_test_client(settings)

    response = client.get("/index.db")
    assert "sensitive data" not in response.text


def test_path_traversal_on_static_mount_is_rejected(tmp_path: Path) -> None:
    """Path traversal on the SPA mount must not escape the frontend directory.

    A percent-encoded ``..`` survives client-side URL normalisation and
    reaches the catch-all as a literal traversal segment. ``register_spa``
    resolves the candidate path and refuses to serve anything outside
    ``web/dist`` — so a crafted path cannot read an out-of-tree file. The
    catch-all falls back to the SPA shell; the probe file's content must
    never appear in the response.
    """
    probe = tmp_path / "traversal_probe.txt"
    probe.write_text("out-of-tree-secret")
    client = build_test_client(_settings())

    response = client.get("/%2e%2e/%2e%2e/%2e%2e/etc/passwd")
    assert "out-of-tree-secret" not in response.text
    assert "root:" not in response.text


# ---------------------------------------------------------------------------
# Entry point — main() delegates to the shared bootstrap
# ---------------------------------------------------------------------------


def test_main_runs_the_shared_process_bootstrap() -> None:
    """main() delegates startup to common.bootstrap.bootstrap_process().

    The per-process startup — Settings, logging, the library singletons, the
    signal handlers, and the LLM concurrency limiter — is defined once in
    common.bootstrap and shared with the daemons.  This test fails if main()
    stops calling it: re-inlining that sequence is what dropped
    llm_limiter.init() and 500ed every /api/search query in production.
    """
    from search.api import main

    valid_settings = MagicMock()

    with (
        patch(
            "common.bootstrap.bootstrap_process", return_value=valid_settings
        ) as mock_bootstrap,
        patch("search.api.create_app"),
        patch("search.api.uvicorn.run"),
    ):
        main()

    mock_bootstrap.assert_called_once()


# ---------------------------------------------------------------------------
# MINOR 2 regression — over-length query returns 422
# ---------------------------------------------------------------------------


def test_search_returns_422_when_query_exceeds_max_length() -> None:
    """POST /api/search returns 422 when query exceeds the 4000-character limit.

    Pydantic enforces ``max_length=MAX_QUERY_LENGTH`` on SearchRequest.query;
    this test confirms the constraint is present and active. The 422 fires
    before the auth dependency runs in FastAPI (body-schema rejection), so no
    key is required.
    """
    settings = _settings()
    client = build_test_client(settings)
    raw_key = _seed_api_key(settings)

    too_long_query = "x" * 4001
    response = client.post(
        "/api/search", json={"query": too_long_query}, headers=_bearer_headers(raw_key)
    )
    assert response.status_code == 422
