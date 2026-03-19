"""Reusable mock builders."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from tests.helpers.factories import make_document, make_settings_obj

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

    Returns ``("Transcribed text", "gpt-5-mini")`` by default.
    """
    mock = MagicMock()
    mock.transcribe_image.return_value = ("Transcribed text for page.", "gpt-5-mini")
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
    mock.classify_text.return_value = (make_classification_result(), "gpt-5-mini")
    mock.get_stats.return_value = {
        "attempts": 1,
        "api_errors": 0,
        "invalid_json": 0,
        "fallback_successes": 0,
    }

    for key, value in overrides.items():
        setattr(mock, key, value)

    return mock
