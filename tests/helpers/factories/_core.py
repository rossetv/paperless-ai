"""Configuration, Paperless, and store-shape test factories.

The ``tests.helpers.factories`` package re-exports every factory from its
``__init__``; this submodule holds the ``Settings``, Paperless-document,
``ClassificationResult``, and store-boundary (``DocumentMeta``, ``ChunkInput``,
``SearchFilters``) builders.  Search-pipeline factories live in the sibling
:mod:`tests.helpers.factories._search`.

Every test that needs a domain object builds it through a factory here, so the
one field a test actually cares about is the only one it has to spell out
(CODE_GUIDELINES §11.5).  Irrelevant fields are filled with deterministic
defaults.  Hand-rolled per-file builders are a smell: they drift, and the same
literal (a settings field, an embedding vector) ends up copied across modules.
"""

from __future__ import annotations

import io
import os
from typing import Any
from unittest.mock import MagicMock, patch

from PIL import Image

from classifier.result import ClassificationResult

_MINIMAL_ENV: dict[str, str] = {
    "PAPERLESS_TOKEN": "test-token",
    "OPENAI_API_KEY": "test-api-key",
}

# Default embedding width for tests.  The store, the worker, and the reconciler
# all agree on a dimension; four keeps test vectors tiny and readable.  This is
# the single home for the test embedding dimension and the unit-vector formula
# below — no test re-spells ``1.0 / (dimensions ** 0.5)``.
DEFAULT_EMBEDDING_DIMENSIONS = 4


def make_embedding(dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS) -> tuple[float, ...]:
    """Return a deterministic unit-length all-equal float32 embedding vector.

    Each component is ``1 / sqrt(dimensions)``, so the vector has length 1.
    For test purposes any non-zero vector is valid; equal components eliminate
    numerical surprise.  This is the one definition of the test embedding
    literal — every factory and test that needs a vector calls it.
    """
    component = 1.0 / (dimensions**0.5)
    return tuple(component for _ in range(dimensions))


def make_settings(**overrides: str) -> Any:
    """Create a ``Settings`` instance with minimal valid environment.

    Any key in *overrides* is injected as an environment variable before
    construction.  The returned object is a real ``Settings`` instance, built
    via :meth:`Settings.from_environment`.
    """
    from common.config import Settings

    env = {**_MINIMAL_ENV, **overrides}
    with patch.dict(os.environ, env, clear=True):
        return Settings.from_environment()


def make_settings_obj(**overrides: Any) -> MagicMock:
    """Create a MagicMock that behaves like a Settings object.

    Useful when a test needs a Settings-like object without touching env vars.
    The defaults span every daemon's fields — OCR, classifier, indexer, and
    store — so this single factory replaces the per-file ``_make_settings``
    builders the store and indexer tests used to hand-roll.
    """
    defaults = {
        "PAPERLESS_URL": "http://paperless:8000",
        "PAPERLESS_TOKEN": "test-token",
        "OPENAI_API_KEY": "test-api-key",
        "LLM_PROVIDER": "openai",
        "AI_MODELS": ["gpt-5.4-mini"],
        "OCR_REFUSAL_MARKERS": ["chatgpt refused to transcribe"],
        "OCR_INCLUDE_PAGE_MODELS": False,
        "PRE_TAG_ID": 443,
        "POST_TAG_ID": 444,
        "OCR_PROCESSING_TAG_ID": None,
        "CLASSIFY_PRE_TAG_ID": 444,
        "CLASSIFY_POST_TAG_ID": None,
        "CLASSIFY_PROCESSING_TAG_ID": None,
        "ERROR_TAG_ID": 552,
        "POLL_INTERVAL": 15,
        "MAX_RETRIES": 3,
        "MAX_RETRY_BACKOFF_SECONDS": 30,
        "REQUEST_TIMEOUT": 180,
        "LLM_MAX_CONCURRENT": 0,
        "OCR_DPI": 300,
        "OCR_MAX_SIDE": 1600,
        "PAGE_WORKERS": 2,
        "DOCUMENT_WORKERS": 2,
        "LOG_LEVEL": "INFO",
        "LOG_FORMAT": "console",
        "REFUSAL_MARK": "CHATGPT REFUSED TO TRANSCRIBE",
        "CLASSIFY_PERSON_FIELD_ID": None,
        "CLASSIFY_DEFAULT_COUNTRY_TAG": "",
        "CLASSIFY_MAX_CHARS": 0,
        "CLASSIFY_MAX_TOKENS": 0,
        "CLASSIFY_TAG_LIMIT": 5,
        "CLASSIFY_TAXONOMY_LIMIT": 100,
        "CLASSIFY_MAX_PAGES": 3,
        "CLASSIFY_TAIL_PAGES": 2,
        "CLASSIFY_HEADERLESS_CHAR_LIMIT": 15000,
        # Indexer / store fields.
        "INDEX_DB_PATH": "/tmp/test-index.db",
        "EMBEDDING_MODEL": "test-model",
        "EMBEDDING_DIMENSIONS": DEFAULT_EMBEDDING_DIMENSIONS,
        "CHUNK_SIZE": 2000,
        "CHUNK_OVERLAP": 256,
        "RECONCILE_INTERVAL": 300,
        "DELETION_SWEEP_INTERVAL": 3600,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def make_store_settings(
    db_path: str,
    *,
    model: str = "test-model",
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    **overrides: Any,
) -> MagicMock:
    """Create a Settings-like mock for the store and the indexer pipeline.

    A thin convenience over :func:`make_settings_obj` that pins the three
    fields a store-backed test always sets per case — the database path and
    the embedding model and dimensions.

    Args:
        db_path: Filesystem path for ``INDEX_DB_PATH`` (usually ``tmp_path``).
        model: Value for ``EMBEDDING_MODEL``.
        dimensions: Value for ``EMBEDDING_DIMENSIONS``.
        **overrides: Any further Settings field overrides.
    """
    return make_settings_obj(
        INDEX_DB_PATH=db_path,
        EMBEDDING_MODEL=model,
        EMBEDDING_DIMENSIONS=dimensions,
        **overrides,
    )


def make_document(**overrides: Any) -> dict:
    """Create a Paperless document dict with sensible defaults.

    The classifier-shaped default — it carries ``custom_fields``.  Indexer
    tests want the indexer-shaped document instead: see
    :func:`make_paperless_document`.
    """
    doc = {
        "id": 1,
        "title": "Test Document",
        "content": "Sample document content for testing.",
        "tags": [443],
        "correspondent": None,
        "document_type": None,
        "created": "2025-01-15",
        "custom_fields": [],
    }
    doc.update(overrides)
    return doc


def make_paperless_document(
    *,
    doc_id: int = 1,
    content: str | None = "Sample document content for the indexer.",
    modified: str = "2024-06-01T12:00:00+00:00",
    created: str | None = "2024-01-15",
    title: str | None = None,
    tags: list[int] | None = None,
    correspondent: int | None = None,
    document_type: int | None = None,
    **overrides: Any,
) -> dict:
    """Create a Paperless document dict shaped for the indexer.

    Mirrors :class:`~common.paperless.PaperlessDocument`: it carries the
    ``content``, ``modified``, ``correspondent``, and ``document_type`` fields
    the indexer reads, and defaults ``tags`` to empty rather than the
    classifier's pre-tag.  This is the single Paperless-document builder the
    worker, reconciler, and indexer-pipeline tests share.

    Args:
        doc_id: The document id.
        content: OCR content; pass ``None`` to model an un-OCR'd document.
        modified: The Paperless ``modified`` timestamp.
        created: The Paperless ``created`` date.
        title: The document title; defaults to ``"Document <id>"``.
        tags: Applied tag ids; defaults to an empty list.
        correspondent: The correspondent id, or ``None``.
        document_type: The document-type id, or ``None``.
        **overrides: Any further document-field overrides.
    """
    doc: dict[str, Any] = {
        "id": doc_id,
        "title": title if title is not None else f"Document {doc_id}",
        "content": content,
        "tags": tags if tags is not None else [],
        "correspondent": correspondent,
        "document_type": document_type,
        "created": created,
        "modified": modified,
    }
    doc.update(overrides)
    return doc


def make_png_bytes(width: int = 20, height: int = 20, color: str = "red") -> bytes:
    """Create a small PNG image as raw bytes."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_classification_result(**overrides: Any) -> ClassificationResult:
    """Create a ClassificationResult with sensible defaults."""
    defaults = {
        "title": "Test Invoice",
        "correspondent": "Acme Corp",
        "tags": ["invoice", "2025"],
        "document_date": "2025-01-15",
        "document_type": "Invoice",
        "language": "en",
        "person": "",
    }
    defaults.update(overrides)
    return ClassificationResult(**defaults)


def make_document_meta(**overrides: Any) -> Any:
    """Create a DocumentMeta with sensible defaults.

    All irrelevant fields are filled with deterministic values; callers
    override only the field under test.
    """
    from store.models import DocumentMeta

    defaults: dict[str, Any] = {
        "id": 1,
        "title": "Test Document",
        "correspondent_id": None,
        "document_type_id": None,
        "tag_ids": (10, 20),
        "created": "2024-01-15T00:00:00Z",
        "modified": "2024-06-01T12:00:00Z",
        "content_hash": "abc123def456",
        "page_count": 2,
    }
    defaults.update(overrides)
    return DocumentMeta(**defaults)


def make_chunk_input(
    chunk_index: int = 0,
    *,
    text: str = "Sample chunk text for testing purposes.",
    page_hint: int | None = 1,
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    **overrides: Any,
) -> Any:
    """Create a single ChunkInput with a deterministic embedding vector.

    The embedding is built by :func:`make_embedding` — the one home for the
    test embedding literal.

    Args:
        chunk_index: Zero-based position within the parent document.
        text: Chunk text content.
        page_hint: Source page number, or None.
        dimensions: Length of the synthesised embedding vector.
        **overrides: Additional ChunkInput field overrides.
    """
    from store.models import ChunkInput

    fields: dict[str, Any] = {
        "chunk_index": chunk_index,
        "text": text,
        "page_hint": page_hint,
        "embedding": make_embedding(dimensions),
    }
    fields.update(overrides)
    return ChunkInput(**fields)


def make_search_filters(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    correspondent_id: int | None = None,
    document_type_id: int | None = None,
    tag_ids: tuple[int, ...] = (),
) -> Any:
    """Create a SearchFilters with every field defaulting to "no restriction".

    A reader test that exercises one filter passes only that keyword; the rest
    stay unrestricted.  The all-default call models "no filter at all".
    """
    from store.models import SearchFilters

    return SearchFilters(
        date_from=date_from,
        date_to=date_to,
        correspondent_id=correspondent_id,
        document_type_id=document_type_id,
        tag_ids=tag_ids,
    )


def make_chunks(
    count: int = 2, *, dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
) -> list[Any]:
    """Create *count* deterministic ChunkInput objects.

    Each chunk gets a contiguous ``chunk_index`` from 0, a unique text body,
    and a ``page_hint`` of ``chunk_index + 1``.  Replaces the per-file
    ``_chunks`` list builders the store tests hand-rolled.

    Args:
        count: How many ChunkInput objects to build.
        dimensions: Embedding width for every chunk.
    """
    return [
        make_chunk_input(
            index,
            text=f"Chunk {index} text content.",
            page_hint=index + 1,
            dimensions=dimensions,
        )
        for index in range(count)
    ]
