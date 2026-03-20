"""Test object factories."""

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


def make_settings(**overrides: str) -> Any:
    """Create a ``Settings`` instance with minimal valid environment.

    Any key in *overrides* is injected as an environment variable before
    construction.  The returned object is a real ``Settings`` instance.
    """
    from common.config import Settings

    env = {**_MINIMAL_ENV, **overrides}
    with patch.dict(os.environ, env, clear=True):
        return Settings()


def make_settings_obj(**overrides: Any) -> MagicMock:
    """Create a MagicMock that behaves like a Settings object.

    Useful when you need a Settings-like object without touching env vars.
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
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock

def make_document(**overrides: Any) -> dict:
    """Create a Paperless document dict with sensible defaults."""
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
