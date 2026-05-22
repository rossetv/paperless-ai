"""Integration tests for Wave 2 per-user recent searches.

Exercises the record-then-list flow through the real search FastAPI app over
a real ``tmp_path`` ``app.db`` and seeded ``index.db``. ``POST /api/search``
runs against the stub ``SearchCore`` that ``build_account_client`` wires, so
no Paperless mock is needed.

Coverage:
- A successful signed-in search is recorded and listed by
  GET /api/recent-searches.
- Recent searches come back newest-first.
- One user never sees another user's recent searches.
- GET /api/recent-searches is rejected 401 when unauthenticated.

Note: passwords use "alice-password" / "bob-password" (≥8 chars) because
the LoginRequest validator enforces a minimum password length.

Wave 3 note: the legacy SEARCH_API_KEY bearer test is removed.
"""

from __future__ import annotations

from pathlib import Path

from store.reader import StoreReader
from tests.integration.accounts_helpers import (
    build_account_client,
    login,
    make_settings,
    open_app_db,
    seed_store,
    seed_user,
)


def test_a_search_is_recorded_and_then_listed(tmp_path: Path) -> None:
    """A signed-in user's successful search appears in recent-searches."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="readonly")
        client = build_account_client(settings, app_db, store_reader)
        assert (
            login(client, username="alice", password="alice-password").status_code
            == 200
        )

        search = client.post("/api/search", json={"query": "british gas bill"})
        assert search.status_code == 200

        recent = client.get("/api/recent-searches")
        assert recent.status_code == 200
        queries = [s["query"] for s in recent.json()["searches"]]
        assert queries == ["british gas bill"]
    finally:
        store_reader.close()
        app_db.close()


def test_recent_searches_are_newest_first(tmp_path: Path) -> None:
    """Running several searches lists them in reverse-chronological order."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="readonly")
        client = build_account_client(settings, app_db, store_reader)
        login(client, username="alice", password="alice-password")

        for query in ("first search", "second search", "third search"):
            assert client.post("/api/search", json={"query": query}).status_code == 200

        recent = client.get("/api/recent-searches")
        queries = [s["query"] for s in recent.json()["searches"]]
        assert queries == [
            "third search",
            "second search",
            "first search",
        ]
    finally:
        store_reader.close()
        app_db.close()


def test_recent_searches_isolate_users(tmp_path: Path) -> None:
    """A second user does not see the first user's recent searches."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="readonly")
        seed_user(app_db, username="bob", password="bob-password", role="readonly")
        client = build_account_client(settings, app_db, store_reader)

        # Alice searches.
        login(client, username="alice", password="alice-password")
        client.post("/api/search", json={"query": "alice private query"})
        # Log Alice out so Bob's cookie replaces hers cleanly.
        client.post("/api/auth/logout")

        # Bob searches and lists.
        login(client, username="bob", password="bob-password")
        client.post("/api/search", json={"query": "bob query"})
        recent = client.get("/api/recent-searches")
        queries = [s["query"] for s in recent.json()["searches"]]
        assert queries == ["bob query"]
        assert "alice private query" not in queries
    finally:
        store_reader.close()
        app_db.close()


def test_recent_searches_requires_authentication(tmp_path: Path) -> None:
    """GET /api/recent-searches is rejected 401 when unauthenticated."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="readonly")
        client = build_account_client(settings, app_db, store_reader)
        # No login.
        response = client.get("/api/recent-searches")
        assert response.status_code == 401
    finally:
        store_reader.close()
        app_db.close()
