"""Settings, Paperless-document, classification and store-write test factories."""

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

# Four dimensions keeps test vectors tiny and readable.
DEFAULT_EMBEDDING_DIMENSIONS = 4


def make_embedding(dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS) -> tuple[float, ...]:
    """Return a deterministic unit-length vector with all components equal."""
    component = 1.0 / (dimensions**0.5)
    return tuple(component for _ in range(dimensions))


def make_settings(**overrides: str) -> Any:
    """Build a real ``Settings`` from a minimal env plus *overrides* as env vars."""
    from common.config import Settings

    env = {**_MINIMAL_ENV, **overrides}
    with patch.dict(os.environ, env, clear=True):
        return Settings.from_environment()


def make_settings_obj(**overrides: Any) -> MagicMock:
    """Create a Settings-like MagicMock with defaults for every daemon's fields."""
    defaults = {
        "PAPERLESS_URL": "http://paperless:8000",
        "PAPERLESS_PUBLIC_URL": "http://paperless:8000",
        "PAPERLESS_TOKEN": "test-token",
        "OPENAI_API_KEY": "test-api-key",
        "LLM_PROVIDER": "openai",
        "OCR_PROVIDER": "openai",
        "CLASSIFY_PROVIDER": "openai",
        "SEARCH_PLANNER_PROVIDER": "openai",
        "SEARCH_JUDGE_PROVIDER": "openai",
        "SEARCH_ANSWER_PROVIDER": "openai",
        "OCR_MODELS": ["gpt-5.4-mini"],
        "CLASSIFY_MODELS": ["gpt-5.4-mini"],
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
        "OPENAI_FLEX_TIER": True,
        "OCR_DPI": 300,
        "OCR_MAX_SIDE": 1600,
        "OCR_IMAGE_DETAIL": "high",
        "OCR_REASONING_EFFORT": "medium",
        "OCR_SKIP_BORN_DIGITAL": False,
        "OCR_BORN_DIGITAL_MIN_CHARS": 1,
        "OCR_BORN_DIGITAL_TAG_ID": None,
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
        "CLASSIFY_TAXONOMY_LIMIT": 40,
        "CLASSIFY_MAX_PAGES": 3,
        "CLASSIFY_TAIL_PAGES": 2,
        "CLASSIFY_HEADERLESS_CHAR_LIMIT": 15000,
        "CLASSIFY_REASONING_EFFORT": "medium",
        # Indexer / store fields.
        "INDEX_DB_PATH": "/tmp/test-index.db",
        "APP_DB_PATH": "/tmp/test-app.db",
        "EMBEDDING_PROVIDER": "openai",
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
    """Create a Settings-like mock with the index DB path and embedding model set."""
    return make_settings_obj(
        INDEX_DB_PATH=db_path,
        EMBEDDING_MODEL=model,
        EMBEDDING_DIMENSIONS=dimensions,
        **overrides,
    )


def make_document(**overrides: Any) -> dict:
    """Create a classifier-shaped Paperless document dict (with ``custom_fields``).

    Indexer tests want :func:`make_paperless_document` instead.
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

    Mirrors :class:`~common.paperless.PaperlessDocument`; ``tags`` defaults to
    empty rather than the classifier's pre-tag. Pass ``content=None`` to model
    a document that has not been OCR'd.
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
        "tags": ("invoice", "2025"),
        "document_date": "2025-01-15",
        "document_type": "Invoice",
        "language": "en",
        "person": "",
    }
    defaults.update(overrides)
    return ClassificationResult(**defaults)


def make_document_meta(**overrides: Any) -> Any:
    """Create a DocumentMeta with deterministic defaults."""
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
    """Create a single ChunkInput with a deterministic embedding vector."""
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
    """Create a SearchFilters with every field defaulting to "no restriction"."""
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
    """Create *count* ChunkInputs indexed from 0, with ``page_hint = index + 1``."""
    return [
        make_chunk_input(
            index,
            text=f"Chunk {index} text content.",
            page_hint=index + 1,
            dimensions=dimensions,
        )
        for index in range(count)
    ]
