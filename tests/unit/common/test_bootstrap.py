"""Tests for common.bootstrap."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from common.bootstrap import bootstrap_daemon
from common.preflight import PreflightError

MODULE = "common.bootstrap"

class TestBootstrapDaemon:
    """Tests for bootstrap_daemon()."""

    @patch(f"{MODULE}.recover_stale_locks")
    @patch(f"{MODULE}.run_preflight_checks")
    @patch(f"{MODULE}.PaperlessClient")
    @patch(f"{MODULE}.llm_limiter")
    @patch(f"{MODULE}.register_signal_handlers")
    @patch(f"{MODULE}.setup_libraries")
    @patch(f"{MODULE}.configure_logging")
    @patch(f"{MODULE}.Settings")
    def test_successful_bootstrap(
        self,
        mock_settings_cls,
        mock_configure_logging,
        mock_setup_libraries,
        mock_register_signals,
        mock_llm_limiter,
        mock_paperless_cls,
        mock_preflight,
        mock_recover,
    ):
        mock_settings = MagicMock()
        mock_settings.LLM_MAX_CONCURRENT = 8
        mock_settings.OCR_PROCESSING_TAG_ID = 55
        mock_settings.PRE_TAG_ID = 443
        mock_settings_cls.return_value = mock_settings
        mock_client = MagicMock()
        mock_paperless_cls.return_value = mock_client

        result = bootstrap_daemon(
            get_processing_tag_id=lambda s: s.OCR_PROCESSING_TAG_ID,
            get_pre_tag_id=lambda s: s.PRE_TAG_ID,
        )

        assert result is not None
        settings, client = result
        assert settings is mock_settings
        assert client is mock_client

        mock_register_signals.assert_called_once()
        mock_llm_limiter.init.assert_called_once_with(8)
        mock_recover.assert_called_once_with(
            mock_client,
            processing_tag_id=55,
            pre_tag_id=443,
        )

    @patch(f"{MODULE}.Settings")
    def test_value_error_from_settings_returns_none(self, mock_settings_cls):
        mock_settings_cls.side_effect = ValueError("bad config")

        result = bootstrap_daemon(
            get_processing_tag_id=lambda s: s.OCR_PROCESSING_TAG_ID,
            get_pre_tag_id=lambda s: s.PRE_TAG_ID,
        )

        assert result is None

    @patch(f"{MODULE}.configure_logging")
    @patch(f"{MODULE}.Settings")
    def test_value_error_from_configure_logging_returns_none(
        self, mock_settings_cls, mock_configure_logging,
    ):
        mock_settings_cls.return_value = MagicMock(LLM_MAX_CONCURRENT=0)
        mock_configure_logging.side_effect = ValueError("bad log config")

        result = bootstrap_daemon(
            get_processing_tag_id=lambda s: s.OCR_PROCESSING_TAG_ID,
            get_pre_tag_id=lambda s: s.PRE_TAG_ID,
        )

        assert result is None

    @patch(f"{MODULE}.run_preflight_checks")
    @patch(f"{MODULE}.PaperlessClient")
    @patch(f"{MODULE}.llm_limiter")
    @patch(f"{MODULE}.register_signal_handlers")
    @patch(f"{MODULE}.setup_libraries")
    @patch(f"{MODULE}.configure_logging")
    @patch(f"{MODULE}.Settings")
    def test_preflight_error_returns_none_and_closes_client(
        self,
        mock_settings_cls,
        mock_configure_logging,
        mock_setup_libraries,
        mock_register_signals,
        mock_llm_limiter,
        mock_paperless_cls,
        mock_preflight,
    ):
        mock_settings = MagicMock(LLM_MAX_CONCURRENT=0)
        mock_settings_cls.return_value = mock_settings
        mock_client = MagicMock()
        mock_paperless_cls.return_value = mock_client
        mock_preflight.side_effect = PreflightError("paperless unreachable")

        result = bootstrap_daemon(
            get_processing_tag_id=lambda s: s.OCR_PROCESSING_TAG_ID,
            get_pre_tag_id=lambda s: s.PRE_TAG_ID,
        )

        assert result is None
        mock_client.close.assert_called_once()
