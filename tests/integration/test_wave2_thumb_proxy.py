"""Integration tests for the Wave 2 thumbnail proxy.

Exercises GET /api/documents/{id}/thumb through the real search FastAPI app
(built by ``create_app``) over a real ``tmp_path`` ``app.db`` and seeded
``index.db``. Paperless-ngx itself is mocked: ``create_app`` builds the
document router with the real ``PaperlessClient`` factory, so the Paperless
client class is patched to a stub the factory then constructs.

Coverage:
- A signed-in user streams a document thumbnail body, 200.
- The response Content-Type is forwarded for a known image type (image/webp).
- An unknown document id maps to 404.
- An unreachable Paperless maps to 502.
- A non-image content type from Paperless maps to 502.
- An unauthenticated request is rejected 401.
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

_THUMB_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-thumbnail\xff\xd9"
_WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP"


class _StubPaperlessClient:
    """A stand-in PaperlessClient whose thumb_stream is scripted.

    Constructed by the real ``_default_paperless_factory`` once the
    ``PaperlessClient`` name in ``search.document_routes`` is patched to this
    class. Class attributes script the next ``thumb_stream`` outcome so a
    test sets behaviour before issuing the request.
    """

    # Set by each test: either ("image/jpeg", <bytes>) to stream, or an
    # exception instance to raise from thumb_stream.
    next_outcome: object = ("image/jpeg", _THUMB_BYTES)

    def __init__(self, _settings: object) -> None:
        """Accept the settings argument the factory passes; ignore it."""

    def thumb_stream(self, _doc_id: int) -> tuple[str, Iterator[bytes]]:
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
    """Patch search.document_routes.PaperlessClient to the stub class.

    Resets ``next_outcome`` to the default success before each test.
    """
    _StubPaperlessClient.next_outcome = ("image/jpeg", _THUMB_BYTES)
    monkeypatch.setattr("search.document_routes.PaperlessClient", _StubPaperlessClient)
    return _StubPaperlessClient


def _make_404_error() -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError carrying a 404 response."""
    request = httpx.Request("GET", "https://paperless.example/thumb")
    response = httpx.Response(404, request=request)
    return httpx.HTTPStatusError("not found", request=request, response=response)


def test_thumb_proxy_streams_for_a_signed_in_user(
    tmp_path: Path, patched_paperless: type[_StubPaperlessClient]
) -> None:
    """A signed-in user gets the thumbnail body streamed back, 200."""
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

        response = client.get("/api/documents/100/thumb")
        assert response.status_code == 200
        assert response.content == _THUMB_BYTES
    finally:
        store_reader.close()
        app_db.close()


def test_thumb_proxy_forwards_webp_content_type(
    tmp_path: Path, patched_paperless: type[_StubPaperlessClient]
) -> None:
    """A WebP thumbnail is forwarded with its correct content type."""
    patched_paperless.next_outcome = ("image/webp", _WEBP_BYTES)
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
        response = client.get("/api/documents/100/thumb")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/webp")
    finally:
        store_reader.close()
        app_db.close()


def test_thumb_proxy_404_for_an_unknown_document(
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
        response = client.get("/api/documents/424242/thumb")
        assert response.status_code == 404
    finally:
        store_reader.close()
        app_db.close()


def test_thumb_proxy_502_when_paperless_unreachable(
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
        response = client.get("/api/documents/100/thumb")
        assert response.status_code == 502
    finally:
        store_reader.close()
        app_db.close()


def test_thumb_proxy_502_for_non_image_content_type(
    tmp_path: Path, patched_paperless: type[_StubPaperlessClient]
) -> None:
    """A non-image content type from Paperless is rejected as 502."""
    # An .html or .svg stored in Paperless must not be served as active content.
    patched_paperless.next_outcome = ("text/html", b"<html>evil</html>")
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
        response = client.get("/api/documents/100/thumb")
        assert response.status_code == 502
    finally:
        store_reader.close()
        app_db.close()


def test_thumb_proxy_401_when_unauthenticated(
    tmp_path: Path, patched_paperless: type[_StubPaperlessClient]
) -> None:
    """An unauthenticated request is rejected 401, before any Paperless call."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="readonly")
        client = build_account_client(settings, app_db, store_reader)
        response = client.get("/api/documents/100/thumb")
        assert response.status_code == 401
    finally:
        store_reader.close()
        app_db.close()
