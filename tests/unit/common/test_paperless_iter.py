"""Tests for common.paperless — iter_all_documents, document_exists, and
create-named-item edge cases.

Split from test_paperless.py to stay within the §3.1 500-line ceiling.
The shared _make_client / _make_settings helpers and the _ClientRegistry
autouse fixture are duplicated here so each file is self-contained and can
run in isolation without import coupling between test modules.
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
        MAX_RETRY_BACKOFF_SECONDS=0,
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


class TestIterAllDocuments:
    def test_yields_every_document_across_multiple_pages(self):
        """iter_all_documents pages through all results and yields each document."""
        url1 = f"{BASE}/api/documents/?ordering=modified&page_size=100"
        url2 = f"{BASE}/api/documents/?ordering=modified&page_size=100&page=2"
        with respx.mock:
            respx.get(url__eq=url1).mock(return_value=httpx.Response(200, json={
                "results": [{"id": 1, "modified": "2024-01-01T00:00:00Z"},
                             {"id": 2, "modified": "2024-01-02T00:00:00Z"}],
                "next": url2,
            }))
            respx.get(url__eq=url2).mock(return_value=httpx.Response(200, json={
                "results": [{"id": 3, "modified": "2024-01-03T00:00:00Z"}],
                "next": None,
            }))
            client = _make_client()

            documents = list(client.iter_all_documents())

        assert [d["id"] for d in documents] == [1, 2, 3]
        client.close()

    def test_passes_modified_after_as_modified_gt_filter(self):
        """Passing modified_after adds the modified__gt query parameter."""
        url = f"{BASE}/api/documents/?ordering=modified&page_size=100&modified__gt=2024-06-01T00%3A00%3A00Z"
        with respx.mock:
            respx.get(url__eq=url).mock(return_value=httpx.Response(200, json={
                "results": [{"id": 5, "modified": "2024-06-02T00:00:00Z"}],
                "next": None,
            }))
            client = _make_client()

            documents = list(client.iter_all_documents(modified_after="2024-06-01T00:00:00Z"))

        assert documents == [{"id": 5, "modified": "2024-06-02T00:00:00Z"}]
        client.close()

    def test_yields_nothing_when_results_are_empty(self):
        """iter_all_documents produces no items when Paperless returns an empty list."""
        url = f"{BASE}/api/documents/?ordering=modified&page_size=100"
        with respx.mock:
            respx.get(url__eq=url).mock(return_value=httpx.Response(200, json={
                "results": [],
                "next": None,
            }))
            client = _make_client()

            documents = list(client.iter_all_documents())

        assert documents == []
        client.close()

    def test_returns_documents_in_modified_order(self):
        """Results come back in the order Paperless returns them (ordered by modified)."""
        url = f"{BASE}/api/documents/?ordering=modified&page_size=100"
        with respx.mock:
            respx.get(url__eq=url).mock(return_value=httpx.Response(200, json={
                "results": [
                    {"id": 10, "modified": "2024-01-01T00:00:00Z"},
                    {"id": 20, "modified": "2024-02-01T00:00:00Z"},
                ],
                "next": None,
            }))
            client = _make_client()

            documents = list(client.iter_all_documents())

        assert documents[0]["id"] == 10
        assert documents[1]["id"] == 20
        client.close()


class TestDocumentExists:
    def test_returns_true_when_document_found(self):
        """document_exists returns True when Paperless returns HTTP 200."""
        with respx.mock:
            respx.get(f"{BASE}/api/documents/42/").mock(
                return_value=httpx.Response(200, json={"id": 42}),
            )
            client = _make_client()

            assert client.document_exists(42) is True
        client.close()

    def test_returns_false_when_document_not_found(self):
        """document_exists returns False when Paperless returns HTTP 404."""
        with respx.mock:
            respx.get(f"{BASE}/api/documents/99/").mock(
                return_value=httpx.Response(404),
            )
            client = _make_client()

            assert client.document_exists(99) is False
        client.close()

    def test_raises_on_server_error(self):
        """document_exists re-raises on 5xx after retries are exhausted."""
        with respx.mock:
            # Always return 500; after MAX_RETRIES attempts it should raise.
            respx.get(f"{BASE}/api/documents/7/").mock(
                return_value=httpx.Response(500),
            )
            client = _make_client()

            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                client.document_exists(7)
            assert exc_info.value.response.status_code == 500
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
