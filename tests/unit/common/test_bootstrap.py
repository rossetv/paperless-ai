"""Tests for common.bootstrap — the shared per-process startup."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from common.bootstrap import bootstrap_daemon, bootstrap_process
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
    @patch(f"{MODULE}.current_settings")
    def test_successful_bootstrap(
        self,
        mock_current_settings,
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
        # bootstrap_daemon builds Settings via the hot-load accessor.
        mock_current_settings.return_value = mock_settings
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

    @patch(f"{MODULE}.current_settings")
    def test_value_error_from_settings_returns_none(self, mock_current_settings):
        mock_current_settings.side_effect = ValueError("bad config")

        result = bootstrap_daemon(
            get_processing_tag_id=lambda s: s.OCR_PROCESSING_TAG_ID,
            get_pre_tag_id=lambda s: s.PRE_TAG_ID,
        )

        assert result is None

    @patch(f"{MODULE}.configure_logging")
    @patch(f"{MODULE}.current_settings")
    def test_value_error_from_configure_logging_returns_none(
        self,
        mock_current_settings,
        mock_configure_logging,
    ):
        mock_current_settings.return_value = MagicMock(LLM_MAX_CONCURRENT=0)
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
    @patch(f"{MODULE}.current_settings")
    def test_preflight_error_returns_none_and_closes_client(
        self,
        mock_current_settings,
        mock_configure_logging,
        mock_setup_libraries,
        mock_register_signals,
        mock_llm_limiter,
        mock_paperless_cls,
        mock_preflight,
    ):
        mock_settings = MagicMock(LLM_MAX_CONCURRENT=0)
        mock_current_settings.return_value = mock_settings
        mock_client = MagicMock()
        mock_paperless_cls.return_value = mock_client
        mock_preflight.side_effect = PreflightError("paperless unreachable")

        result = bootstrap_daemon(
            get_processing_tag_id=lambda s: s.OCR_PROCESSING_TAG_ID,
            get_pre_tag_id=lambda s: s.PRE_TAG_ID,
        )

        assert result is None
        mock_client.close.assert_called_once()


class TestBootstrapProcess:
    """Tests for bootstrap_process() — the per-process startup shared by all."""

    @patch(f"{MODULE}.llm_limiter")
    @patch(f"{MODULE}.register_signal_handlers")
    @patch(f"{MODULE}.setup_libraries")
    @patch(f"{MODULE}.configure_logging")
    @patch(f"{MODULE}.current_settings")
    def test_runs_every_step_and_initialises_the_limiter(
        self,
        mock_current_settings,
        mock_configure_logging,
        mock_setup_libraries,
        mock_register_signals,
        mock_llm_limiter,
    ):
        """bootstrap_process runs all five steps and returns the settings.

        Regression: an entry point that omits llm_limiter.init() leaves the
        limiter uninitialised, so every LLM call raises RuntimeError at request
        time — the search server 500ed on every query before this sequence was
        centralised here.
        """
        mock_settings = MagicMock(LLM_MAX_CONCURRENT=4)
        mock_current_settings.return_value = mock_settings

        settings = bootstrap_process()

        assert settings is mock_settings
        mock_configure_logging.assert_called_once_with(mock_settings)
        mock_setup_libraries.assert_called_once_with(mock_settings)
        mock_register_signals.assert_called_once()
        mock_llm_limiter.init.assert_called_once_with(4)


def test_bootstrap_process_loads_settings_from_app_db(tmp_path) -> None:
    """bootstrap_process builds Settings via the DB-backed loader, reading
    APP_DB_PATH from the environment and layering the config table over it."""
    from appdb import config as config_store
    from appdb.connection import connect
    from appdb.schema import ensure_schema
    from common.bootstrap import bootstrap_process

    app_db = str(tmp_path / "app.db")
    conn = connect(app_db)
    ensure_schema(conn)
    # A value only the config table carries — proves the loader read it.
    config_store.set_value(conn, "OCR_DPI", "175")
    conn.close()

    env = {
        "APP_DB_PATH": app_db,
        "PAPERLESS_TOKEN": "env-token",
        "OPENAI_API_KEY": "env-api-key",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = bootstrap_process()

    assert settings.OCR_DPI == 175
    assert settings.APP_DB_PATH == app_db
