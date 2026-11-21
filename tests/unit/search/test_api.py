"""Unit tests for search.api, the FastAPI search server.

Healthz and the SEARCH_MAX_CONCURRENT cap are covered in :mod:`test_api_healthz`.
"""

from __future__ import annotations

import threading
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


def _settings(
    *, db_path: str = "/nonexistent/index.db", **overrides: object
) -> MagicMock:
    """Build a Settings-like mock for API tests, with a chosen index DB path."""
    return make_search_settings(INDEX_DB_PATH=db_path, **overrides)


def _seed_api_key(settings: MagicMock) -> str:
    """Seed a user and an API key in *settings.APP_DB_PATH*; return the raw key."""
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
        "/api/search",
        json={"query": "boiler warranty"},
        headers=_bearer_headers(raw_key),
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


def test_index_db_is_not_served_over_http(tmp_path: Path) -> None:
    """The index DB must never be served via the SPA static mount.

    ``/index.db`` does not resolve inside ``web/dist``, so the catch-all returns the
    SPA shell instead.
    """
    db_path = tmp_path / "index.db"
    db_path.write_text("sensitive data")
    # No auth: the SPA mount is unauthenticated; the invariant is path containment.
    settings = _settings(db_path=str(db_path))
    client = build_test_client(settings)

    response = client.get("/index.db")
    assert "sensitive data" not in response.text


def test_path_traversal_on_static_mount_is_rejected(tmp_path: Path) -> None:
    """Path traversal on the SPA mount must not escape the frontend directory.

    A percent-encoded ``..`` survives client-side URL normalisation and reaches the
    catch-all as a literal traversal segment.
    """
    probe = tmp_path / "traversal_probe.txt"
    probe.write_text("out-of-tree-secret")
    client = build_test_client(_settings())

    response = client.get("/%2e%2e/%2e%2e/%2e%2e/etc/passwd")
    assert "out-of-tree-secret" not in response.text
    assert "root:" not in response.text


def test_main_runs_the_shared_process_bootstrap() -> None:
    """main() delegates startup to common.bootstrap.bootstrap_process().

    Inlining that sequence risks dropping a step such as llm_limiter.init(), which
    makes every /api/search query fail with a 500.
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


def test_search_returns_422_when_query_exceeds_max_length() -> None:
    """POST /api/search returns 422 when query exceeds the 4000-character limit.

    The body schema rejects it before the auth dependency runs, so no key is needed.
    """
    settings = _settings()
    client = build_test_client(settings)
    raw_key = _seed_api_key(settings)

    too_long_query = "x" * 4001
    response = client.post(
        "/api/search", json={"query": too_long_query}, headers=_bearer_headers(raw_key)
    )
    assert response.status_code == 422


def test_search_heartbeat_connects_to_settings_app_db_path(tmp_path: Path) -> None:
    """``_start_search_heartbeat`` opens ``settings.APP_DB_PATH``, not the env default.

    Reading ``os.environ["APP_DB_PATH"]`` would write the heartbeat to the wrong
    file wherever app.db lives elsewhere, and the Index dashboard would report the
    server as stopped.
    """
    from search.api import _start_search_heartbeat

    app_db_path = str(tmp_path / "elsewhere" / "app.db")
    (tmp_path / "elsewhere").mkdir()
    settings = _settings(APP_DB_PATH=app_db_path)

    opened_paths: list[str] = []

    def _record_connect(path: str) -> MagicMock:
        opened_paths.append(path)
        return MagicMock()

    # Point the env default at a wrong path so reading the environment is caught.
    with (
        patch("search.api.connect_app_db", side_effect=_record_connect),
        patch("search.api.ensure_app_db_schema"),
        # No-op the ticker so the daemon thread returns immediately after the
        # connect under test, rather than looping until stopped.
        patch("search.api.run_heartbeat_ticker"),
        patch.dict("os.environ", {"APP_DB_PATH": "/data/wrong.db"}),
    ):
        stop_heartbeat = _start_search_heartbeat(settings)
        # The returned stop callable joins only this call's thread, never the
        # same-named threads other tests started.
        stop_heartbeat()

    assert opened_paths == [app_db_path]
    assert "/data/wrong.db" not in opened_paths


def test_search_heartbeat_stop_terminates_the_thread(tmp_path: Path) -> None:
    """The stop callable returned by ``_start_search_heartbeat`` ends the thread.

    Drives the real ticker so a leaked "search-heartbeat" thread per app instance
    would fail the test.
    """
    from search.api import _start_search_heartbeat

    settings = _settings(APP_DB_PATH=str(tmp_path / "app.db"))
    threads_before = set(threading.enumerate())
    with (
        patch("search.api.connect_app_db", return_value=MagicMock()),
        patch("search.api.ensure_app_db_schema"),
    ):
        stop_heartbeat = _start_search_heartbeat(settings)
        stop_heartbeat()

    leaked = {
        thread
        for thread in set(threading.enumerate()) - threads_before
        if thread.name == "search-heartbeat" and thread.is_alive()
    }
    assert leaked == set()
