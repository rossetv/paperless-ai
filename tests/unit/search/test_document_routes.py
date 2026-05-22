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

_LEGACY_KEY = "doc-routes-legacy-key"
_PDF_BYTES = b"%PDF-1.7\nstreamed document body\n%%EOF"


def _make_404_status_error() -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError carrying a 404 response."""
    request = httpx.Request("GET", "https://paperless.example/x")
    response = httpx.Response(404, request=request)
    return httpx.HTTPStatusError(
        "not found", request=request, response=response
    )


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
            legacy_api_key=_LEGACY_KEY,
        ),
    )
    settings = MagicMock()
    app.include_router(
        build_document_router(
            settings, paperless_factory=lambda _s: paperless_client
        )
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


def test_pdf_proxy_forwards_the_content_type(app_db_path, conn) -> None:
    """The Content-Type from Paperless is forwarded to the browser."""
    paperless = MagicMock()
    paperless.download_stream.return_value = (
        "application/pdf",
        iter([_PDF_BYTES]),
    )
    client = _client(app_db_path, paperless)
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn))
    response = client.get("/api/documents/100/pdf")
    assert response.headers["content-type"].startswith("application/pdf")


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
    paperless.download_stream.side_effect = httpx.ConnectError(
        "connection refused"
    )
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


def test_pdf_proxy_allows_a_legacy_bearer(app_db_path) -> None:
    """The legacy SEARCH_API_KEY bearer (a synthetic admin) is allowed."""
    paperless = MagicMock()
    paperless.download_stream.return_value = (
        "application/pdf",
        iter([_PDF_BYTES]),
    )
    client = _client(app_db_path, paperless)
    response = client.get(
        "/api/documents/100/pdf",
        headers={"Authorization": f"Bearer {_LEGACY_KEY}"},
    )
    assert response.status_code == 200
