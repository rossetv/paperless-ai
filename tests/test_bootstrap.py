"""Tests for common.bootstrap — shared daemon startup sequence."""

import os
from unittest.mock import MagicMock, patch

import pytest

from common.bootstrap import bootstrap_daemon


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Set minimal required env vars for Settings()."""
    monkeypatch.setenv("PAPERLESS_TOKEN", "test_token")
    monkeypatch.setenv("OPENAI_API_KEY", "test_api_key")
    monkeypatch.setenv("PRE_TAG_ID", "10")
    monkeypatch.setenv("POST_TAG_ID", "11")


@patch("common.bootstrap.recover_stale_locks")
@patch("common.bootstrap.run_preflight_checks")
@patch("common.bootstrap.register_signal_handlers")
@patch("common.bootstrap.init_llm_semaphore")
@patch("common.bootstrap.setup_libraries")
@patch("common.bootstrap.configure_logging")
@patch("common.bootstrap.PaperlessClient")
def test_bootstrap_success(
    mock_client_cls,
    mock_logging,
    mock_libraries,
    mock_semaphore,
    mock_signals,
    mock_preflight,
    mock_stale,
):
    """Successful bootstrap returns (settings, list_client) and calls all steps."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    result = bootstrap_daemon(
        processing_tag_id_attr="OCR_PROCESSING_TAG_ID",
        pre_tag_id_attr="PRE_TAG_ID",
    )

    assert result is not None
    settings, client = result
    assert client is mock_client
    assert settings.PRE_TAG_ID == 10

    mock_logging.assert_called_once()
    mock_libraries.assert_called_once()
    mock_signals.assert_called_once()
    mock_semaphore.assert_called_once()
    mock_preflight.assert_called_once()
    mock_stale.assert_called_once()


@patch("common.bootstrap.configure_logging")
def test_bootstrap_returns_none_on_settings_error(mock_logging):
    """ValueError from Settings() → returns None without creating a client."""
    with patch("common.bootstrap.Settings", side_effect=ValueError("bad")):
        result = bootstrap_daemon(
            processing_tag_id_attr="OCR_PROCESSING_TAG_ID",
            pre_tag_id_attr="PRE_TAG_ID",
        )
    assert result is None
    mock_logging.assert_not_called()


@patch("common.bootstrap.PaperlessClient")
@patch("common.bootstrap.setup_libraries")
@patch("common.bootstrap.configure_logging", side_effect=ValueError("bad log level"))
def test_bootstrap_returns_none_on_logging_error(mock_logging, mock_libraries, mock_client_cls):
    """ValueError from configure_logging() → returns None without creating a client."""
    result = bootstrap_daemon(
        processing_tag_id_attr="OCR_PROCESSING_TAG_ID",
        pre_tag_id_attr="PRE_TAG_ID",
    )
    assert result is None
    mock_logging.assert_called_once()
    mock_libraries.assert_not_called()
    mock_client_cls.assert_not_called()


@patch("common.bootstrap.recover_stale_locks")
@patch("common.bootstrap.run_preflight_checks")
@patch("common.bootstrap.register_signal_handlers")
@patch("common.bootstrap.init_llm_semaphore")
@patch("common.bootstrap.setup_libraries")
@patch("common.bootstrap.configure_logging")
@patch("common.bootstrap.PaperlessClient")
def test_bootstrap_preflight_failure(
    mock_client_cls,
    mock_logging,
    mock_libraries,
    mock_semaphore,
    mock_signals,
    mock_preflight,
    mock_stale,
):
    """PreflightError → returns None and closes list_client."""
    from common.preflight import PreflightError

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_preflight.side_effect = PreflightError("unreachable")

    result = bootstrap_daemon(
        processing_tag_id_attr="OCR_PROCESSING_TAG_ID",
        pre_tag_id_attr="PRE_TAG_ID",
    )

    assert result is None
    mock_client.close.assert_called_once()
    mock_stale.assert_not_called()


@patch("common.bootstrap.recover_stale_locks")
@patch("common.bootstrap.run_preflight_checks")
@patch("common.bootstrap.register_signal_handlers")
@patch("common.bootstrap.init_llm_semaphore")
@patch("common.bootstrap.setup_libraries")
@patch("common.bootstrap.configure_logging")
@patch("common.bootstrap.PaperlessClient")
def test_bootstrap_stale_locks_called_with_correct_attrs(
    mock_client_cls,
    mock_logging,
    mock_libraries,
    mock_semaphore,
    mock_signals,
    mock_preflight,
    mock_stale,
    monkeypatch,
):
    """recover_stale_locks receives the correct tag IDs from Settings."""
    monkeypatch.setenv("OCR_PROCESSING_TAG_ID", "99")
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    result = bootstrap_daemon(
        processing_tag_id_attr="OCR_PROCESSING_TAG_ID",
        pre_tag_id_attr="PRE_TAG_ID",
    )

    assert result is not None
    settings, _ = result
    mock_stale.assert_called_once_with(
        mock_client,
        processing_tag_id=99,
        pre_tag_id=10,
    )
