"""Tests for common.paperless — client setup, document CRUD, list endpoints,
create-named-item, retry behaviour, ping, and close.

iter_all_documents, document_exists, and create-named-item edge cases live in
test_paperless_iter.py (§3.1 500-line ceiling split).
"""

from __future__ import annotations

import json as json_mod
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from common.paperless import PaperlessClient
from tests.helpers.factories import make_settings_obj

BASE = "http://paperless:8000"


def _make_settings(**overrides):
    defaults = dict(
        PAPERLESS_URL=BASE,
        PAPERLESS_TOKEN="test-token-abc",
        REQUEST_TIMEOUT=30,
        MAX_RETRIES=3,
        MAX_RETRY_BACKOFF_SECONDS=0,  # no real sleeping in tests
    )
    defaults.update(overrides)
    return make_settings_obj(**defaults)


class _ClientRegistry:
    """Tracks PaperlessClient instances for automatic cleanup."""

    def __init__(self) -> None:
        self.clients: list[PaperlessClient] = []

    def register(self, client: PaperlessClient) -> PaperlessClient:
        self.clients.append(client)
        return client

    def close_all(self) -> None:
        # PaperlessClient.close() just closes the httpx session; it is safe and
        # idempotent, so no error guard is needed (CODE_GUIDELINES §17.6).
        for client in self.clients:
            client.close()
        self.clients.clear()


_registry = _ClientRegistry()


@pytest.fixture(autouse=True)
def _auto_close_clients():
    """Guarantee every PaperlessClient created during a test is closed."""
    _registry.close_all()
    yield
    _registry.close_all()


def _make_client(settings=None):
    """Create a PaperlessClient with test settings.

    All clients created via this helper are automatically closed after each
    test by the ``_auto_close_clients`` fixture, ensuring no resource leaks
    even when assertions fail.
    """
    if settings is None:
        settings = _make_settings()
    c = PaperlessClient(settings)
    return _registry.register(c)


class TestInitialization:
    def test_creates_httpx_client_with_auth_header_and_timeout(self):
        settings = _make_settings()
        client = _make_client(settings)

        assert client._client.headers["authorization"] == "Token test-token-abc"
        assert client._client.timeout == httpx.Timeout(30)
        client.close()


class TestListAllPagination:
    def test_follows_next_links_across_multiple_pages(self):
        url1 = f"{BASE}/api/things/"
        url2 = f"{BASE}/api/things/?page=2"
        url3 = f"{BASE}/api/things/?page=3"
        with respx.mock:
            respx.get(url__eq=url1).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "results": [{"id": 1}],
                        "next": url2,
                    },
                )
            )
            respx.get(url__eq=url2).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "results": [{"id": 2}],
                        "next": url3,
                    },
                )
            )
            respx.get(url__eq=url3).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "results": [{"id": 3}],
                        "next": None,
                    },
                )
            )

            client = _make_client()

            results = list(client._list_all(url1))

        assert results == [{"id": 1}, {"id": 2}, {"id": 3}]
        client.close()

    def test_yields_all_results_from_all_pages(self):
        url1 = f"{BASE}/api/x/"
        url2 = f"{BASE}/api/x/?page=2"
        with respx.mock:
            respx.get(url__eq=url1).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "results": [{"id": 1}, {"id": 2}],
                        "next": url2,
                    },
                )
            )
            respx.get(url__eq=url2).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "results": [{"id": 3}],
                        "next": None,
                    },
                )
            )

            client = _make_client()

            results = list(client._list_all(url1))

        assert len(results) == 3
        client.close()


class TestGetDocumentsByTag:
    def test_constructs_correct_url_with_tag_id(self):
        url = f"{BASE}/api/documents/?tags__id=443&page_size=100"
        with respx.mock:
            respx.get(url__eq=url).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "results": [{"id": 10}],
                        "next": None,
                    },
                )
            )
            client = _make_client()

            results = list(client.get_documents_by_tag(443))

        assert results == [{"id": 10}]
        client.close()

    def test_returns_all_documents_via_pagination(self):
        url1 = f"{BASE}/api/documents/?tags__id=5&page_size=100"
        url2 = f"{BASE}/api/documents/?tags__id=5&page_size=100&page=2"
        with respx.mock:
            respx.get(url__eq=url1).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "results": [{"id": 1}],
                        "next": url2,
                    },
                )
            )
            respx.get(url__eq=url2).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "results": [{"id": 2}],
                        "next": None,
                    },
                )
            )
            client = _make_client()

            results = list(client.get_documents_by_tag(5))

        assert len(results) == 2
        client.close()


class TestGetDocument:
    def test_fetches_single_document_by_id(self):
        doc = {"id": 42, "title": "Test", "tags": [1]}
        with respx.mock:
            respx.get(f"{BASE}/api/documents/42/").mock(
                return_value=httpx.Response(200, json=doc),
            )
            client = _make_client()

            result = client.get_document(42)

        assert result == doc
        client.close()

    def test_raises_on_http_error(self):
        with respx.mock:
            respx.get(f"{BASE}/api/documents/99/").mock(
                return_value=httpx.Response(404),
            )
            client = _make_client()

            with pytest.raises(httpx.HTTPStatusError):
                client.get_document(99)
        client.close()


class TestDownloadContent:
    def test_returns_bytes_and_content_type_tuple(self):
        with respx.mock:
            respx.get(f"{BASE}/api/documents/1/download/").mock(
                return_value=httpx.Response(
                    200,
                    content=b"PDF-bytes-here",
                    headers={"Content-Type": "application/pdf"},
                ),
            )
            client = _make_client()

            content, ct = client.download_content(1)

        assert content == b"PDF-bytes-here"
        assert ct == "application/pdf"
        client.close()

    def test_defaults_content_type_to_application_pdf(self):
        with respx.mock:
            respx.get(f"{BASE}/api/documents/1/download/").mock(
                return_value=httpx.Response(200, content=b"data"),
            )
            client = _make_client()

            _, ct = client.download_content(1)

        assert ct == "application/pdf"
        client.close()


class TestUpdateDocument:
    def test_sends_patch_with_content_and_tags(self):
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/1/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()

            client.update_document(1, "new content", [10, 20])

        assert route.called
        body = route.calls[0].request.content
        assert b"new content" in body
        client.close()


class TestUpdateDocumentMetadata:
    def test_sends_only_non_none_fields(self):
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/1/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()

            client.update_document_metadata(1, title="New Title", tags=[5])

        assert route.called
        body = json_mod.loads(route.calls[0].request.content)
        assert body["title"] == "New Title"
        assert body["tags"] == [5]
        assert "correspondent" not in body
        client.close()

    def test_does_nothing_when_all_fields_are_none(self):
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/1/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()

            client.update_document_metadata(1)

        assert not route.called
        client.close()

    def test_forwards_null_to_clear_field(self):
        """Explicit None is forwarded to Paperless as null — clears the field."""
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/42/").mock(
                return_value=httpx.Response(200, json={"id": 42}),
            )
            client = _make_client()

            client.update_document_metadata(42, title=None, correspondent_id=None)

        assert route.called
        body = json_mod.loads(route.calls[0].request.content)
        assert body == {"title": None, "correspondent": None}
        client.close()

    def test_skips_absent_fields(self):
        """Fields NOT passed as kwargs do not appear in the payload."""
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/42/").mock(
                return_value=httpx.Response(200, json={"id": 42}),
            )
            client = _make_client()

            client.update_document_metadata(42, title="just title")

        assert route.called
        body = json_mod.loads(route.calls[0].request.content)
        assert body == {"title": "just title"}  # no other keys
        client.close()


class TestListEndpoints:
    def test_list_correspondents(self):
        url = f"{BASE}/api/correspondents/?page_size=100"
        with respx.mock:
            respx.get(url__eq=url).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "results": [{"id": 1, "name": "Alice"}],
                        "next": None,
                    },
                ),
            )
            client = _make_client()

            result = client.list_correspondents()

        assert result == [{"id": 1, "name": "Alice"}]
        client.close()

    def test_list_document_types(self):
        url = f"{BASE}/api/document_types/?page_size=100"
        with respx.mock:
            respx.get(url__eq=url).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "results": [{"id": 2, "name": "Invoice"}],
                        "next": None,
                    },
                ),
            )
            client = _make_client()

            result = client.list_document_types()

        assert result == [{"id": 2, "name": "Invoice"}]
        client.close()

    def test_list_tags(self):
        url = f"{BASE}/api/tags/?page_size=100"
        with respx.mock:
            respx.get(url__eq=url).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "results": [{"id": 3, "name": "ocr"}],
                        "next": None,
                    },
                ),
            )
            client = _make_client()

            result = client.list_tags()

        assert result == [{"id": 3, "name": "ocr"}]
        client.close()


class TestCreateNamedItems:
    def test_creates_item_with_matching_algorithm(self):
        with respx.mock:
            respx.post(f"{BASE}/api/tags/").mock(
                return_value=httpx.Response(201, json={"id": 10, "name": "new-tag"}),
            )
            client = _make_client()

            result = client.create_tag("new-tag", matching_algorithm="none")

        assert result == {"id": 10, "name": "new-tag"}
        client.close()

    def test_falls_back_string_to_int_on_400_error(self):
        # Arrange — first call with "none" fails 400, second with 0 succeeds
        with respx.mock:
            route = respx.post(f"{BASE}/api/correspondents/")
            route.side_effect = [
                httpx.Response(400, json={"error": "bad"}),
                httpx.Response(201, json={"id": 1, "name": "X"}),
            ]
            client = _make_client()

            result = client.create_correspondent("X", matching_algorithm="none")

        assert result == {"id": 1, "name": "X"}
        assert route.call_count == 2
        client.close()

    def test_falls_back_int_to_string_on_400_error(self):
        # Arrange — first call with int 0 fails 400, second with "none" succeeds
        with respx.mock:
            route = respx.post(f"{BASE}/api/document_types/")
            route.side_effect = [
                httpx.Response(400, json={"error": "bad"}),
                httpx.Response(201, json={"id": 2, "name": "Y"}),
            ]
            client = _make_client()

            result = client.create_document_type("Y", matching_algorithm=0)

        assert result == {"id": 2, "name": "Y"}
        client.close()

    def test_passes_matching_algorithm_none_correctly(self):
        with respx.mock:
            route = respx.post(f"{BASE}/api/tags/")
            route.mock(return_value=httpx.Response(201, json={"id": 5, "name": "Z"}))
            client = _make_client()

            result = client.create_tag("Z", matching_algorithm=None)

        body = json_mod.loads(route.calls[0].request.content)
        assert "matching_algorithm" not in body
        assert result == {"id": 5, "name": "Z"}
        client.close()

    def test_raises_on_non_400_error(self):
        with respx.mock:
            respx.post(f"{BASE}/api/tags/").mock(
                return_value=httpx.Response(500),
            )
            client = _make_client()

            # Act / Assert — 500 triggers _raise_for_status_if_server_error
            # which raises HTTPStatusError; the retry exhausts MAX_RETRIES
            with pytest.raises(httpx.HTTPStatusError):
                client.create_tag("fail-tag", matching_algorithm="none")
        client.close()


class TestRetryBehavior:
    def test_retries_on_network_error(self):
        with respx.mock:
            route = respx.get(f"{BASE}/api/documents/1/")
            route.side_effect = [
                httpx.ConnectError("conn refused"),
                httpx.Response(200, json={"id": 1}),
            ]
            client = _make_client()

            result = client.get_document(1)

        assert result == {"id": 1}
        assert route.call_count == 2
        client.close()

    def test_retries_on_5xx_server_error(self):
        with respx.mock:
            route = respx.get(f"{BASE}/api/documents/1/")
            route.side_effect = [
                httpx.Response(503),
                httpx.Response(200, json={"id": 1}),
            ]
            client = _make_client()

            result = client.get_document(1)

        assert result == {"id": 1}
        client.close()

    def test_does_not_retry_on_4xx_client_error(self):
        with respx.mock:
            route = respx.get(f"{BASE}/api/documents/1/")
            route.mock(return_value=httpx.Response(404))
            client = _make_client()

            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                client.get_document(1)
            assert exc_info.value.response.status_code == 404
            assert route.call_count == 1
        client.close()

    def test_raises_after_max_retries_exhausted(self):
        with respx.mock:
            route = respx.get(f"{BASE}/api/documents/1/")
            route.side_effect = [
                httpx.ConnectError("fail1"),
                httpx.ConnectError("fail2"),
                httpx.ConnectError("fail3"),
            ]
            client = _make_client()

            with pytest.raises(httpx.ConnectError):
                client.get_document(1)
            assert route.call_count == 3
        client.close()


class TestPing:
    def test_single_request_without_retry(self):
        with respx.mock:
            route = respx.get(f"{BASE}/api/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()

            client.ping()

        assert route.call_count == 1
        client.close()

    def test_follows_redirect(self):
        # Arrange – Paperless-ngx may redirect /api/ to schema/view/
        with respx.mock:
            respx.get(f"{BASE}/api/").mock(
                return_value=httpx.Response(
                    302,
                    headers={"Location": f"{BASE}/api/schema/view/"},
                ),
            )
            respx.get(f"{BASE}/api/schema/view/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()

            client.ping()

        client.close()

    def test_raises_on_failure(self):
        with respx.mock:
            respx.get(f"{BASE}/api/").mock(
                return_value=httpx.Response(500),
            )
            client = _make_client()

            with pytest.raises(httpx.HTTPStatusError):
                client.ping()
        client.close()


class TestCountDocuments:
    def test_count_documents_returns_the_paperless_count(self):
        """count_documents reads the `count` field of the documents list page."""
        url = f"{BASE}/api/documents/?page_size=1"
        with respx.mock:
            respx.get(url__eq=url).mock(
                return_value=httpx.Response(
                    200,
                    json={"count": 14238, "results": []},
                )
            )
            client = _make_client()
            count = client.count_documents()

        assert count == 14238
        client.close()

    def test_count_documents_raises_on_http_error(self):
        """A non-2xx from Paperless raises HTTPStatusError."""
        url = f"{BASE}/api/documents/?page_size=1"
        with respx.mock:
            respx.get(url__eq=url).mock(
                return_value=httpx.Response(401),
            )
            client = _make_client()
            with pytest.raises(httpx.HTTPStatusError):
                client.count_documents()
        client.close()


class TestClose:
    def test_closes_underlying_httpx_client(self):
        client = _make_client()

        client.close()

        # Assert — httpx.Client is closed; subsequent requests would fail
        assert client._client.is_closed


class TestDeleteDocument:
    def test_delete_document_sends_delete_request(self):
        with respx.mock:
            route = respx.delete(f"{BASE}/api/documents/42/").mock(
                return_value=httpx.Response(204)
            )
            client = _make_client()
            client.delete_document(42)
        assert route.called
        client.close()


class TestNoteHelpers:
    def test_add_note_posts_to_notes_endpoint(self):
        with respx.mock:
            route = respx.post(f"{BASE}/api/documents/42/notes/").mock(
                return_value=httpx.Response(201, json={"id": 7, "note": "hi"})
            )
            client = _make_client()
            client.add_note(42, "hi")
        assert route.called
        body = json_mod.loads(route.calls[0].request.content)
        assert body == {"note": "hi"}
        client.close()

    def test_delete_note_sends_delete_with_id_query(self):
        with respx.mock:
            route = respx.delete(
                f"{BASE}/api/documents/42/notes/",
                params={"id": "7"},
            ).mock(return_value=httpx.Response(204))
            client = _make_client()
            client.delete_note(42, 7)
        assert route.called
        client.close()

    def test_list_notes_reads_document_notes_array(self):
        with respx.mock:
            respx.get(f"{BASE}/api/documents/42/").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "id": 42,
                        "notes": [
                            {"id": 1, "note": "first"},
                            {"id": 2, "note": "second"},
                        ],
                    },
                )
            )
            client = _make_client()
            notes = client.list_notes(42)
        assert notes == [{"id": 1, "note": "first"}, {"id": 2, "note": "second"}]
        client.close()

    def test_list_notes_handles_missing_notes_field(self):
        with respx.mock:
            respx.get(f"{BASE}/api/documents/42/").mock(
                return_value=httpx.Response(200, json={"id": 42})
            )
            client = _make_client()
            assert client.list_notes(42) == []
        client.close()


class TestUpdateDocumentMetadataNotes:
    def test_update_document_metadata_supports_notes_replace(self):
        """Notes are written via separate endpoint: delete all existing, then add new."""
        with respx.mock:
            respx.get(f"{BASE}/api/documents/42/").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "id": 42,
                        "notes": [{"id": 1, "note": "old"}, {"id": 5, "note": "older"}],
                    },
                )
            )
            delete_route = respx.delete(f"{BASE}/api/documents/42/notes/").mock(
                return_value=httpx.Response(204)
            )
            post_route = respx.post(f"{BASE}/api/documents/42/notes/").mock(
                return_value=httpx.Response(201, json={"id": 9, "note": "fresh"})
            )

            client = _make_client()
            client.update_document_metadata(42, notes="fresh")

        assert delete_route.call_count == 2
        assert post_route.called
        client.close()

    def test_update_document_metadata_notes_empty_string_deletes_all(self):
        """notes='' deletes existing notes without adding a new one."""
        with respx.mock:
            respx.get(f"{BASE}/api/documents/42/").mock(
                return_value=httpx.Response(
                    200, json={"id": 42, "notes": [{"id": 1, "note": "old"}]}
                )
            )
            delete_route = respx.delete(f"{BASE}/api/documents/42/notes/").mock(
                return_value=httpx.Response(204)
            )
            post_route = respx.post(f"{BASE}/api/documents/42/notes/").mock(
                return_value=httpx.Response(201)
            )

            client = _make_client()
            client.update_document_metadata(42, notes="")

        assert delete_route.called
        assert not post_route.called
        client.close()

    def test_update_document_metadata_supports_asn(self):
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/42/").mock(
                return_value=httpx.Response(200, json={"id": 42})
            )
            client = _make_client()
            client.update_document_metadata(42, archive_serial_number=12345)
        assert route.called
        body = json_mod.loads(route.calls[0].request.content)
        assert body == {"archive_serial_number": 12345}
        client.close()


class TestDownloadStream:
    """PaperlessClient.download_stream streams a document without buffering."""

    @staticmethod
    def _streaming_client(
        monkeypatch: pytest.MonkeyPatch,
        *,
        body: bytes,
        status_code: int = 200,
        content_type: str = "application/pdf",
    ) -> PaperlessClient:
        """Build a PaperlessClient whose httpx session is a MockTransport.

        The transport answers any request with *body*, *status_code* and
        *content_type*, so download_stream is exercised with no network.
        """
        settings = MagicMock()
        settings.PAPERLESS_URL = "https://paperless.example"
        settings.PAPERLESS_TOKEN = "tok"
        settings.REQUEST_TIMEOUT = 30

        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code,
                content=body,
                headers={"Content-Type": content_type},
            )

        client = PaperlessClient(settings)
        # Replace the real httpx session with one backed by the mock
        # transport; close the original first so no socket leaks.
        client._client.close()
        client._client = httpx.Client(transport=httpx.MockTransport(_handler))
        return client

    def test_download_stream_yields_the_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The chunk iterator reassembles to the full document body."""
        pdf = b"%PDF-1.7\nfake pdf payload\n%%EOF"
        client = self._streaming_client(monkeypatch, body=pdf)
        try:
            content_type, chunks = client.download_stream(100)
            assembled = b"".join(chunks)
        finally:
            client.close()
        assert assembled == pdf

    def test_download_stream_returns_the_content_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Paperless Content-Type header is returned to the caller."""
        client = self._streaming_client(
            monkeypatch, body=b"%PDF-1.7", content_type="application/pdf"
        )
        try:
            content_type, chunks = client.download_stream(100)
            list(chunks)  # drain so the stream context closes cleanly
        finally:
            client.close()
        assert content_type == "application/pdf"

    def test_download_stream_defaults_content_type_when_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing Content-Type header falls back to application/pdf."""

        def _handler(request: httpx.Request) -> httpx.Response:
            # No Content-Type header at all.
            return httpx.Response(200, content=b"%PDF-1.7")

        settings = MagicMock()
        settings.PAPERLESS_URL = "https://paperless.example"
        settings.PAPERLESS_TOKEN = "tok"
        settings.REQUEST_TIMEOUT = 30
        client = PaperlessClient(settings)
        client._client.close()
        client._client = httpx.Client(transport=httpx.MockTransport(_handler))
        try:
            content_type, chunks = client.download_stream(100)
            list(chunks)
        finally:
            client.close()
        assert content_type == "application/pdf"

    def test_download_stream_raises_on_404(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 404 surfaces as httpx.HTTPStatusError eagerly, before iterating.

        The single-stream rewrite checks raise_for_status() when the stream
        is opened, so the caller never receives a chunk iterator for a
        failed request — the error is raised by download_stream itself.
        """
        client = self._streaming_client(monkeypatch, body=b"not found", status_code=404)
        try:
            with pytest.raises(httpx.HTTPStatusError):
                client.download_stream(999)
        finally:
            client.close()

    def test_download_stream_makes_a_single_http_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """download_stream opens exactly one upstream request, not two.

        The previous implementation made a probe GET for the Content-Type
        and a second GET for the body — doubling Paperless load per PDF
        view. The rewrite reads the headers off the single body stream.
        """
        requests: list[httpx.Request] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, content=b"%PDF-1.7\nbody\n%%EOF")

        settings = MagicMock()
        settings.PAPERLESS_URL = "https://paperless.example"
        settings.PAPERLESS_TOKEN = "tok"
        settings.REQUEST_TIMEOUT = 30
        client = PaperlessClient(settings)
        client._client.close()
        client._client = httpx.Client(transport=httpx.MockTransport(_handler))
        try:
            _content_type, chunks = client.download_stream(100)
            list(chunks)
        finally:
            client.close()
        assert len(requests) == 1
