"""Integration tests for the GET /api/documents/{id}/pdf proxy.

``create_app`` builds the real ``PaperlessClient`` factory, so the client class
itself is patched to a stub.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from store.reader import StoreReader
from tests.integration.accounts_helpers import (
    build_account_client,
    make_settings,
    open_app_db,
    seed_store,
    seed_user,
)

_PDF_BYTES = b"%PDF-1.7\nintegration pdf body\n%%EOF"


class _StubPaperlessClient:
    """A stand-in PaperlessClient whose ``download_stream`` outcome is set per test."""

    # Set by each test: either ("application/pdf", <bytes>) to stream, or an
    # exception instance to raise from download_stream.
    next_outcome: object = ("application/pdf", _PDF_BYTES)

    def __init__(self, _settings: object) -> None:
        """Ignore the settings the factory passes."""

    def download_stream(self, _doc_id: int) -> tuple[str, Iterator[bytes]]:
        """Return the scripted stream, or raise the scripted exception."""
        outcome = type(self).next_outcome
        if isinstance(outcome, BaseException):
            raise outcome
        content_type, body = outcome  # type: ignore[misc]
        return content_type, iter([body])

    def close(self) -> None:
        """No-op — the stub holds no resources."""


@pytest.fixture()
def patched_paperless(monkeypatch: pytest.MonkeyPatch) -> type[_StubPaperlessClient]:
    """Patch search.document_routes.PaperlessClient to the stub, reset to success."""
    _StubPaperlessClient.next_outcome = ("application/pdf", _PDF_BYTES)
    monkeypatch.setattr("search.document_routes.PaperlessClient", _StubPaperlessClient)
    return _StubPaperlessClient


def _make_404_error() -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError carrying a 404 response."""
    request = httpx.Request("GET", "https://paperless.example/x")
    response = httpx.Response(404, request=request)
    return httpx.HTTPStatusError("not found", request=request, response=response)


def test_pdf_proxy_streams_for_a_signed_in_user(
    tmp_path: Path, patched_paperless: type[_StubPaperlessClient]
) -> None:
    """A signed-in user gets the document body streamed back, 200."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="readonly")
        client = build_account_client(settings, app_db, store_reader)
        login = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "alice-password", "remember": False},
        )
        assert login.status_code == 200

        response = client.get("/api/documents/100/pdf")
        assert response.status_code == 200
        assert response.content == _PDF_BYTES
    finally:
        store_reader.close()
        app_db.close()


def test_pdf_proxy_404_for_an_unknown_document(
    tmp_path: Path, patched_paperless: type[_StubPaperlessClient]
) -> None:
    """An id Paperless does not know maps to a 404 from the proxy."""
    patched_paperless.next_outcome = _make_404_error()
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="readonly")
        client = build_account_client(settings, app_db, store_reader)
        client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "alice-password", "remember": False},
        )
        response = client.get("/api/documents/424242/pdf")
        assert response.status_code == 404
    finally:
        store_reader.close()
        app_db.close()


def test_pdf_proxy_502_when_paperless_unreachable(
    tmp_path: Path, patched_paperless: type[_StubPaperlessClient]
) -> None:
    """A Paperless network error maps to a 502 Bad Gateway."""
    patched_paperless.next_outcome = httpx.ConnectError("refused")
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="readonly")
        client = build_account_client(settings, app_db, store_reader)
        client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "alice-password", "remember": False},
        )
        response = client.get("/api/documents/100/pdf")
        assert response.status_code == 502
    finally:
        store_reader.close()
        app_db.close()


def test_pdf_proxy_401_when_unauthenticated(
    tmp_path: Path, patched_paperless: type[_StubPaperlessClient]
) -> None:
    """An unauthenticated request is rejected 401, before any Paperless call."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        # A user exists so the app is past first-run setup, but we do not
        # log in.
        seed_user(app_db, username="alice", password="alice-password", role="readonly")
        client = build_account_client(settings, app_db, store_reader)
        response = client.get("/api/documents/100/pdf")
        assert response.status_code == 401
    finally:
        store_reader.close()
        app_db.close()
