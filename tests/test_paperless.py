import json
import os

import httpx
import pytest
import respx

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
    client = PaperlessClient(settings)
    yield client
    client.close()


@respx.mock
def test_get_documents_to_process(paperless_client, settings):
    """
    Test that the client correctly fetches all documents with the pre-OCR tag.
    """
    # Page 1
    respx.get(
        f"{settings.PAPERLESS_URL}/api/documents/?tags__id=10&page_size=100"
    ).mock(return_value=httpx.Response(200, json={
        "next": f"{settings.PAPERLESS_URL}/api/documents/page2",
        "results": [
            {"id": 1, "tags": [10]},
            {"id": 2, "tags": [10, 11]},
        ],
    }))
    # Page 2
    respx.get(
        f"{settings.PAPERLESS_URL}/api/documents/page2"
    ).mock(return_value=httpx.Response(200, json={
        "next": None,
        "results": [
            {"id": 3, "tags": [10]},
        ],
    }))

    docs = list(paperless_client.get_documents_to_process())

    assert len(docs) == 3
    assert [d["id"] for d in docs] == [1, 2, 3]


@respx.mock
def test_download_content(paperless_client, settings):
    """
    Test that file content is correctly downloaded.
    """
    doc_id = 1
    file_content = b"This is a test PDF."
    respx.get(
        f"{settings.PAPERLESS_URL}/api/documents/{doc_id}/download/"
    ).mock(return_value=httpx.Response(
        200,
        content=file_content,
        headers={"Content-Type": "application/pdf"},
    ))

    content, content_type = paperless_client.download_content(doc_id)

    assert content_type == "application/pdf"
    assert content == file_content


@respx.mock
def test_download_content_defaults_content_type(paperless_client, settings):
    """
    Test that the content type defaults when not provided by the server.
    """
    doc_id = 2
    file_content = b"binary data"
    respx.get(
        f"{settings.PAPERLESS_URL}/api/documents/{doc_id}/download/"
    ).mock(return_value=httpx.Response(200, content=file_content))

    content, content_type = paperless_client.download_content(doc_id)

    assert content_type == "application/pdf"
    assert content == file_content


@respx.mock
def test_update_document(paperless_client, settings):
    """
    Test that a document is correctly updated with new content and tags.
    """
    doc_id = 1
    new_content = "This is the OCR text."
    new_tags = [11, 12]

    route = respx.patch(
        f"{settings.PAPERLESS_URL}/api/documents/{doc_id}/"
    ).mock(return_value=httpx.Response(200))

    paperless_client.update_document(doc_id, new_content, new_tags)

    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"content": new_content, "tags": new_tags}


@respx.mock
def test_get_document(paperless_client, settings):
    """
    Test that a single document can be fetched.
    """
    doc_id = 42
    respx.get(
        f"{settings.PAPERLESS_URL}/api/documents/{doc_id}/"
    ).mock(return_value=httpx.Response(200, json={"id": doc_id, "content": "text"}))

    doc = paperless_client.get_document(doc_id)

    assert doc["id"] == doc_id


@respx.mock
def test_list_tags(paperless_client, settings):
    """
    Test listing tags from Paperless.
    """
    respx.get(
        f"{settings.PAPERLESS_URL}/api/tags/?page_size=100"
    ).mock(return_value=httpx.Response(200, json={
        "next": None,
        "results": [{"id": 1, "name": "Bills"}],
    }))

    tags = paperless_client.list_tags()

    assert tags == [{"id": 1, "name": "Bills"}]


@respx.mock
def test_create_tag(paperless_client, settings):
    """
    Test creating a tag in Paperless.
    """
    route = respx.post(
        f"{settings.PAPERLESS_URL}/api/tags/"
    ).mock(return_value=httpx.Response(201, json={"id": 9, "name": "NewTag"}))

    created = paperless_client.create_tag("NewTag")

    assert created["id"] == 9
    assert created["name"] == "NewTag"
    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "NewTag", "matching_algorithm": "none"}


@respx.mock
def test_create_correspondent(paperless_client, settings):
    """
    Test creating a correspondent in Paperless.
    """
    route = respx.post(
        f"{settings.PAPERLESS_URL}/api/correspondents/"
    ).mock(return_value=httpx.Response(201, json={"id": 3, "name": "NewCorr"}))

    created = paperless_client.create_correspondent("NewCorr")

    assert created["id"] == 3
    assert created["name"] == "NewCorr"
    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "NewCorr", "matching_algorithm": "none"}


@respx.mock
def test_create_document_type(paperless_client, settings):
    """
    Test creating a document type in Paperless.
    """
    route = respx.post(
        f"{settings.PAPERLESS_URL}/api/document_types/"
    ).mock(return_value=httpx.Response(201, json={"id": 4, "name": "NewType"}))

    created = paperless_client.create_document_type("NewType")

    assert created["id"] == 4
    assert created["name"] == "NewType"
    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "NewType", "matching_algorithm": "none"}


@respx.mock
def test_update_document_metadata(paperless_client, settings):
    """
    Test metadata updates with a PATCH payload.
    """
    doc_id = 3
    route = respx.patch(
        f"{settings.PAPERLESS_URL}/api/documents/{doc_id}/"
    ).mock(return_value=httpx.Response(200))

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

    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "title": "Title",
        "correspondent": 1,
        "document_type": 2,
        "created": "2025-05-01",
        "tags": [1, 2],
        "language": "en",
        "custom_fields": [{"field": 7, "value": "Person"}],
    }


@respx.mock
def test_retry_on_network_error(paperless_client, settings):
    """
    Test that the client retries on a transient network error.
    """
    url = f"{settings.PAPERLESS_URL}/api/documents/?tags__id=10&page_size=100"
    route = respx.get(url).mock(side_effect=[
        httpx.ConnectError("connection refused"),
        httpx.TimeoutException("timed out"),
        httpx.Response(200, json={"next": None, "results": [{"id": 1, "tags": [10]}]}),
    ])

    docs = list(paperless_client.get_documents_to_process())
    assert len(docs) == 1
    assert route.call_count == 3


@respx.mock
def test_retry_fails_after_max_retries(paperless_client, settings):
    """
    Test that the client gives up after exhausting all retries.
    """
    url = f"{settings.PAPERLESS_URL}/api/documents/?tags__id=10&page_size=100"
    route = respx.get(url).mock(side_effect=httpx.ConnectError("connection refused"))

    with pytest.raises(httpx.ConnectError):
        list(paperless_client.get_documents_to_process())

    assert route.call_count == settings.MAX_RETRIES


@respx.mock
def test_retry_on_server_error(paperless_client, settings):
    """
    Test that 5xx responses trigger retries.
    """
    url = f"{settings.PAPERLESS_URL}/api/documents/?tags__id=10&page_size=100"
    route = respx.get(url).mock(side_effect=[
        httpx.Response(502, json={"detail": "Bad Gateway"}),
        httpx.Response(200, json={"next": None, "results": [{"id": 1, "tags": [10]}]}),
    ])

    docs = list(paperless_client.get_documents_to_process())

    assert len(docs) == 1
    assert route.call_count == 2


@respx.mock
def test_no_retry_on_client_error(paperless_client, settings):
    """
    Test that 4xx responses do not trigger retries.
    """
    url = f"{settings.PAPERLESS_URL}/api/documents/?tags__id=10&page_size=100"
    route = respx.get(url).mock(return_value=httpx.Response(404, json={"detail": "Not found"}))

    with pytest.raises(httpx.HTTPStatusError):
        list(paperless_client.get_documents_to_process())

    assert route.call_count == 1


@respx.mock
def test_create_tag_string_fallback_on_400(paperless_client, settings):
    """
    Test that _create_named_item falls back from a string matching_algorithm
    to int 0 when the first attempt returns a 400 error.
    """
    url = f"{settings.PAPERLESS_URL}/api/tags/"
    route = respx.post(url).mock(side_effect=[
        httpx.Response(400, json={"matching_algorithm": ["Invalid value."]}),
        httpx.Response(201, json={"id": 15, "name": "FallbackTag"}),
    ])

    created = paperless_client.create_tag("FallbackTag", matching_algorithm="none")

    assert created["id"] == 15
    assert created["name"] == "FallbackTag"
    assert route.call_count == 2
    body1 = json.loads(route.calls[0].request.content)
    body2 = json.loads(route.calls[1].request.content)
    assert body1 == {"name": "FallbackTag", "matching_algorithm": "none"}
    assert body2 == {"name": "FallbackTag", "matching_algorithm": 0}


@respx.mock
def test_create_tag_int_fallback_on_400(paperless_client, settings):
    """
    Test that _create_named_item falls back from an int matching_algorithm
    to string "none" when the first attempt returns a 400 error.
    """
    url = f"{settings.PAPERLESS_URL}/api/tags/"
    route = respx.post(url).mock(side_effect=[
        httpx.Response(400, json={"matching_algorithm": ["Invalid value."]}),
        httpx.Response(201, json={"id": 16, "name": "IntFallback"}),
    ])

    created = paperless_client.create_tag("IntFallback", matching_algorithm=0)

    assert created["id"] == 16
    assert created["name"] == "IntFallback"
    assert route.call_count == 2
    body1 = json.loads(route.calls[0].request.content)
    body2 = json.loads(route.calls[1].request.content)
    assert body1 == {"name": "IntFallback", "matching_algorithm": 0}
    assert body2 == {"name": "IntFallback", "matching_algorithm": "none"}


@respx.mock
def test_create_tag_matching_algorithm_none(paperless_client, settings):
    """
    Test that _create_named_item with matching_algorithm=None sends a payload
    without matching_algorithm and does not retry on 400.
    """
    url = f"{settings.PAPERLESS_URL}/api/tags/"
    route = respx.post(url).mock(
        return_value=httpx.Response(201, json={"id": 20, "name": "NoAlgo"})
    )

    created = paperless_client.create_tag("NoAlgo", matching_algorithm=None)

    assert created["id"] == 20
    assert created["name"] == "NoAlgo"
    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "NoAlgo"}


@respx.mock
def test_create_tag_matching_algorithm_none_raises_on_400(
    paperless_client, settings
):
    """
    Test that _create_named_item with matching_algorithm=None raises HTTPStatusError
    on a 400 because there is only one candidate and no fallback.
    """
    url = f"{settings.PAPERLESS_URL}/api/tags/"
    respx.post(url).mock(return_value=httpx.Response(
        400, json={"name": ["Tag with this name already exists."]}
    ))

    with pytest.raises(httpx.HTTPStatusError):
        paperless_client.create_tag("Duplicate", matching_algorithm=None)


@respx.mock
def test_create_tag_unexpected_type_matching_algorithm(
    paperless_client, settings
):
    """
    Test that _create_named_item with an unexpected type for matching_algorithm
    (e.g., a float) uses candidates = [matching_algorithm] and sends it as-is.
    """
    url = f"{settings.PAPERLESS_URL}/api/tags/"
    route = respx.post(url).mock(
        return_value=httpx.Response(201, json={"id": 25, "name": "WeirdAlgo"})
    )

    created = paperless_client.create_tag("WeirdAlgo", matching_algorithm=3.14)

    assert created["id"] == 25
    assert created["name"] == "WeirdAlgo"
    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "WeirdAlgo", "matching_algorithm": 3.14}


@respx.mock
def test_create_tag_unexpected_type_raises_on_400(
    paperless_client, settings
):
    """
    Test that _create_named_item with an unexpected type raises on 400
    since there is only one candidate and no fallback.
    """
    url = f"{settings.PAPERLESS_URL}/api/tags/"
    respx.post(url).mock(return_value=httpx.Response(
        400, json={"matching_algorithm": ["Invalid value."]}
    ))

    with pytest.raises(httpx.HTTPStatusError):
        paperless_client.create_tag("BadAlgo", matching_algorithm=3.14)


@respx.mock
def test_update_document_metadata_empty_payload(
    paperless_client, settings
):
    """
    Test that update_document_metadata returns early without making any
    HTTP request when no metadata fields are provided.
    """
    doc_id = 5
    route = respx.patch(
        f"{settings.PAPERLESS_URL}/api/documents/{doc_id}/"
    ).mock(return_value=httpx.Response(200))

    paperless_client.update_document_metadata(doc_id)

    assert not route.called


@respx.mock
def test_list_correspondents(paperless_client, settings):
    """
    Test listing correspondents from Paperless.
    """
    respx.get(
        f"{settings.PAPERLESS_URL}/api/correspondents/?page_size=100"
    ).mock(return_value=httpx.Response(200, json={
        "next": None,
        "results": [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ],
    }))

    correspondents = paperless_client.list_correspondents()

    assert correspondents == [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]


@respx.mock
def test_list_document_types(paperless_client, settings):
    """
    Test listing document types from Paperless.
    """
    respx.get(
        f"{settings.PAPERLESS_URL}/api/document_types/?page_size=100"
    ).mock(return_value=httpx.Response(200, json={
        "next": None,
        "results": [
            {"id": 1, "name": "Invoice"},
            {"id": 2, "name": "Receipt"},
        ],
    }))

    doc_types = paperless_client.list_document_types()

    assert doc_types == [
        {"id": 1, "name": "Invoice"},
        {"id": 2, "name": "Receipt"},
    ]


def test_close(paperless_client, mocker):
    """
    Test that close() calls the underlying client's close method.
    """
    spy = mocker.spy(paperless_client._client, "close")

    paperless_client.close()

    spy.assert_called_once()
