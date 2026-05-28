"""Tests for search.document_routes — the PDF proxy route and document summary route.

Exercises GET /api/documents/{id}/pdf through a tiny FastAPI app and
TestClient with the AppState wired and a stubbed PaperlessClient, so the
routing, auth gate, streaming and error mapping are all real. Covers: a
signed-in user streams a document; the body and Content-Type are forwarded;
an unknown id maps to 404; a Paperless network error maps to 502; an
unauthenticated request is rejected 401.

Also exercises GET /api/documents/{id} (the shareable-URL document summary
endpoint added in Task 3): returns a DocumentSummaryResponse for a known id,
404 for an unknown id, and 401 when unauthenticated.

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
from store.models import DocumentSummary

_PDF_BYTES = b"%PDF-1.7\nstreamed document body\n%%EOF"


def _make_404_status_error() -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError carrying a 404 response."""
    request = httpx.Request("GET", "https://paperless.example/x")
    response = httpx.Response(404, request=request)
    return httpx.HTTPStatusError("not found", request=request, response=response)


def _build_app(
    app_db_path: str,
    paperless_client,
    store_reader=None,
    settings=None,
) -> FastAPI:
    """A FastAPI app mounting the document router with a stubbed client.

    The router is built with a *paperless_factory* that returns the supplied
    stub, so no real Paperless call is made. An optional *store_reader* stub
    is forwarded to ``build_document_router`` for the document-summary route.
    An optional *settings* mock is forwarded to ``build_document_router`` so
    that tests can configure tag-id attributes on the same object the router
    sees; when omitted a fresh :class:`~unittest.mock.MagicMock` is created.
    """
    app = FastAPI()
    attach_app_state(
        app.state,
        AppState(
            app_db_path=app_db_path,
            setup_state=SetupState(),
        ),
    )
    if settings is None:
        settings = MagicMock()
    app.include_router(
        build_document_router(
            settings,
            paperless_factory=lambda _s: paperless_client,
            store_reader=store_reader if store_reader is not None else MagicMock(),
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


def _client(
    app_db_path: str, paperless_client, store_reader=None, settings=None
) -> TestClient:
    return TestClient(
        _build_app(
            app_db_path, paperless_client, store_reader=store_reader, settings=settings
        ),
        raise_server_exceptions=False,
        base_url="https://testserver",
    )


def _login(conn, *, role: str = "readonly", username: str = "u") -> str:
    """Create a user of *role* and return a live session token."""
    user = create_user(conn, username=username, password_hash="h", role=role)
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
            build_document_router(
                settings,
                paperless_factory=lambda _s: MagicMock(),
                store_reader=MagicMock(),
            )
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


_DOCUMENT_SUMMARY = DocumentSummary(
    id=42,
    title="Test Invoice",
    correspondent="ACME Ltd",
    document_type="Invoice",
    tags=("tax", "2024"),
    created="2024-01-15T00:00:00Z",
    page_count=3,
)


def _build_app_with_paperless_url(
    app_db_path: str,
    paperless_client,
    paperless_url: str,
    store_reader=None,
) -> FastAPI:
    """A FastAPI app mounting the document router with a configured PAPERLESS_URL."""
    app = FastAPI()
    attach_app_state(
        app.state,
        AppState(
            app_db_path=app_db_path,
            setup_state=SetupState(),
        ),
    )
    settings = MagicMock()
    settings.PAPERLESS_URL = paperless_url
    app.include_router(
        build_document_router(
            settings,
            paperless_factory=lambda _s: paperless_client,
            store_reader=store_reader if store_reader is not None else MagicMock(),
        )
    )
    return app


def test_get_document_returns_summary(app_db_path, conn) -> None:
    """GET /api/documents/{id} returns the wire DocumentSummaryResponse for the id."""
    store_reader = MagicMock()
    store_reader.get_document_summary.return_value = _DOCUMENT_SUMMARY
    app = _build_app_with_paperless_url(
        app_db_path, MagicMock(), "https://paperless.example", store_reader=store_reader
    )
    client = TestClient(app, raise_server_exceptions=False, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn))

    response = client.get("/api/documents/42")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 42
    assert body["title"] == "Test Invoice"
    assert body["correspondent"] == "ACME Ltd"
    assert body["document_type"] == "Invoice"
    assert body["created"] == "2024-01-15T00:00:00Z"
    assert body["tags"] == ["tax", "2024"]
    assert body["page_count"] == 3
    store_reader.get_document_summary.assert_called_once_with(42)


def test_get_document_includes_paperless_url(app_db_path, conn) -> None:
    """GET /api/documents/{id} includes the paperless_url for the document."""
    store_reader = MagicMock()
    store_reader.get_document_summary.return_value = _DOCUMENT_SUMMARY
    app = _build_app_with_paperless_url(
        app_db_path, MagicMock(), "https://paperless.example", store_reader=store_reader
    )
    client = TestClient(app, raise_server_exceptions=False, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn))

    response = client.get("/api/documents/42")

    assert response.status_code == 200
    paperless_url = response.json()["paperless_url"]
    assert paperless_url  # non-empty
    assert paperless_url.endswith("/documents/42/")


def test_get_document_404_for_missing_id(app_db_path, conn) -> None:
    """Stub get_document_summary returning None yields a 404."""
    store_reader = MagicMock()
    store_reader.get_document_summary.return_value = None
    client = _client(app_db_path, MagicMock(), store_reader=store_reader)
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn))

    response = client.get("/api/documents/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "document not found"


def test_get_document_requires_auth(app_db_path) -> None:
    """An unauthenticated request to GET /api/documents/{id} is rejected 401."""
    store_reader = MagicMock()
    client = _client(app_db_path, MagicMock(), store_reader=store_reader)

    response = client.get("/api/documents/42")

    assert response.status_code == 401
    store_reader.get_document_summary.assert_not_called()


# ---------------------------------------------------------------------------
# PATCH /api/documents/{id}
# ---------------------------------------------------------------------------


def _min_summary(doc_id: int) -> DocumentSummary:
    """A minimal :class:`DocumentSummary` factory for PATCH tests."""
    return DocumentSummary(
        id=doc_id,
        title=None,
        correspondent=None,
        document_type=None,
        tags=(),
        created=None,
        page_count=None,
    )


class PaperlessStub:
    """A minimal Paperless stub recording ``update_document_metadata`` and taxonomy calls.

    Replaces ``MagicMock`` for PATCH tests that need to assert on what was
    sent to Paperless, and for taxonomy GET/POST tests (correspondents,
    document-types, tags).  Also supports ``get_document`` (pipeline tag-swap
    tests) and ``delete_document`` (delete-document tests).
    """

    def __init__(self) -> None:
        self._update_calls: list[tuple[int, dict]] = []
        self._list_returns: dict[str, list] = {}
        self._create_returns: dict[str, dict] = {}
        self._create_calls: list[tuple[str, str]] = []
        self._get_document_return: dict[str, object] | None = None
        self._delete_calls: list[int] = []
        # Needed by the router; handlers call close() in a finally.
        self.close = MagicMock()

    # ------------------------------------------------------------------
    # PATCH support
    # ------------------------------------------------------------------

    def update_document_metadata(self, doc_id: int, **kwargs) -> None:
        """Record the call and return without error."""
        self._update_calls.append((doc_id, dict(kwargs)))

    def assert_update_document_metadata_called_with(
        self, doc_id: int, **expected_kwargs
    ) -> None:
        """Assert exactly one call was made with the given document id and kwargs."""
        assert self._update_calls, "update_document_metadata was never called"
        assert len(self._update_calls) == 1, (
            f"expected one call, got {len(self._update_calls)}: {self._update_calls}"
        )
        actual_id, actual_kwargs = self._update_calls[0]
        assert actual_id == doc_id, f"expected doc_id={doc_id}, got {actual_id}"
        assert actual_kwargs == expected_kwargs, (
            f"expected kwargs {expected_kwargs!r}, got {actual_kwargs!r}"
        )

    # ------------------------------------------------------------------
    # Taxonomy list/create support
    # ------------------------------------------------------------------

    def set_list_return(self, method_name: str, items: list) -> None:
        """Configure what a list_* method returns."""
        self._list_returns[method_name] = items

    def set_create_return(self, method_name: str, item: dict) -> None:
        """Configure what a create_* method returns."""
        self._create_returns[method_name] = item

    def list_correspondents(self) -> list:
        """Return pre-configured correspondents list."""
        return self._list_returns.get("list_correspondents", [])

    def list_document_types(self) -> list:
        """Return pre-configured document types list."""
        return self._list_returns.get("list_document_types", [])

    def list_tags(self) -> list:
        """Return pre-configured tags list."""
        return self._list_returns.get("list_tags", [])

    def create_correspondent(self, name: str) -> dict:
        """Record the call and return the pre-configured response."""
        self._create_calls.append(("create_correspondent", name))
        return self._create_returns.get("create_correspondent", {"id": 0, "name": name})

    def create_document_type(self, name: str) -> dict:
        """Record the call and return the pre-configured response."""
        self._create_calls.append(("create_document_type", name))
        return self._create_returns.get("create_document_type", {"id": 0, "name": name})

    def create_tag(self, name: str) -> dict:
        """Record the call and return the pre-configured response."""
        self._create_calls.append(("create_tag", name))
        return self._create_returns.get("create_tag", {"id": 0, "name": name})

    def assert_create_called_with(self, method_name: str, name: str) -> None:
        """Assert that *method_name* was called with *name*."""
        assert (method_name, name) in self._create_calls, (
            f"expected {method_name}({name!r}); calls were {self._create_calls}"
        )

    # ------------------------------------------------------------------
    # Pipeline tag-swap support (reclassify / retranscribe)
    # ------------------------------------------------------------------

    def set_get_document_return(self, doc: dict) -> None:
        """Configure the dict returned by :meth:`get_document`."""
        self._get_document_return = doc

    def get_document(self, doc_id: int) -> dict:
        """Return the pre-configured document dict, or a minimal default."""
        if self._get_document_return is None:
            return {"id": doc_id, "tags": []}
        return self._get_document_return

    # ------------------------------------------------------------------
    # Delete support
    # ------------------------------------------------------------------

    def delete_document(self, doc_id: int) -> None:
        """Record the delete call."""
        self._delete_calls.append(doc_id)

    def assert_delete_document_called_with(self, doc_id: int) -> None:
        """Assert that :meth:`delete_document` was called with *doc_id*."""
        assert doc_id in self._delete_calls, (
            f"expected delete({doc_id}); calls were {self._delete_calls}"
        )


def test_patch_document_forwards_metadata_to_paperless(app_db_path, conn) -> None:
    """PATCH /api/documents/{id} proxies the request body to Paperless."""
    paperless = PaperlessStub()
    store_reader = MagicMock()
    store_reader.get_document_summary.return_value = DocumentSummary(
        id=42,
        title="Renamed",
        correspondent=None,
        document_type=None,
        tags=(),
        created=None,
        page_count=None,
    )
    app = _build_app_with_paperless_url(
        app_db_path, paperless, "https://paperless.example", store_reader=store_reader
    )
    client = TestClient(app, raise_server_exceptions=False, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn, role="member"))

    response = client.patch("/api/documents/42", json={"title": "Renamed", "tags": [1, 2, 3]})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 42
    assert body["title"] == "Renamed"
    paperless.assert_update_document_metadata_called_with(42, title="Renamed", tags={1, 2, 3})


def test_patch_document_with_notes_field(app_db_path, conn) -> None:
    """PATCH with only ``notes`` passes the note text through to Paperless."""
    paperless = PaperlessStub()
    store_reader = MagicMock()
    store_reader.get_document_summary.return_value = _min_summary(42)
    app = _build_app_with_paperless_url(
        app_db_path, paperless, "https://paperless.example", store_reader=store_reader
    )
    client = TestClient(app, raise_server_exceptions=False, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn, role="member"))

    response = client.patch("/api/documents/42", json={"notes": "hello"})

    assert response.status_code == 200
    paperless.assert_update_document_metadata_called_with(42, notes="hello")


def test_patch_document_readonly_forbidden(app_db_path, conn) -> None:
    """A read-only user is rejected 403 from PATCH /api/documents/{id}."""
    client = _client(app_db_path, PaperlessStub())
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn, role="readonly"))

    response = client.patch("/api/documents/42", json={"title": "x"})

    assert response.status_code == 403


def test_patch_document_unauthenticated(app_db_path) -> None:
    """An unauthenticated PATCH request is rejected 401."""
    client = _client(app_db_path, PaperlessStub())

    response = client.patch("/api/documents/42", json={"title": "x"})

    assert response.status_code == 401


def test_patch_document_returns_404_when_document_missing(app_db_path, conn) -> None:
    """When the store has no record for the id, a 404 is returned."""
    paperless = PaperlessStub()
    store_reader = MagicMock()
    store_reader.get_document_summary.return_value = None
    app = _build_app_with_paperless_url(
        app_db_path, paperless, "https://paperless.example", store_reader=store_reader
    )
    client = TestClient(app, raise_server_exceptions=False, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn, role="member"))

    response = client.patch("/api/documents/42", json={"title": "x"})

    assert response.status_code == 404
    assert response.json()["detail"] == "document not found"


def test_patch_document_null_clears_field(app_db_path, conn) -> None:
    """Sending null for a field clears it — the backend must forward null, not skip it."""
    paperless = PaperlessStub()
    store_reader = MagicMock()
    store_reader.get_document_summary.return_value = _min_summary(42)
    app = _build_app_with_paperless_url(
        app_db_path, paperless, "https://paperless.example", store_reader=store_reader
    )
    client = TestClient(app, raise_server_exceptions=False, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn, role="member"))

    response = client.patch("/api/documents/42", json={"title": None})

    assert response.status_code == 200
    paperless.assert_update_document_metadata_called_with(42, title=None)


# ---------------------------------------------------------------------------
# Taxonomy GET + POST  (/api/correspondents, /api/document-types, /api/tags)
# ---------------------------------------------------------------------------


@pytest.fixture()
def paperless_stub() -> PaperlessStub:
    """A fresh :class:`PaperlessStub` for taxonomy tests."""
    return PaperlessStub()


@pytest.fixture()
def settings() -> MagicMock:
    """A :class:`~unittest.mock.MagicMock` wired into the test app as ``settings``.

    Shared between the app under test and the test body, so tests that need
    to configure ``CLASSIFY_PRE_TAG_ID`` etc. write to the same object the
    router closure sees.
    """
    return MagicMock()


@pytest.fixture()
def api_client(app_db_path, conn, paperless_stub, settings) -> TestClient:
    """A :class:`TestClient` signed in as a ``member`` user."""
    client = _client(app_db_path, paperless_stub, settings=settings)
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn, role="member"))
    return client


@pytest.fixture()
def readonly_client(app_db_path, conn, paperless_stub, settings) -> TestClient:
    """A :class:`TestClient` signed in as a ``readonly`` user."""
    client = _client(app_db_path, paperless_stub, settings=settings)
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn, role="readonly", username="readonly_u"))
    return client


@pytest.fixture()
def unauthenticated_client(app_db_path, paperless_stub, settings) -> TestClient:
    """A :class:`TestClient` with no session cookie."""
    return _client(app_db_path, paperless_stub, settings=settings)


@pytest.fixture()
def member_client(app_db_path, conn, paperless_stub, settings) -> TestClient:
    """A :class:`TestClient` signed in as a ``member`` user.

    Exposed separately from :func:`api_client` so auth-gate tests can name
    both ``member_client`` and ``readonly_client`` (or ``admin_client``)
    explicitly without a username collision.
    """
    client = _client(app_db_path, paperless_stub, settings=settings)
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn, role="member", username="member_u"))
    return client


@pytest.fixture()
def admin_client(app_db_path, conn, paperless_stub, settings) -> TestClient:
    """A :class:`TestClient` signed in as an ``admin`` user."""
    client = _client(app_db_path, paperless_stub, settings=settings)
    client.cookies.set(SESSION_COOKIE_NAME, _login(conn, role="admin", username="admin_u"))
    return client


@pytest.mark.parametrize(
    "path,list_method",
    [
        ("/api/correspondents", "list_correspondents"),
        ("/api/document-types", "list_document_types"),
        ("/api/tags", "list_tags"),
    ],
)
def test_taxonomy_get_returns_list(api_client, paperless_stub, path, list_method) -> None:
    """GET on a taxonomy path returns the list from Paperless as JSON."""
    paperless_stub.set_list_return(list_method, [{"id": 1, "name": "ACME", "document_count": 7}])
    r = api_client.get(path)
    assert r.status_code == 200
    body = r.json()
    assert body == [{"id": 1, "name": "ACME", "document_count": 7}]


def test_taxonomy_get_handles_alternate_count_field(api_client, paperless_stub) -> None:
    """Older Paperless versions return ``documents_count`` (plural) or ``documents`` (list)."""
    paperless_stub.set_list_return(
        "list_tags",
        [
            {"id": 1, "name": "with-plural", "documents_count": 5},
            {"id": 2, "name": "with-list", "documents": [10, 11, 12]},
            {"id": 3, "name": "with-string-count", "document_count": "9"},
            {"id": 4, "name": "with-none-count"},
        ],
    )
    body = api_client.get("/api/tags").json()
    assert {"id": 1, "name": "with-plural", "document_count": 5} in body
    # ``documents`` is a list — the helper reports 0 (does not infer from the list).
    assert {"id": 2, "name": "with-list", "document_count": 0} in body
    # String count must be coerced to int.
    assert {"id": 3, "name": "with-string-count", "document_count": 9} in body
    # Missing count defaults to 0.
    assert {"id": 4, "name": "with-none-count", "document_count": 0} in body


@pytest.mark.parametrize(
    "path,create_method",
    [
        ("/api/correspondents", "create_correspondent"),
        ("/api/document-types", "create_document_type"),
        ("/api/tags", "create_tag"),
    ],
)
def test_taxonomy_create_member_returns_201(
    api_client, paperless_stub, path, create_method
) -> None:
    """POST on a taxonomy path creates the item and returns 201."""
    paperless_stub.set_create_return(create_method, {"id": 99, "name": "New", "document_count": 0})
    r = api_client.post(path, json={"name": "New"})
    assert r.status_code == 201
    assert r.json()["id"] == 99
    paperless_stub.assert_create_called_with(create_method, "New")


def test_taxonomy_create_readonly_forbidden(readonly_client) -> None:
    """A read-only user is rejected 403 from POST /api/tags."""
    r = readonly_client.post("/api/tags", json={"name": "x"})
    assert r.status_code == 403


def test_taxonomy_create_unauthenticated(unauthenticated_client) -> None:
    """An unauthenticated POST /api/tags is rejected 401."""
    r = unauthenticated_client.post("/api/tags", json={"name": "x"})
    assert r.status_code == 401


def test_taxonomy_get_unauthenticated(unauthenticated_client) -> None:
    """An unauthenticated GET /api/tags is rejected 401."""
    r = unauthenticated_client.get("/api/tags")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/documents/{id}/reclassify
# POST /api/documents/{id}/retranscribe
# DELETE /api/documents/{id}
# ---------------------------------------------------------------------------


def test_reclassify_swaps_post_tag_for_pre_tag(
    api_client, paperless_stub, settings
) -> None:
    """POST /reclassify removes the classify-post tag and adds the classify-pre tag."""
    paperless_stub.set_get_document_return({"id": 42, "tags": [444, 555]})
    settings.CLASSIFY_PRE_TAG_ID = 333
    settings.CLASSIFY_POST_TAG_ID = 444
    r = api_client.post("/api/documents/42/reclassify")
    assert r.status_code == 202
    paperless_stub.assert_update_document_metadata_called_with(42, tags={333, 555})


def test_retranscribe_swaps_post_tag_for_pre_tag(
    api_client, paperless_stub, settings
) -> None:
    """POST /retranscribe removes the OCR-post tag and adds the OCR-pre tag."""
    paperless_stub.set_get_document_return({"id": 42, "tags": [444]})
    settings.PRE_TAG_ID = 222
    settings.POST_TAG_ID = 444
    r = api_client.post("/api/documents/42/retranscribe")
    assert r.status_code == 202
    paperless_stub.assert_update_document_metadata_called_with(42, tags={222})


def test_reclassify_handles_missing_post_tag(
    api_client, paperless_stub, settings
) -> None:
    """If the document does not carry the post-tag, just add the pre-tag."""
    paperless_stub.set_get_document_return({"id": 42, "tags": [777]})
    settings.CLASSIFY_PRE_TAG_ID = 333
    settings.CLASSIFY_POST_TAG_ID = 444  # not present in tags
    r = api_client.post("/api/documents/42/reclassify")
    assert r.status_code == 202
    paperless_stub.assert_update_document_metadata_called_with(42, tags={333, 777})


def test_reclassify_member_only(
    member_client, readonly_client, paperless_stub, settings
) -> None:
    """POST /reclassify is open to members, forbidden for read-only users."""
    paperless_stub.set_get_document_return({"id": 42, "tags": []})
    settings.CLASSIFY_PRE_TAG_ID = 333
    settings.CLASSIFY_POST_TAG_ID = 444
    assert member_client.post("/api/documents/42/reclassify").status_code == 202
    assert readonly_client.post("/api/documents/42/reclassify").status_code == 403


def test_reclassify_unauthenticated(unauthenticated_client) -> None:
    """An unauthenticated POST /reclassify is rejected 401."""
    assert unauthenticated_client.post("/api/documents/42/reclassify").status_code == 401


def test_retranscribe_member_only(
    member_client, readonly_client, paperless_stub, settings
) -> None:
    """POST /retranscribe is open to members, forbidden for read-only users."""
    paperless_stub.set_get_document_return({"id": 42, "tags": []})
    settings.PRE_TAG_ID = 222
    settings.POST_TAG_ID = 444
    assert member_client.post("/api/documents/42/retranscribe").status_code == 202
    assert readonly_client.post("/api/documents/42/retranscribe").status_code == 403


def test_retranscribe_unauthenticated(unauthenticated_client) -> None:
    """An unauthenticated POST /retranscribe is rejected 401."""
    assert unauthenticated_client.post("/api/documents/42/retranscribe").status_code == 401


def test_delete_document_admin(admin_client, paperless_stub) -> None:
    """DELETE /api/documents/{id} succeeds for an admin user and returns 204."""
    r = admin_client.delete("/api/documents/42")
    assert r.status_code == 204
    paperless_stub.assert_delete_document_called_with(42)


def test_delete_document_member_forbidden(member_client, readonly_client) -> None:
    """DELETE /api/documents/{id} is forbidden for non-admin callers."""
    assert member_client.delete("/api/documents/42").status_code == 403
    assert readonly_client.delete("/api/documents/42").status_code == 403


def test_delete_document_unauthenticated(unauthenticated_client) -> None:
    """An unauthenticated DELETE /api/documents/{id} is rejected 401."""
    assert unauthenticated_client.delete("/api/documents/42").status_code == 401
