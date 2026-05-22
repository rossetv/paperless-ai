"""Tests for search.document_routes — the PDF proxy route.

Exercises GET /api/documents/{id}/pdf through a tiny FastAPI app and
TestClient with the AppState wired and a stubbed PaperlessClient, so the
routing, auth gate, streaming and error mapping are all real. Covers: a
signed-in user streams a document; the body and Content-Type are forwarded;
an unknown id maps to 404; a Paperless network error maps to 502; an
unauthenticated request is rejected 401.

Adaptation from the plan: AppState takes app_db_path (a path string), not a
live connection. The app is built with the tmp_path file; test fixtures seed
data via a separate connection to the same file, matching the established
pattern from test_deps.py.

Wave 3 note: the legacy SEARCH_API_KEY bearer is retired. Tests that
exercised the legacy bearer path have been removed.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from search.appstate import AppState, attach_app_state
from search.auth import SESSION_COOKIE_NAME
from search.document_routes import build_document_router
from search.sessions import begin_session
from search.setup import SetupState

_PDF_BYTES = b"%PDF-1.7\nstreamed document body\n%%EOF"


def _make_404_status_error() -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError carrying a 404 response."""
    request = httpx.Request("GET", "https://paperless.example/x")
    response = httpx.Response(404, request=request)
    return httpx.HTTPStatusError("not found", request=request, response=response)


def _build_app(app_db_path: str, paperless_client) -> FastAPI:
    """A FastAPI app mounting the document router with a stubbed client.

    The router is built with a *paperless_factory* that returns the supplied
    stub, so no real Paperless call is made.
    """
    app = FastAPI()
    attach_app_state(
        app.state,
        AppState(
            app_db_path=app_db_path,
            setup_state=SetupState(),
        ),
    )
    settings = MagicMock()
    app.include_router(
        build_document_router(settings, paperless_factory=lambda _s: paperless_client)
    )
    return app


@pytest.fixture()
def app_db_path(tmp_path) -> str:
    """Path to a migrated, empty app.db under tmp_path."""
    path = str(tmp_path / "app.db")
    c = connect(path)
    ensure_schema(c)
    c.close()
    return path


@pytest.fixture()
def conn(app_db_path):
    """An open connection to the migrated app.db for seeding test data."""
    c = connect(app_db_path)
    yield c
    c.close()


def _client(app_db_path: str, paperless_client) -> TestClient:
    return TestClient(
        _build_app(app_db_path, paperless_client),
        raise_server_exceptions=False,
        base_url="https://testserver",
    )


def _login(conn, *, role: str = "readonly") -> str:
    """Create a user of *role* and return a live session token."""
    user = create_user(conn, username="u", password_hash="h", role=role)
    return begin_session(conn, user_id=user.id, ttl_seconds=3600).token


def test_pdf_proxy_streams_the_document(app_db_path, conn) -> None:
    """A signed-in user gets the document body streamed back, 200."""

    def _chunks() -> Iterator[bytes]:
        yield _PDF_BYTES[:10]
        yield _PDF_BYTES[10:]

    paperless = MagicMock()
    paperless.download_stream.return_value = ("application/pdf", _chunks())
    client = _client(app_db_path, paperless)
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn))
    response = client.get("/api/documents/100/pdf")
    assert response.status_code == 200
    assert response.content == _PDF_BYTES


def test_pdf_proxy_pins_content_type_to_pdf(app_db_path, conn) -> None:
    """The response is always application/pdf, never Paperless's type.

    A malicious .html/.svg in the library reports text/html / image/svg+xml;
    forwarding that into the same-origin viewer iframe would execute script
    in the app origin. The proxy pins application/pdf with nosniff so the
    browser cannot be tricked into rendering active content.
    """
    paperless = MagicMock()
    # Paperless reports a script-executing content type for a hostile file.
    paperless.download_stream.return_value = (
        "text/html",
        iter([b"<script>steal()</script>"]),
    )
    client = _client(app_db_path, paperless)
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn))
    response = client.get("/api/documents/100/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == "inline"


def test_pdf_proxy_closes_the_client_on_success(app_db_path, conn) -> None:
    """The per-request Paperless client is closed once the body is drained.

    The client owns an httpx connection pool; without a deterministic close
    every PDF request leaks a socket until the server hits EMFILE.
    """
    paperless = MagicMock()
    paperless.download_stream.return_value = ("application/pdf", iter([_PDF_BYTES]))
    client = _client(app_db_path, paperless)
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn))
    response = client.get("/api/documents/100/pdf")
    assert response.status_code == 200
    paperless.close.assert_called_once()


def test_pdf_proxy_closes_the_client_on_an_upstream_error(app_db_path, conn) -> None:
    """The client is closed even when download_stream raises before a body."""
    paperless = MagicMock()
    paperless.download_stream.side_effect = httpx.ConnectError("refused")
    client = _client(app_db_path, paperless)
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn))
    response = client.get("/api/documents/100/pdf")
    assert response.status_code == 502
    paperless.close.assert_called_once()


def test_pdf_proxy_404_for_an_unknown_document(app_db_path, conn) -> None:
    """An unknown id — Paperless 404 — maps to a 404 from the proxy."""
    paperless = MagicMock()
    paperless.download_stream.side_effect = _make_404_status_error()
    client = _client(app_db_path, paperless)
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn))
    response = client.get("/api/documents/999/pdf")
    assert response.status_code == 404


def test_pdf_proxy_502_when_paperless_is_unreachable(app_db_path, conn) -> None:
    """A Paperless network error maps to a 502 Bad Gateway."""
    paperless = MagicMock()
    paperless.download_stream.side_effect = httpx.ConnectError("connection refused")
    client = _client(app_db_path, paperless)
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn))
    response = client.get("/api/documents/100/pdf")
    assert response.status_code == 502


def test_pdf_proxy_502_on_a_paperless_server_error(app_db_path, conn) -> None:
    """A Paperless 5xx maps to a 502 (it is not the client's fault)."""
    request = httpx.Request("GET", "https://paperless.example/x")
    response500 = httpx.Response(500, request=request)
    paperless = MagicMock()
    paperless.download_stream.side_effect = httpx.HTTPStatusError(
        "server error", request=request, response=response500
    )
    client = _client(app_db_path, paperless)
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn))
    response = client.get("/api/documents/100/pdf")
    assert response.status_code == 502


def test_pdf_proxy_401_when_unauthenticated(app_db_path) -> None:
    """An unauthenticated request is rejected before any Paperless call."""
    paperless = MagicMock()
    client = _client(app_db_path, paperless)
    response = client.get("/api/documents/100/pdf")
    assert response.status_code == 401
    paperless.download_stream.assert_not_called()


class TestRecentSearchesRoute:
    """GET /api/recent-searches returns the current user's search history."""

    @staticmethod
    def _build_app_no_paperless(app_db_path: str) -> FastAPI:
        """A FastAPI app with the document router; Paperless is never called."""
        app = FastAPI()
        attach_app_state(
            app.state,
            AppState(
                app_db_path=app_db_path,
                setup_state=SetupState(),
            ),
        )
        settings = MagicMock()
        app.include_router(
            build_document_router(settings, paperless_factory=lambda _s: MagicMock())
        )
        return app

    def _client_no_paperless(self, app_db_path: str) -> TestClient:
        return TestClient(
            self._build_app_no_paperless(app_db_path),
            raise_server_exceptions=False,
            base_url="https://testserver",
        )

    def test_recent_searches_returns_the_users_history(self, app_db_path, conn) -> None:
        """A signed-in user's recorded searches come back newest-first."""
        from appdb.recent_searches import record

        user = create_user(conn, username="alice", password_hash="h", role="readonly")
        record(conn, user_id=user.id, query="first query")
        record(conn, user_id=user.id, query="second query")
        token = begin_session(conn, user_id=user.id, ttl_seconds=3600).token

        client = self._client_no_paperless(app_db_path)
        client.cookies.set(SESSION_COOKIE_NAME, token)
        response = client.get("/api/recent-searches")
        assert response.status_code == 200
        queries = [s["query"] for s in response.json()["searches"]]
        assert queries == ["second query", "first query"]

    def test_recent_searches_empty_for_a_user_with_no_history(
        self, app_db_path, conn
    ) -> None:
        """A user who has never searched gets an empty list, 200."""
        user = create_user(conn, username="bob", password_hash="h", role="readonly")
        token = begin_session(conn, user_id=user.id, ttl_seconds=3600).token
        client = self._client_no_paperless(app_db_path)
        client.cookies.set(SESSION_COOKIE_NAME, token)
        response = client.get("/api/recent-searches")
        assert response.status_code == 200
        assert response.json() == {"searches": []}

    def test_recent_searches_isolates_users(self, app_db_path, conn) -> None:
        """One user never sees another user's recent searches."""
        from appdb.recent_searches import record

        alice = create_user(conn, username="alice", password_hash="h", role="readonly")
        bob = create_user(conn, username="bob", password_hash="h", role="readonly")
        record(conn, user_id=alice.id, query="alice secret")
        record(conn, user_id=bob.id, query="bob query")
        token = begin_session(conn, user_id=bob.id, ttl_seconds=3600).token

        client = self._client_no_paperless(app_db_path)
        client.cookies.set(SESSION_COOKIE_NAME, token)
        response = client.get("/api/recent-searches")
        queries = [s["query"] for s in response.json()["searches"]]
        assert queries == ["bob query"]
        assert "alice secret" not in queries

    def test_recent_searches_401_when_unauthenticated(self, app_db_path) -> None:
        """An unauthenticated request is rejected 401."""
        client = self._client_no_paperless(app_db_path)
        assert client.get("/api/recent-searches").status_code == 401
