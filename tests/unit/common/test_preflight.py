"""Tests for common.preflight."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from common.preflight import PreflightError, run_preflight_checks
from tests.helpers.factories import make_settings_obj


MODULE = "common.preflight"


class TestRunPreflightChecks:
    """Tests for run_preflight_checks()."""

    def test_all_checks_pass_no_exception(self):
        # Arrange
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2,
            OCR_PROCESSING_TAG_ID=3, CLASSIFY_PRE_TAG_ID=4,
            CLASSIFY_POST_TAG_ID=5, CLASSIFY_PROCESSING_TAG_ID=6,
            ERROR_TAG_ID=7,
        )
        client = MagicMock()
        client.ping.return_value = None
        client.list_tags.return_value = [
            {"id": i} for i in range(1, 8)
        ]

        # Act / Assert — no exception
        with patch(f"{MODULE}.openai") as mock_openai:
            mock_openai.models.list.return_value = []
            run_preflight_checks(settings, client)

    def test_paperless_unreachable_raises_preflight_error(self):
        # Arrange
        settings = make_settings_obj()
        client = MagicMock()
        client.ping.side_effect = ConnectionError("connection refused")

        # Act / Assert
        with pytest.raises(PreflightError, match="not reachable"):
            run_preflight_checks(settings, client)

    def test_tag_list_fetch_fails_logs_warning_continues(self):
        # Arrange
        settings = make_settings_obj()
        client = MagicMock()
        client.ping.return_value = None
        client.list_tags.side_effect = OSError("API error")

        # Act — should not raise
        with patch(f"{MODULE}.openai") as mock_openai:
            mock_openai.models.list.return_value = []
            run_preflight_checks(settings, client)

        # Assert — list_tags was called
        client.list_tags.assert_called_once()

    def test_missing_tag_id_logs_warning(self):
        # Arrange
        settings = make_settings_obj(
            PRE_TAG_ID=999,
            POST_TAG_ID=2,
            OCR_PROCESSING_TAG_ID=None,
            CLASSIFY_PRE_TAG_ID=4,
            CLASSIFY_POST_TAG_ID=None,
            CLASSIFY_PROCESSING_TAG_ID=None,
            ERROR_TAG_ID=None,
        )
        client = MagicMock()
        client.ping.return_value = None
        client.list_tags.return_value = [{"id": 2}, {"id": 4}]  # 999 missing

        # Act
        with patch(f"{MODULE}.log") as mock_log, \
             patch(f"{MODULE}.openai") as mock_openai:
            mock_openai.models.list.return_value = []
            run_preflight_checks(settings, client)

        # Assert — warning logged for missing tag 999
        warning_calls = [
            c for c in mock_log.warning.call_args_list
            if "does not exist" in str(c)
        ]
        assert len(warning_calls) >= 1

    def test_none_tag_id_is_skipped(self):
        # Arrange
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2,
            OCR_PROCESSING_TAG_ID=None,
            CLASSIFY_PRE_TAG_ID=3,
            CLASSIFY_POST_TAG_ID=None,
            CLASSIFY_PROCESSING_TAG_ID=None,
            ERROR_TAG_ID=None,
        )
        client = MagicMock()
        client.ping.return_value = None
        client.list_tags.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]

        # Act
        with patch(f"{MODULE}.log") as mock_log, \
             patch(f"{MODULE}.openai") as mock_openai:
            mock_openai.models.list.return_value = []
            run_preflight_checks(settings, client)

        # Assert — no warnings about missing tags
        warning_calls = [
            c for c in mock_log.warning.call_args_list
            if "does not exist" in str(c)
        ]
        assert len(warning_calls) == 0

    def test_llm_unreachable_logs_warning_does_not_raise(self):
        # Arrange
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2,
            OCR_PROCESSING_TAG_ID=None, CLASSIFY_PRE_TAG_ID=3,
            CLASSIFY_POST_TAG_ID=None, CLASSIFY_PROCESSING_TAG_ID=None,
            ERROR_TAG_ID=None,
        )
        client = MagicMock()
        client.ping.return_value = None
        client.list_tags.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]

        # Act — LLM check fails but shouldn't raise
        with patch(f"{MODULE}.openai") as mock_openai:
            mock_openai.models.list.side_effect = OSError("LLM down")
            run_preflight_checks(settings, client)

        # Assert — we got here without exception
