"""Reusable mock builders."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from tests.helpers.factories import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    make_document,
    make_embedding,
    make_settings_obj,
)


def make_mock_embedding_client(
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
) -> MagicMock:
    """Create a MagicMock that behaves like a ``common.embeddings.EmbeddingClient``.

    ``embed(texts)`` returns one deterministic unit vector per input text,
    built by :func:`tests.helpers.factories.make_embedding` — so the indexer
    worker, the reconciler, and the pipeline tests share a single embedding
    client mock instead of hand-rolling the ``1/sqrt(d)`` literal each.

    Args:
        dimensions: Width of every returned embedding vector.
    """
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

    Either supply *vectors* (explicit list of vectors, one per input) or *n*
    (number of inputs; generic zero-vectors of the given *dimensions* are used).
    The mock is stateful: successive calls consume the next slice of vectors, so
    batched calls that split a long input across multiple requests work correctly.

    Returns a ``(mock_openai, last_response)`` pair.  ``last_response`` is the
    ``MagicMock`` returned by the most-recent call, which is useful in tests that
    want to pass it as a ``side_effect`` value.
    """
    if vectors is not None:
        all_vectors = vectors
    elif n is not None:
        all_vectors = [[0.0] * dimensions for _ in range(n)]
    else:
        raise ValueError("Provide either vectors= or n= to make_mock_embeddings")

    # Track the position in all_vectors across successive calls so that
    # cross-batch ordering tests work without per-call bookkeeping in the test.
    position: list[int] = [0]

    last_response: list[MagicMock] = []

    def _create(*, model: str, input: list[str], **kwargs: Any) -> MagicMock:
        start = position[0]
        end = start + len(input)
        batch_vectors = all_vectors[start:end]
        position[0] = end

        response = MagicMock()
        response.data = [
            MagicMock(embedding=vec, index=i)
            for i, vec in enumerate(batch_vectors)
        ]
        last_response.clear()
        last_response.append(response)
        return response

    mock_openai = MagicMock()
    mock_openai.embeddings.create.side_effect = _create

    # Build a dummy response for callers that need the raw response object.
    dummy_response = MagicMock()
    dummy_response.data = [
        MagicMock(embedding=[0.0] * dimensions, index=0)
    ]
    return mock_openai, dummy_response

def make_mock_paperless(**overrides: Any) -> MagicMock:
    """Create a MagicMock that behaves like a PaperlessClient.

    The mock supports common operations out of the box:
    - ``get_document`` returns ``make_document()``
    - ``download_content`` returns dummy PDF bytes
    - ``list_tags/correspondents/document_types`` return empty lists
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

def make_mock_ocr_provider(**overrides: Any) -> MagicMock:
    """Create a MagicMock that behaves like an OcrProvider.

    Returns ``("Transcribed text", "gpt-5.4-mini")`` by default.
    """
    mock = MagicMock()
    mock.transcribe_image.return_value = ("Transcribed text for page.", "gpt-5.4-mini")
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
    """Create a mock PaperlessClient for the reconciler unit and integration tests.

    The incremental sync calls ``iter_all_documents(modified_after=...)`` — the
    keyword is always passed, even when its value is None on the first run.
    The deletion sweep calls ``iter_all_documents()`` with no keyword at all.
    The side effect disambiguates on keyword *presence*: an incremental call
    yields *documents*, a sweep call yields *all_ids* as bare-id docs.
    Disambiguating on a ``None`` value instead would misroute a first-run
    incremental sync into the sweep branch.

    Args:
        documents: Documents an incremental call returns.
        all_ids: Document ids a deletion-sweep enumeration returns.
        correspondents: Correspondent taxonomy entries ``list_correspondents``
            returns; defaults to an empty list.
    """
    paperless = MagicMock()
    docs = documents if documents is not None else []
    ids = all_ids if all_ids is not None else []

    def _iter_all_documents(**kwargs: Any) -> list[dict]:
        if "modified_after" in kwargs:
            return docs
        return [{"id": doc_id} for doc_id in ids]

    paperless.iter_all_documents.side_effect = _iter_all_documents
    paperless.list_correspondents.return_value = correspondents or []
    paperless.list_document_types.return_value = []
    paperless.list_tags.return_value = []
    paperless.document_exists.return_value = False
    return paperless
