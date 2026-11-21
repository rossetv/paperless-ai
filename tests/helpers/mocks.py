"""Reusable mock builders."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from tests.helpers.factories import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    make_document,
    make_embedding,
    make_paperless_document,
    make_settings_obj,
)


def make_mock_embedding_client(
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
) -> MagicMock:
    """Create an EmbeddingClient mock whose ``embed`` gives one unit vector per text."""
    client = MagicMock()
    vector = list(make_embedding(dimensions))
    client.embed.side_effect = lambda texts: [list(vector) for _ in texts]
    return client


def make_mock_embeddings(
    *,
    n: int | None = None,
    dimensions: int = 4,
    vectors: list[list[float]] | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Create a mock OpenAI client whose embeddings.create returns predictable vectors.

    Supply *vectors* (one per input) or *n* (that many zero vectors). Successive
    calls consume the next slice, so a batched request split across calls keeps
    its order. Returns ``(mock_openai, dummy_response)``, where
    ``dummy_response`` is a standalone one-vector response object.
    """
    if vectors is not None:
        all_vectors = vectors
    elif n is not None:
        all_vectors = [[0.0] * dimensions for _ in range(n)]
    else:
        raise ValueError("Provide either vectors= or n= to make_mock_embeddings")

    position: list[int] = [0]

    last_response: list[MagicMock] = []

    def _create(*, model: str, input: list[str], **kwargs: Any) -> MagicMock:
        start = position[0]
        end = start + len(input)
        batch_vectors = all_vectors[start:end]
        position[0] = end

        response = MagicMock()
        response.data = [
            MagicMock(embedding=vec, index=i) for i, vec in enumerate(batch_vectors)
        ]
        last_response.clear()
        last_response.append(response)
        return response

    mock_openai = MagicMock()
    mock_openai.embeddings.create.side_effect = _create

    dummy_response = MagicMock()
    dummy_response.data = [MagicMock(embedding=[0.0] * dimensions, index=0)]
    return mock_openai, dummy_response


def make_mock_paperless(**overrides: Any) -> MagicMock:
    """Create a MagicMock that behaves like a PaperlessClient.

    ``get_document`` returns ``make_document()``, ``download_content`` returns
    dummy PDF bytes and the taxonomy list calls return empty lists.
    """
    mock = MagicMock()
    mock.settings = make_settings_obj()

    doc = make_document()
    mock.get_document.return_value = doc
    mock.get_documents_by_tag.return_value = [doc]
    mock.download_content.return_value = (b"fake-pdf-bytes", "application/pdf")
    mock.list_tags.return_value = []
    mock.list_correspondents.return_value = []
    mock.list_document_types.return_value = []
    mock.update_document.return_value = None
    mock.update_document_metadata.return_value = None
    mock.create_tag.side_effect = lambda name, **kw: {"id": 900, "name": name}
    mock.create_correspondent.side_effect = lambda name, **kw: {"id": 901, "name": name}
    mock.create_document_type.side_effect = lambda name, **kw: {"id": 902, "name": name}
    mock.ping.return_value = None
    mock.close.return_value = None

    for key, value in overrides.items():
        setattr(mock, key, value)

    return mock


def make_stateful_paperless(
    initial_doc: dict, *, with_taxonomy: bool = False
) -> tuple[MagicMock, dict[str, Any]]:
    """Create a mock PaperlessClient that tracks tag state across calls.

    Claiming the processing tag re-reads the document to verify the tag stuck,
    which a stateless mock would fail. Updates write ``state["tags"]`` and
    ``get_document`` reads it. *with_taxonomy* also stubs a fixed taxonomy.

    Returns:
        A ``(client, state)`` pair; ``state["tags"]`` is the live tag list.
    """
    client = MagicMock()
    state: dict[str, Any] = {
        "tags": list(initial_doc.get("tags", [])),
        "doc": dict(initial_doc),
    }

    def get_document(doc_id: int) -> dict:
        doc_copy = dict(state["doc"])
        doc_copy["tags"] = list(state["tags"])
        return doc_copy

    def update_document_metadata(doc_id: int, **kwargs: Any) -> None:
        if "tags" in kwargs:
            state["tags"] = list(kwargs["tags"])

    def update_document(doc_id: int, content: str, tags: Any) -> None:
        state["tags"] = list(tags)

    client.get_document.side_effect = get_document
    client.update_document_metadata.side_effect = update_document_metadata
    client.update_document.side_effect = update_document
    client.download_content.return_value = (b"fake", "application/pdf")

    if with_taxonomy:
        _stub_fixed_taxonomy(client)

    return client, state


def _stub_fixed_taxonomy(client: MagicMock) -> None:
    """Stub a fixed correspondent/document-type/tag taxonomy on *client*.

    The ids are pinned so the classifier workflow tests can assert exact
    resolution (correspondent ``Acme Corp`` → 1, document type ``Invoice`` →
    10).  Newly created items get monotonically increasing ids from 200.
    """
    client.list_correspondents.return_value = [
        {
            "id": 1,
            "name": "Acme Corp",
            "document_count": 10,
            "matching_algorithm": "none",
        },
    ]
    client.list_document_types.return_value = [
        {
            "id": 10,
            "name": "Invoice",
            "document_count": 20,
            "matching_algorithm": "none",
        },
        {
            "id": 11,
            "name": "Receipt",
            "document_count": 5,
            "matching_algorithm": "none",
        },
    ]
    client.list_tags.return_value = [
        {"id": 100, "name": "2025", "matching_algorithm": "none", "document_count": 30},
        {
            "id": 101,
            "name": "invoice",
            "matching_algorithm": "none",
            "document_count": 15,
        },
        {
            "id": 102,
            "name": "payment",
            "matching_algorithm": "none",
            "document_count": 8,
        },
        {"id": 103, "name": "de", "matching_algorithm": "none", "document_count": 25},
    ]

    next_id = [200]

    def create_tag(name: str, **kwargs: Any) -> dict:
        tag_id = next_id[0]
        next_id[0] += 1
        return {"id": tag_id, "name": name, "matching_algorithm": "none"}

    client.create_tag.side_effect = create_tag
    client.create_correspondent.side_effect = lambda name, **kw: {
        "id": 300,
        "name": name,
    }
    client.create_document_type.side_effect = lambda name, **kw: {
        "id": 301,
        "name": name,
    }


def make_mock_ocr_provider(**overrides: Any) -> MagicMock:
    """Create a MagicMock that behaves like an OcrProvider.

    ``transcribe_image`` returns a :class:`~ocr.text_assembly.PageResult` by
    default — the same shape the real provider yields, so the OCR worker and
    the e2e workflow tests share one provider mock.
    """
    from ocr.text_assembly import PageResult

    mock = MagicMock()
    mock.transcribe_image.return_value = PageResult(
        "Transcribed text for page.", "gpt-5.4-mini"
    )
    mock.get_stats.return_value = {
        "attempts": 1,
        "refusals": 0,
        "api_errors": 0,
        "fallback_successes": 0,
    }

    for key, value in overrides.items():
        setattr(mock, key, value)

    return mock


def make_mock_classify_provider(**overrides: Any) -> MagicMock:
    """Create a MagicMock that behaves like a ClassificationProvider."""
    from tests.helpers.factories import make_classification_result

    mock = MagicMock()
    mock.classify_text.return_value = (make_classification_result(), "gpt-5.4-mini")
    mock.get_stats.return_value = {
        "attempts": 1,
        "api_errors": 0,
        "invalid_json": 0,
        "fallback_successes": 0,
    }

    for key, value in overrides.items():
        setattr(mock, key, value)

    return mock


def make_reconciler_paperless(
    *,
    documents: list[dict] | None = None,
    all_ids: list[int] | None = None,
    correspondents: list[dict] | None = None,
) -> MagicMock:
    """Create a mock PaperlessClient for the reconciler tests.

    ``iter_all_documents`` routes on whether ``modified_after`` is *present*:
    the incremental sync always passes it (``None`` on the first run) and gets
    *documents*; the deletion sweep omits it and gets *all_ids* as bare-id docs.
    ``get_document`` returns the matching document, or a generic stub for an id
    outside *documents* (an out-of-band retry past the watermark).
    """
    paperless = MagicMock()
    docs = documents if documents is not None else []
    ids = all_ids if all_ids is not None else []
    by_id = {doc["id"]: doc for doc in docs if "id" in doc}

    def _iter_all_documents(**kwargs: Any) -> list[dict]:
        if "modified_after" in kwargs:
            return docs
        return [{"id": doc_id} for doc_id in ids]

    def _get_document(doc_id: int) -> dict:
        return by_id.get(doc_id, make_paperless_document(doc_id=doc_id))

    paperless.iter_all_documents.side_effect = _iter_all_documents
    paperless.get_document.side_effect = _get_document
    paperless.list_correspondents.return_value = correspondents or []
    paperless.list_document_types.return_value = []
    paperless.list_tags.return_value = []
    paperless.document_exists.return_value = False
    return paperless
