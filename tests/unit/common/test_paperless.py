"""
Unit tests for common.paperless.PaperlessClient.

Uses ``respx`` for HTTP mocking so we can test the real httpx client
interactions without touching the network.

Note: ``respx.get(url)`` does prefix matching, so paginated URLs must use
``url__eq`` for exact matching to avoid the base URL matching all pages.
"""

from __future__ import annotations

import json as json_mod

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
        for c in self.clients:
            try:
                c.close()
            except Exception:
                pass
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


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInitialization:
    def test_creates_httpx_client_with_auth_header_and_timeout(self):
        # Arrange / Act
        settings = _make_settings()
        client = _make_client(settings)

        # Assert
        assert client._client.headers["authorization"] == "Token test-token-abc"
        assert client._client.timeout == httpx.Timeout(30)
        client.close()


# ---------------------------------------------------------------------------
# _list_all pagination
# ---------------------------------------------------------------------------

class TestListAllPagination:
    def test_follows_next_links_across_multiple_pages(self):
        # Arrange
        url1 = f"{BASE}/api/things/"
        url2 = f"{BASE}/api/things/?page=2"
        url3 = f"{BASE}/api/things/?page=3"
        with respx.mock:
            respx.get(url__eq=url1).mock(return_value=httpx.Response(200, json={
                "results": [{"id": 1}], "next": url2,
            }))
            respx.get(url__eq=url2).mock(return_value=httpx.Response(200, json={
                "results": [{"id": 2}], "next": url3,
            }))
            respx.get(url__eq=url3).mock(return_value=httpx.Response(200, json={
                "results": [{"id": 3}], "next": None,
            }))

            client = _make_client()

            # Act
            results = list(client._list_all(url1))

        # Assert
        assert results == [{"id": 1}, {"id": 2}, {"id": 3}]
        client.close()

    def test_yields_all_results_from_all_pages(self):
        # Arrange
        url1 = f"{BASE}/api/x/"
        url2 = f"{BASE}/api/x/?page=2"
        with respx.mock:
            respx.get(url__eq=url1).mock(return_value=httpx.Response(200, json={
                "results": [{"id": 1}, {"id": 2}], "next": url2,
            }))
            respx.get(url__eq=url2).mock(return_value=httpx.Response(200, json={
                "results": [{"id": 3}], "next": None,
            }))

            client = _make_client()

            # Act
            results = list(client._list_all(url1))

        # Assert
        assert len(results) == 3
        client.close()


# ---------------------------------------------------------------------------
# get_documents_by_tag
# ---------------------------------------------------------------------------

class TestGetDocumentsByTag:
    def test_constructs_correct_url_with_tag_id(self):
        # Arrange
        url = f"{BASE}/api/documents/?tags__id=443&page_size=100"
        with respx.mock:
            respx.get(url__eq=url).mock(return_value=httpx.Response(200, json={
                "results": [{"id": 10}], "next": None,
            }))
            client = _make_client()

            # Act
            results = list(client.get_documents_by_tag(443))

        # Assert
        assert results == [{"id": 10}]
        client.close()

    def test_returns_all_documents_via_pagination(self):
        # Arrange
        url1 = f"{BASE}/api/documents/?tags__id=5&page_size=100"
        url2 = f"{BASE}/api/documents/?tags__id=5&page_size=100&page=2"
        with respx.mock:
            respx.get(url__eq=url1).mock(return_value=httpx.Response(200, json={
                "results": [{"id": 1}], "next": url2,
            }))
            respx.get(url__eq=url2).mock(return_value=httpx.Response(200, json={
                "results": [{"id": 2}], "next": None,
            }))
            client = _make_client()

            # Act
            results = list(client.get_documents_by_tag(5))

        # Assert
        assert len(results) == 2
        client.close()


# ---------------------------------------------------------------------------
# get_document
# ---------------------------------------------------------------------------

class TestGetDocument:
    def test_fetches_single_document_by_id(self):
        # Arrange
        doc = {"id": 42, "title": "Test", "tags": [1]}
        with respx.mock:
            respx.get(f"{BASE}/api/documents/42/").mock(
                return_value=httpx.Response(200, json=doc),
            )
            client = _make_client()

            # Act
            result = client.get_document(42)

        # Assert
        assert result == doc
        client.close()

    def test_raises_on_http_error(self):
        # Arrange
        with respx.mock:
            respx.get(f"{BASE}/api/documents/99/").mock(
                return_value=httpx.Response(404),
            )
            client = _make_client()

            # Act / Assert
            with pytest.raises(httpx.HTTPStatusError):
                client.get_document(99)
        client.close()


# ---------------------------------------------------------------------------
# download_content
# ---------------------------------------------------------------------------

class TestDownloadContent:
    def test_returns_bytes_and_content_type_tuple(self):
        # Arrange
        with respx.mock:
            respx.get(f"{BASE}/api/documents/1/download/").mock(
                return_value=httpx.Response(
                    200,
                    content=b"PDF-bytes-here",
                    headers={"Content-Type": "application/pdf"},
                ),
            )
            client = _make_client()

            # Act
            content, ct = client.download_content(1)

        # Assert
        assert content == b"PDF-bytes-here"
        assert ct == "application/pdf"
        client.close()

    def test_defaults_content_type_to_application_pdf(self):
        # Arrange
        with respx.mock:
            respx.get(f"{BASE}/api/documents/1/download/").mock(
                return_value=httpx.Response(200, content=b"data"),
            )
            client = _make_client()

            # Act
            _, ct = client.download_content(1)

        # Assert
        assert ct == "application/pdf"
        client.close()


# ---------------------------------------------------------------------------
# update_document
# ---------------------------------------------------------------------------

class TestUpdateDocument:
    def test_sends_patch_with_content_and_tags(self):
        # Arrange
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/1/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()

            # Act
            client.update_document(1, "new content", [10, 20])

        # Assert
        assert route.called
        body = route.calls[0].request.content
        assert b"new content" in body
        client.close()


# ---------------------------------------------------------------------------
# update_document_metadata
# ---------------------------------------------------------------------------

class TestUpdateDocumentMetadata:
    def test_sends_only_non_none_fields(self):
        # Arrange
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/1/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()

            # Act
            client.update_document_metadata(1, title="New Title", tags=[5])

        # Assert
        assert route.called
        body = json_mod.loads(route.calls[0].request.content)
        assert body["title"] == "New Title"
        assert body["tags"] == [5]
        assert "correspondent" not in body
        client.close()

    def test_does_nothing_when_all_fields_are_none(self):
        # Arrange
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/1/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()

            # Act
            client.update_document_metadata(1)

        # Assert
        assert not route.called
        client.close()


# ---------------------------------------------------------------------------
# list_correspondents / document_types / tags
# ---------------------------------------------------------------------------

class TestListEndpoints:
    def test_list_correspondents(self):
        # Arrange
        url = f"{BASE}/api/correspondents/?page_size=100"
        with respx.mock:
            respx.get(url__eq=url).mock(
                return_value=httpx.Response(200, json={
                    "results": [{"id": 1, "name": "Alice"}], "next": None,
                }),
            )
            client = _make_client()

            # Act
            result = client.list_correspondents()

        # Assert
        assert result == [{"id": 1, "name": "Alice"}]
        client.close()

    def test_list_document_types(self):
        # Arrange
        url = f"{BASE}/api/document_types/?page_size=100"
        with respx.mock:
            respx.get(url__eq=url).mock(
                return_value=httpx.Response(200, json={
                    "results": [{"id": 2, "name": "Invoice"}], "next": None,
                }),
            )
            client = _make_client()

            # Act
            result = client.list_document_types()

        # Assert
        assert result == [{"id": 2, "name": "Invoice"}]
        client.close()

    def test_list_tags(self):
        # Arrange
        url = f"{BASE}/api/tags/?page_size=100"
        with respx.mock:
            respx.get(url__eq=url).mock(
                return_value=httpx.Response(200, json={
                    "results": [{"id": 3, "name": "ocr"}], "next": None,
                }),
            )
            client = _make_client()

            # Act
            result = client.list_tags()

        # Assert
        assert result == [{"id": 3, "name": "ocr"}]
        client.close()


# ---------------------------------------------------------------------------
# create_correspondent / document_type / create_tag
# ---------------------------------------------------------------------------

class TestCreateNamedItems:
    def test_creates_item_with_matching_algorithm(self):
        # Arrange
        with respx.mock:
            respx.post(f"{BASE}/api/tags/").mock(
                return_value=httpx.Response(201, json={"id": 10, "name": "new-tag"}),
            )
            client = _make_client()

            # Act
            result = client.create_tag("new-tag", matching_algorithm="none")

        # Assert
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

            # Act
            result = client.create_correspondent("X", matching_algorithm="none")

        # Assert
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

            # Act
            result = client.create_document_type("Y", matching_algorithm=0)

        # Assert
        assert result == {"id": 2, "name": "Y"}
        client.close()

    def test_passes_matching_algorithm_none_correctly(self):
        # Arrange
        with respx.mock:
            route = respx.post(f"{BASE}/api/tags/")
            route.mock(return_value=httpx.Response(201, json={"id": 5, "name": "Z"}))
            client = _make_client()

            # Act
            result = client.create_tag("Z", matching_algorithm=None)

        # Assert
        body = json_mod.loads(route.calls[0].request.content)
        assert "matching_algorithm" not in body
        assert result == {"id": 5, "name": "Z"}
        client.close()

    def test_raises_on_non_400_error(self):
        # Arrange
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


# ---------------------------------------------------------------------------
# Retry behavior
# ---------------------------------------------------------------------------

class TestRetryBehavior:
    def test_retries_on_network_error(self):
        # Arrange
        with respx.mock:
            route = respx.get(f"{BASE}/api/documents/1/")
            route.side_effect = [
                httpx.ConnectError("conn refused"),
                httpx.Response(200, json={"id": 1}),
            ]
            client = _make_client()

            # Act
            result = client.get_document(1)

        # Assert
        assert result == {"id": 1}
        assert route.call_count == 2
        client.close()

    def test_retries_on_5xx_server_error(self):
        # Arrange
        with respx.mock:
            route = respx.get(f"{BASE}/api/documents/1/")
            route.side_effect = [
                httpx.Response(503),
                httpx.Response(200, json={"id": 1}),
            ]
            client = _make_client()

            # Act
            result = client.get_document(1)

        # Assert
        assert result == {"id": 1}
        client.close()

    def test_does_not_retry_on_4xx_client_error(self):
        # Arrange
        with respx.mock:
            route = respx.get(f"{BASE}/api/documents/1/")
            route.mock(return_value=httpx.Response(404))
            client = _make_client()

            # Act / Assert
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                client.get_document(1)
            assert exc_info.value.response.status_code == 404
            assert route.call_count == 1
        client.close()

    def test_raises_after_max_retries_exhausted(self):
        # Arrange — all 3 attempts fail
        with respx.mock:
            route = respx.get(f"{BASE}/api/documents/1/")
            route.side_effect = [
                httpx.ConnectError("fail1"),
                httpx.ConnectError("fail2"),
                httpx.ConnectError("fail3"),
            ]
            client = _make_client()

            # Act / Assert
            with pytest.raises(httpx.ConnectError):
                client.get_document(1)
            assert route.call_count == 3
        client.close()


# ---------------------------------------------------------------------------
# ping
# ---------------------------------------------------------------------------

class TestPing:
    def test_single_request_without_retry(self):
        # Arrange
        with respx.mock:
            route = respx.get(f"{BASE}/api/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()

            # Act
            client.ping()

        # Assert
        assert route.call_count == 1
        client.close()

    def test_raises_on_failure(self):
        # Arrange
        with respx.mock:
            respx.get(f"{BASE}/api/").mock(
                return_value=httpx.Response(500),
            )
            client = _make_client()

            # Act / Assert
            with pytest.raises(httpx.HTTPStatusError):
                client.ping()
        client.close()


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

class TestGetDocumentsToProcess:
    def test_delegates_to_get_documents_by_tag_with_pre_tag_id(self):
        # Arrange
        settings = _make_settings(PRE_TAG_ID=443)
        url = f"{BASE}/api/documents/?tags__id=443&page_size=100"
        with respx.mock:
            respx.get(url__eq=url).mock(return_value=httpx.Response(200, json={
                "results": [{"id": 7}], "next": None,
            }))
            client = _make_client(settings)

            # Act
            results = list(client.get_documents_to_process())

        # Assert
        assert results == [{"id": 7}]
        client.close()


class TestUpdateDocumentMetadataAllFields:
    """Test that each individual metadata field is included when provided."""

    def test_correspondent_id_sent_as_correspondent(self):
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/1/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()
            client.update_document_metadata(1, correspondent_id=42)
        body = json_mod.loads(route.calls[0].request.content)
        assert body["correspondent"] == 42
        client.close()

    def test_document_type_id_sent_as_document_type(self):
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/1/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()
            client.update_document_metadata(1, document_type_id=7)
        body = json_mod.loads(route.calls[0].request.content)
        assert body["document_type"] == 7
        client.close()

    def test_document_date_sent_as_created(self):
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/1/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()
            client.update_document_metadata(1, document_date="2025-01-15")
        body = json_mod.loads(route.calls[0].request.content)
        assert body["created"] == "2025-01-15"
        client.close()

    def test_language_sent(self):
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/1/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()
            client.update_document_metadata(1, language="en")
        body = json_mod.loads(route.calls[0].request.content)
        assert body["language"] == "en"
        client.close()

    def test_custom_fields_sent(self):
        with respx.mock:
            route = respx.patch(f"{BASE}/api/documents/1/").mock(
                return_value=httpx.Response(200, json={}),
            )
            client = _make_client()
            fields = [{"field": 5, "value": "test"}]
            client.update_document_metadata(1, custom_fields=fields)
        body = json_mod.loads(route.calls[0].request.content)
        assert body["custom_fields"] == [{"field": 5, "value": "test"}]
        client.close()


class TestCreateNamedItemUnexpectedType:
    """matching_algorithm of unexpected type uses single-element candidates."""

    def test_unexpected_type_used_directly(self):
        with respx.mock:
            route = respx.post(f"{BASE}/api/tags/")
            route.mock(return_value=httpx.Response(201, json={"id": 5, "name": "Z"}))
            client = _make_client()
            client.create_tag("Z", matching_algorithm=3.14)
        body = json_mod.loads(route.calls[0].request.content)
        assert body["matching_algorithm"] == 3.14
        client.close()


class TestCreateNamedItemNon400Reraise:
    """Non-400 HTTP errors during creation are re-raised."""

    def test_422_error_raised_immediately(self):
        with respx.mock:
            route = respx.post(f"{BASE}/api/tags/")
            route.mock(return_value=httpx.Response(422))
            client = _make_client()
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                client.create_tag("fail", matching_algorithm="none")
            assert exc_info.value.response.status_code == 422
        client.close()


class TestClose:
    def test_closes_underlying_httpx_client(self):
        # Arrange
        client = _make_client()

        # Act
        client.close()

        # Assert — httpx.Client is closed; subsequent requests would fail
        assert client._client.is_closed
