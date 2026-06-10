"""Integration tests: Settings test-connection and RBAC (web-redesign §5).

Covers POST /api/settings/test-connection against a mocked Paperless
count_documents call (success with a document count, bad token, unreachable
host), the new per-service probes (openai, ollama), backward-compatibility of
omitting ``service``, and the RBAC gates on all three Settings endpoints — a
member is 403, an unauthenticated caller is 401.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx

from tests.integration.accounts_helpers import (
    build_account_client,
    login,
    make_settings,
    open_app_db,
    seed_admin,
    seed_store,
    seed_user,
)


def _admin_client(tmp_path):
    """Build a logged-in admin client; return (client, app_db, store_reader)."""
    from store.reader import StoreReader

    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    seed_admin(app_db, username="admin", password="admin-password")
    store_reader = StoreReader(settings)
    client = build_account_client(settings, app_db, store_reader)
    assert login(client, username="admin", password="admin-password").status_code == 200
    return client, app_db, store_reader


def test_test_connection_reports_success_with_a_count(tmp_path) -> None:
    """A successful round-trip yields ok=True and the document count."""
    client, app_db, store_reader = _admin_client(tmp_path)
    try:
        with patch(
            "search.settings_routes.PaperlessClient.count_documents",
            return_value=14238,
        ):
            response = client.post(
                "/api/settings/test-connection",
                json={"paperless_url": "http://x", "paperless_token": "tok"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["document_count"] == 14238
    finally:
        store_reader.close()
        app_db.close()


def test_test_connection_reports_a_bad_token(tmp_path) -> None:
    """A 401 from Paperless yields a clean ok=False, not a 500."""
    client, app_db, store_reader = _admin_client(tmp_path)
    try:
        fake_response = httpx.Response(401, request=httpx.Request("GET", "http://x"))
        error = httpx.HTTPStatusError(
            "401", request=fake_response.request, response=fake_response
        )
        with patch(
            "search.settings_routes.PaperlessClient.count_documents",
            side_effect=error,
        ):
            response = client.post(
                "/api/settings/test-connection",
                json={"paperless_url": "http://x", "paperless_token": "wrong"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["document_count"] == 0
        assert "401" in body["detail"]
    finally:
        store_reader.close()
        app_db.close()


def test_test_connection_reports_an_unreachable_host(tmp_path) -> None:
    """A connection error yields ok=False with a reachability message."""
    client, app_db, store_reader = _admin_client(tmp_path)
    try:
        with patch(
            "search.settings_routes.PaperlessClient.count_documents",
            side_effect=httpx.ConnectError("refused"),
        ):
            response = client.post(
                "/api/settings/test-connection",
                json={"paperless_url": "http://x", "paperless_token": "tok"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert "reach" in body["detail"].lower()
    finally:
        store_reader.close()
        app_db.close()


def test_test_connection_paperless_is_default_when_service_omitted(tmp_path) -> None:
    """Omitting ``service`` still probes Paperless (back-compat)."""
    client, app_db, store_reader = _admin_client(tmp_path)
    try:
        with patch(
            "search.settings_routes.PaperlessClient.count_documents",
            return_value=99,
        ):
            response = client.post(
                "/api/settings/test-connection",
                # No ``service`` key — must default to paperless.
                json={"paperless_url": "http://x", "paperless_token": "tok"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["document_count"] == 99
    finally:
        store_reader.close()
        app_db.close()


def test_test_connection_openai_success(tmp_path) -> None:
    """service=openai with a valid key returns ok=True, document_count=0."""
    client, app_db, store_reader = _admin_client(tmp_path)
    try:
        with patch(
            "search.settings_routes._probe_openai",
            return_value=None,  # success — no exception
        ):
            response = client.post(
                "/api/settings/test-connection",
                json={
                    "paperless_url": "",
                    "paperless_token": "",
                    "service": "openai",
                    "openai_api_key": "sk-test",
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["document_count"] == 0
        assert "connected" in body["detail"].lower()
    finally:
        store_reader.close()
        app_db.close()


def test_test_connection_openai_bad_key(tmp_path) -> None:
    """service=openai with a bad key returns ok=False, never 500."""
    import openai as openai_sdk

    client, app_db, store_reader = _admin_client(tmp_path)
    try:
        with patch(
            "search.settings_routes._probe_openai",
            side_effect=openai_sdk.AuthenticationError(
                "invalid api key",
                response=httpx.Response(
                    401, request=httpx.Request("GET", "https://api.openai.com")
                ),
                body={"error": {"message": "invalid api key", "type": "invalid_api_key"}},
            ),
        ):
            response = client.post(
                "/api/settings/test-connection",
                json={
                    "paperless_url": "",
                    "paperless_token": "",
                    "service": "openai",
                    "openai_api_key": "bad-key",
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["document_count"] == 0
        assert body["detail"]
    finally:
        store_reader.close()
        app_db.close()


def test_test_connection_ollama_success(tmp_path) -> None:
    """service=ollama with a reachable base URL returns ok=True."""
    client, app_db, store_reader = _admin_client(tmp_path)
    try:
        with patch(
            "search.settings_routes._probe_ollama",
            return_value=None,  # success — no exception
        ):
            response = client.post(
                "/api/settings/test-connection",
                json={
                    "paperless_url": "",
                    "paperless_token": "",
                    "service": "ollama",
                    "ollama_base_url": "http://localhost:11434",
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["document_count"] == 0
        assert "connected" in body["detail"].lower()
    finally:
        store_reader.close()
        app_db.close()


def test_test_connection_ollama_unreachable(tmp_path) -> None:
    """service=ollama with an unreachable host returns ok=False, never 500."""
    client, app_db, store_reader = _admin_client(tmp_path)
    try:
        with patch(
            "search.settings_routes._probe_ollama",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            response = client.post(
                "/api/settings/test-connection",
                json={
                    "paperless_url": "",
                    "paperless_token": "",
                    "service": "ollama",
                    "ollama_base_url": "http://localhost:11434",
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["document_count"] == 0
        assert body["detail"]
    finally:
        store_reader.close()
        app_db.close()


def test_get_settings_403_for_a_member(tmp_path) -> None:
    """A logged-in member cannot view Settings — admin-only."""
    from store.reader import StoreReader

    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    seed_user(app_db, username="bob", password="bob-password", role="member")
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        assert login(client, username="bob", password="bob-password").status_code == 200
        assert client.get("/api/settings").status_code == 403
    finally:
        store_reader.close()
        app_db.close()


def test_put_settings_403_for_a_member(tmp_path) -> None:
    """A member cannot change Settings."""
    from store.reader import StoreReader

    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    seed_user(app_db, username="bob", password="bob-password", role="member")
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        assert login(client, username="bob", password="bob-password").status_code == 200
        response = client.put("/api/settings", json={"changes": {"OCR_DPI": "200"}})
        assert response.status_code == 403
    finally:
        store_reader.close()
        app_db.close()


def test_settings_endpoints_401_when_unauthenticated(tmp_path) -> None:
    """All three Settings endpoints reject an unauthenticated caller."""
    from store.reader import StoreReader

    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    seed_admin(app_db, username="admin", password="admin-password")
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        # No login — the cookie jar is empty.
        assert client.get("/api/settings").status_code == 401
        assert client.put("/api/settings", json={"changes": {}}).status_code == 401
        assert (
            client.post(
                "/api/settings/test-connection",
                json={"paperless_url": "http://x", "paperless_token": "t"},
            ).status_code
            == 401
        )
    finally:
        store_reader.close()
        app_db.close()
