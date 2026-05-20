"""Shared builders for the classifier unit tests.

Several classifier source files have their tests split across two files for the
500-line ceiling (CODE_GUIDELINES §3.1) — ``test_worker`` /
``test_worker_metadata`` and ``test_provider`` / ``test_provider_compat``.  The
builders those pairs share live here so each file imports one definition rather
than redeclaring it, mirroring ``tests/integration/conftest.py``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import openai

from classifier.provider import ClassificationProvider
from classifier.worker import ClassificationProcessor
from tests.helpers.factories import (
    make_classification_result,
    make_document,
    make_settings_obj,
)
from tests.helpers.mocks import make_mock_paperless


def make_processor(
    doc: Any = None,
    settings_overrides: dict[str, Any] | None = None,
    paperless_overrides: dict[str, Any] | None = None,
    classifier_overrides: dict[str, Any] | None = None,
    taxonomy_overrides: dict[str, Any] | None = None,
) -> ClassificationProcessor:
    """Build a ClassificationProcessor with mocked dependencies.

    The classifier and taxonomy cache are MagicMocks with sensible default
    behaviour (a successful classification, resolvable taxonomy ids); each can
    be overridden per test via the ``*_overrides`` mappings.
    """
    doc = doc or make_document()
    settings = make_settings_obj(**(settings_overrides or {}))
    paperless = make_mock_paperless(**(paperless_overrides or {}))
    classifier = MagicMock()
    taxonomy = MagicMock()

    # Default classifier behaviour: successful classification
    result = make_classification_result()
    classifier.classify_text.return_value = (result, "gpt-5.4-mini")
    classifier.get_stats.return_value = {
        "attempts": 1,
        "api_errors": 0,
        "invalid_json": 0,
        "fallback_successes": 0,
        "temperature_retries": 0,
        "response_format_retries": 0,
        "max_tokens_retries": 0,
    }

    # Default taxonomy behaviour
    taxonomy.correspondent_names.return_value = ["Acme Corp"]
    taxonomy.document_type_names.return_value = ["Invoice"]
    taxonomy.tag_names.return_value = ["2025"]
    taxonomy.get_or_create_correspondent_id.return_value = 101
    taxonomy.get_or_create_document_type_id.return_value = 201
    taxonomy.get_or_create_tag_ids.return_value = [301, 302]

    if classifier_overrides:
        for key, value in classifier_overrides.items():
            setattr(classifier, key, value)
    if taxonomy_overrides:
        for key, value in taxonomy_overrides.items():
            setattr(taxonomy, key, value)

    return ClassificationProcessor(doc, paperless, classifier, taxonomy, settings)


def make_doc_with_content(content: str, tags: Any = None) -> dict:
    """Create a Paperless document dict carrying *content* and *tags*."""
    return make_document(content=content, tags=tags or [443])


def make_provider(**settings_overrides: Any) -> ClassificationProvider:
    """Create a ClassificationProvider with a mock Settings object."""
    settings = make_settings_obj(**settings_overrides)
    return ClassificationProvider(settings)


def make_completion_response(content: str = "") -> MagicMock:
    """Build a fake OpenAI chat completion response carrying *content*."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def valid_classification_json(**overrides: Any) -> str:
    """Return a valid classification JSON string, with field *overrides*."""
    data: dict[str, Any] = {
        "title": "Test Invoice",
        "correspondent": "Acme Corp",
        "tags": ["invoice", "2025"],
        "document_date": "2025-01-15",
        "document_type": "Invoice",
        "language": "en",
        "person": "",
    }
    data.update(overrides)
    return json.dumps(data)


def make_bad_request_error(message: str) -> openai.BadRequestError:
    """Create an :class:`openai.BadRequestError` carrying *message*."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.headers = {}
    mock_response.json.return_value = {"error": {"message": message}}
    return openai.BadRequestError(
        message=message,
        response=mock_response,
        body={"error": {"message": message}},
    )


def make_api_error(message: str = "Server error") -> openai.APIError:
    """Create a generic :class:`openai.APIError`."""
    return openai.APIError(
        message=message,
        request=MagicMock(),
        body=None,
    )
