"""Tests for startup preflight checks."""

import os
from unittest.mock import MagicMock, patch

import pytest

from common.config import Settings
from common.preflight import PreflightError, run_preflight_checks


@pytest.fixture
def settings(mocker):
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "PRE_TAG_ID": "10",
            "POST_TAG_ID": "11",
            "ERROR_TAG_ID": "12",
        },
        clear=True,
    )
    return Settings()


def _make_client(reachable=True, tags=None):
    """Create a mock PaperlessClient."""
    client = MagicMock()
    if reachable:
        client.ping.return_value = None
    else:
        client.ping.side_effect = RuntimeError("unreachable")
    if tags is not None:
        client.list_tags.return_value = tags
    else:
        client.list_tags.return_value = [
            {"id": 10, "name": "ocr-queue"},
            {"id": 11, "name": "ocr-done"},
            {"id": 12, "name": "error"},
        ]
    return client


@patch("common.preflight.openai")
def test_all_checks_pass(mock_openai, settings):
    """No error raised when everything is reachable and tags exist."""
    client = _make_client(reachable=True)
    run_preflight_checks(settings, client)  # should not raise


@patch("common.preflight.openai")
def test_paperless_unreachable_raises(mock_openai, settings):
    """PreflightError raised when Paperless is not reachable."""
    client = _make_client(reachable=False)
    with pytest.raises(PreflightError, match="not reachable"):
        run_preflight_checks(settings, client)


@patch("common.preflight.openai")
def test_missing_tag_logs_warning_but_does_not_raise(mock_openai, settings):
    """Missing tags are warnings, not fatal errors."""
    client = _make_client(
        reachable=True,
        tags=[{"id": 10, "name": "ocr-queue"}],  # 11 and 12 missing
    )
    # Should not raise
    run_preflight_checks(settings, client)


@patch("common.preflight.openai")
def test_tag_fetch_failure_does_not_raise(mock_openai, settings):
    """If we can't fetch tags, log a warning and continue."""
    client = _make_client(reachable=True)
    client.list_tags.side_effect = RuntimeError("API error")
    run_preflight_checks(settings, client)  # should not raise


@patch("common.preflight.openai")
def test_llm_unreachable_does_not_raise(mock_openai, settings):
    """LLM being unreachable is a warning, not fatal."""
    mock_openai.models.list.side_effect = RuntimeError("connection refused")
    client = _make_client(reachable=True)
    run_preflight_checks(settings, client)  # should not raise
