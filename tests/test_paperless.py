import os

import pytest
import requests
import requests_mock

from common.config import Settings
from common.paperless import PaperlessClient


@pytest.fixture
def settings(mocker):
    """Fixture to create a Settings object for tests."""
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "PRE_TAG_ID": "10",
            "POST_TAG_ID": "11",
            "MAX_RETRIES": "3",
        },
        clear=True,
    )
    return Settings()


@pytest.fixture
def paperless_client(settings):
    """Fixture to create a PaperlessClient instance."""
    return PaperlessClient(settings)


def test_get_documents_to_process(paperless_client, settings, requests_mock):
    """
    Test that the client correctly fetches all documents with the pre-OCR tag.
    """
    # Mock the paginated API response
    # Page 1
    requests_mock.get(
        f"{settings.PAPERLESS_URL}/api/documents/?tags__id=10&page_size=100",
        json={
            "next": f"{settings.PAPERLESS_URL}/api/documents/page2",
            "results": [
                {"id": 1, "tags": [10]},
                {"id": 2, "tags": [10, 11]},
            ],
        },
    )
    # Page 2
    requests_mock.get(
        f"{settings.PAPERLESS_URL}/api/documents/page2",
        json={
            "next": None,
            "results": [
                {"id": 3, "tags": [10]},
            ],
        },
    )

    docs = list(paperless_client.get_documents_to_process())

    assert len(docs) == 3
    assert [d["id"] for d in docs] == [1, 2, 3]


def test_download_content(paperless_client, settings, requests_mock):
    """
    Test that file content is correctly downloaded.
    """
    doc_id = 1
    file_content = b"This is a test PDF."
    requests_mock.get(
        f"{settings.PAPERLESS_URL}/api/documents/{doc_id}/download/",
        content=file_content,
        headers={"Content-Type": "application/pdf"},
    )

    content, content_type = paperless_client.download_content(doc_id)

    assert content_type == "application/pdf"
    assert content == file_content


def test_download_content_defaults_content_type(paperless_client, settings, requests_mock):
    """
    Test that the content type defaults when not provided by the server.
    """
    doc_id = 2
    file_content = b"binary data"
    requests_mock.get(
        f"{settings.PAPERLESS_URL}/api/documents/{doc_id}/download/",
        content=file_content,
        headers={},
    )

    content, content_type = paperless_client.download_content(doc_id)

    assert content_type == "application/pdf"
    assert content == file_content


def test_update_document(paperless_client, settings, requests_mock):
    """
    Test that a document is correctly updated with new content and tags.
    """
    doc_id = 1
    new_content = "This is the OCR text."
    new_tags = [11, 12]

    # Mock the PATCH request and check the payload
    mock_patch = requests_mock.patch(
        f"{settings.PAPERLESS_URL}/api/documents/{doc_id}/", status_code=200
    )

    paperless_client.update_document(doc_id, new_content, new_tags)

    assert mock_patch.called
    assert mock_patch.last_request.json() == {
        "content": new_content,
        "tags": new_tags,
    }


def test_get_document(paperless_client, settings, requests_mock):
    """
    Test that a single document can be fetched.
    """
    doc_id = 42
    requests_mock.get(
        f"{settings.PAPERLESS_URL}/api/documents/{doc_id}/",
        json={"id": doc_id, "content": "text"},
    )

    doc = paperless_client.get_document(doc_id)

    assert doc["id"] == doc_id


def test_list_tags(paperless_client, settings, requests_mock):
    """
    Test listing tags from Paperless.
    """
    requests_mock.get(
        f"{settings.PAPERLESS_URL}/api/tags/?page_size=100",
        json={"next": None, "results": [{"id": 1, "name": "Bills"}]},
    )

    tags = paperless_client.list_tags()

    assert tags == [{"id": 1, "name": "Bills"}]


def test_create_tag(paperless_client, settings, requests_mock):
    """
    Test creating a tag in Paperless.
    """
    mock_post = requests_mock.post(
        f"{settings.PAPERLESS_URL}/api/tags/",
        json={"id": 9, "name": "NewTag"},
        status_code=201,
    )

    created = paperless_client.create_tag("NewTag")

    assert created["id"] == 9
    assert created["name"] == "NewTag"
    assert mock_post.last_request.json() == {
        "name": "NewTag",
        "matching_algorithm": "none",
    }


def test_create_correspondent(paperless_client, settings, requests_mock):
    """
    Test creating a correspondent in Paperless.
    """
    mock_post = requests_mock.post(
        f"{settings.PAPERLESS_URL}/api/correspondents/",
        json={"id": 3, "name": "NewCorr"},
        status_code=201,
    )

    created = paperless_client.create_correspondent("NewCorr")

    assert created["id"] == 3
    assert created["name"] == "NewCorr"
    assert mock_post.last_request.json() == {
        "name": "NewCorr",
        "matching_algorithm": "none",
    }


def test_create_document_type(paperless_client, settings, requests_mock):
    """
    Test creating a document type in Paperless.
    """
    mock_post = requests_mock.post(
        f"{settings.PAPERLESS_URL}/api/document_types/",
        json={"id": 4, "name": "NewType"},
        status_code=201,
    )

    created = paperless_client.create_document_type("NewType")

    assert created["id"] == 4
    assert created["name"] == "NewType"
    assert mock_post.last_request.json() == {
        "name": "NewType",
        "matching_algorithm": "none",
    }


def test_update_document_metadata(paperless_client, settings, requests_mock):
    """
    Test metadata updates with a PATCH payload.
    """
    doc_id = 3
    mock_patch = requests_mock.patch(
        f"{settings.PAPERLESS_URL}/api/documents/{doc_id}/", status_code=200
    )

    paperless_client.update_document_metadata(
        doc_id,
        title="Title",
        correspondent_id=1,
        document_type_id=2,
        document_date="2025-05-01",
        tags=[1, 2],
        language="en",
        custom_fields=[{"field": 7, "value": "Person"}],
    )

    assert mock_patch.called
    assert mock_patch.last_request.json() == {
        "title": "Title",
        "correspondent": 1,
        "document_type": 2,
        "created": "2025-05-01",
        "tags": [1, 2],
        "language": "en",
        "custom_fields": [{"field": 7, "value": "Person"}],
    }

def test_retry_on_network_error(paperless_client, settings, requests_mock):
    """
    Test that the client retries on a transient network error.
    """
    url = f"{settings.PAPERLESS_URL}/api/documents/?tags__id=10&page_size=100"
    requests_mock.get(
        url,
        [
            {"exc": requests.exceptions.ConnectionError},
            {"exc": requests.exceptions.Timeout},
            {"json": {"next": None, "results": [{"id": 1, "tags": [10]}]}},
        ],
    )

    # The call should succeed on the third attempt
    docs = list(paperless_client.get_documents_to_process())
    assert len(docs) == 1
    assert requests_mock.call_count == 3


def test_retry_fails_after_max_retries(paperless_client, settings, requests_mock):
    """
    Test that the client gives up after exhausting all retries.
    """
    url = f"{settings.PAPERLESS_URL}/api/documents/?tags__id=10&page_size=100"
    requests_mock.get(url, exc=requests.exceptions.ConnectionError)

    with pytest.raises(requests.exceptions.ConnectionError):
        list(paperless_client.get_documents_to_process())

    assert requests_mock.call_count == settings.MAX_RETRIES


def test_retry_on_server_error(paperless_client, settings, requests_mock):
    """
    Test that 5xx responses trigger retries.
    """
    url = f"{settings.PAPERLESS_URL}/api/documents/?tags__id=10&page_size=100"
    requests_mock.get(
        url,
        [
            {"status_code": 502, "json": {"detail": "Bad Gateway"}},
            {"json": {"next": None, "results": [{"id": 1, "tags": [10]}]}},
        ],
    )

    docs = list(paperless_client.get_documents_to_process())

    assert len(docs) == 1
    assert requests_mock.call_count == 2


def test_no_retry_on_client_error(paperless_client, settings, requests_mock):
    """
    Test that 4xx responses do not trigger retries.
    """
    url = f"{settings.PAPERLESS_URL}/api/documents/?tags__id=10&page_size=100"
    requests_mock.get(url, status_code=404, json={"detail": "Not found"})

    with pytest.raises(requests.exceptions.HTTPError):
        list(paperless_client.get_documents_to_process())

    assert requests_mock.call_count == 1


def test_create_tag_string_fallback_on_400(paperless_client, settings, requests_mock):
    """
    Test that _create_named_item falls back from a string matching_algorithm
    to int 0 when the first attempt returns a 400 error.
    Covers lines 104-107 (str branch: candidates = [matching_algorithm, 0])
    and lines 117-121 (HTTPError catch with fallback).
    """
    url = f"{settings.PAPERLESS_URL}/api/tags/"
    mock_post = requests_mock.post(
        url,
        [
            {"status_code": 400, "json": {"matching_algorithm": ["Invalid value."]}},
            {"status_code": 201, "json": {"id": 15, "name": "FallbackTag"}},
        ],
    )

    created = paperless_client.create_tag("FallbackTag", matching_algorithm="none")

    assert created["id"] == 15
    assert created["name"] == "FallbackTag"
    assert mock_post.call_count == 2
    # First attempt uses the string value
    assert mock_post.request_history[0].json() == {
        "name": "FallbackTag",
        "matching_algorithm": "none",
    }
    # Second attempt falls back to int 0
    assert mock_post.request_history[1].json() == {
        "name": "FallbackTag",
        "matching_algorithm": 0,
    }


def test_create_tag_int_fallback_on_400(paperless_client, settings, requests_mock):
    """
    Test that _create_named_item falls back from an int matching_algorithm
    to string "none" when the first attempt returns a 400 error.
    Covers lines 104-105 (int branch: candidates = [matching_algorithm, "none"]).
    """
    url = f"{settings.PAPERLESS_URL}/api/tags/"
    mock_post = requests_mock.post(
        url,
        [
            {"status_code": 400, "json": {"matching_algorithm": ["Invalid value."]}},
            {"status_code": 201, "json": {"id": 16, "name": "IntFallback"}},
        ],
    )

    created = paperless_client.create_tag("IntFallback", matching_algorithm=0)

    assert created["id"] == 16
    assert created["name"] == "IntFallback"
    assert mock_post.call_count == 2
    # First attempt uses the int value
    assert mock_post.request_history[0].json() == {
        "name": "IntFallback",
        "matching_algorithm": 0,
    }
    # Second attempt falls back to string "none"
    assert mock_post.request_history[1].json() == {
        "name": "IntFallback",
        "matching_algorithm": "none",
    }


def test_create_tag_matching_algorithm_none(paperless_client, settings, requests_mock):
    """
    Test that _create_named_item with matching_algorithm=None sends a payload
    without matching_algorithm and does not retry on 400.
    Covers line 101 (candidates = [None]).
    """
    url = f"{settings.PAPERLESS_URL}/api/tags/"
    mock_post = requests_mock.post(
        url,
        json={"id": 20, "name": "NoAlgo"},
        status_code=201,
    )

    created = paperless_client.create_tag("NoAlgo", matching_algorithm=None)

    assert created["id"] == 20
    assert created["name"] == "NoAlgo"
    assert mock_post.last_request.json() == {"name": "NoAlgo"}


def test_create_tag_matching_algorithm_none_raises_on_400(
    paperless_client, settings, requests_mock
):
    """
    Test that _create_named_item with matching_algorithm=None raises HTTPError
    on a 400 because there is only one candidate and no fallback.
    Covers lines 117-121 (raise path when index == len(candidates) - 1).
    """
    url = f"{settings.PAPERLESS_URL}/api/tags/"
    requests_mock.post(
        url,
        status_code=400,
        json={"name": ["Tag with this name already exists."]},
    )

    with pytest.raises(requests.exceptions.HTTPError):
        paperless_client.create_tag("Duplicate", matching_algorithm=None)


def test_create_tag_unexpected_type_matching_algorithm(
    paperless_client, settings, requests_mock
):
    """
    Test that _create_named_item with an unexpected type for matching_algorithm
    (e.g., a float) uses candidates = [matching_algorithm] and sends it as-is.
    Covers lines 106-107 (else branch: candidates = [matching_algorithm]).
    """
    url = f"{settings.PAPERLESS_URL}/api/tags/"
    mock_post = requests_mock.post(
        url,
        json={"id": 25, "name": "WeirdAlgo"},
        status_code=201,
    )

    created = paperless_client.create_tag("WeirdAlgo", matching_algorithm=3.14)

    assert created["id"] == 25
    assert created["name"] == "WeirdAlgo"
    assert mock_post.last_request.json() == {
        "name": "WeirdAlgo",
        "matching_algorithm": 3.14,
    }


def test_create_tag_unexpected_type_raises_on_400(
    paperless_client, settings, requests_mock
):
    """
    Test that _create_named_item with an unexpected type raises on 400
    since there is only one candidate and no fallback.
    Covers lines 106-107 and 117-119 (else branch + raise on last candidate).
    """
    url = f"{settings.PAPERLESS_URL}/api/tags/"
    requests_mock.post(
        url,
        status_code=400,
        json={"matching_algorithm": ["Invalid value."]},
    )

    with pytest.raises(requests.exceptions.HTTPError):
        paperless_client.create_tag("BadAlgo", matching_algorithm=3.14)


def test_update_document_metadata_empty_payload(
    paperless_client, settings, requests_mock
):
    """
    Test that update_document_metadata returns early without making any
    HTTP request when no metadata fields are provided.
    Covers lines 216-217 (empty payload early return).
    """
    doc_id = 5
    mock_patch = requests_mock.patch(
        f"{settings.PAPERLESS_URL}/api/documents/{doc_id}/", status_code=200
    )

    # Call with all defaults (no metadata to update)
    paperless_client.update_document_metadata(doc_id)

    assert not mock_patch.called


def test_list_correspondents(paperless_client, settings, requests_mock):
    """
    Test listing correspondents from Paperless.
    Covers lines 229-231 (list_correspondents endpoint).
    """
    requests_mock.get(
        f"{settings.PAPERLESS_URL}/api/correspondents/?page_size=100",
        json={
            "next": None,
            "results": [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ],
        },
    )

    correspondents = paperless_client.list_correspondents()

    assert correspondents == [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]


def test_list_document_types(paperless_client, settings, requests_mock):
    """
    Test listing document types from Paperless.
    Covers lines 237-239 (list_document_types endpoint).
    """
    requests_mock.get(
        f"{settings.PAPERLESS_URL}/api/document_types/?page_size=100",
        json={
            "next": None,
            "results": [
                {"id": 1, "name": "Invoice"},
                {"id": 2, "name": "Receipt"},
            ],
        },
    )

    doc_types = paperless_client.list_document_types()

    assert doc_types == [
        {"id": 1, "name": "Invoice"},
        {"id": 2, "name": "Receipt"},
    ]


def test_close(paperless_client, mocker):
    """
    Test that close() calls the underlying session's close method.
    Covers line 291 (close method).
    """
    spy = mocker.spy(paperless_client._session, "close")

    paperless_client.close()

    spy.assert_called_once()
