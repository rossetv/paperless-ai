"""Tests for common.logging_config."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import structlog
import pytest

from common.logging_config import configure_logging

def _make_settings(log_format: str = "console", log_level: str = "INFO") -> MagicMock:
    s = MagicMock()
    s.LOG_FORMAT = log_format
    s.LOG_LEVEL = log_level
    return s


@pytest.fixture(autouse=True)
def _clean_root_logger():
    """Remove handlers added during tests so they don't leak."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    original_structlog_config = structlog.get_config()
    yield
    root.handlers = original_handlers
    root.level = original_level
    structlog.configure(**original_structlog_config)

class TestConsoleFormat:

    def test_uses_console_renderer(self):
        settings = _make_settings(log_format="console")
        configure_logging(settings)

        root = logging.getLogger()
        # Find the handler we added (StreamHandler to stdout)
        handler = root.handlers[-1]
        formatter = handler.formatter
        assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)
        # The processor chain should end with ConsoleRenderer
        assert isinstance(formatter.processors[-1], structlog.dev.ConsoleRenderer)

class TestJsonFormat:

    def test_uses_json_renderer(self):
        settings = _make_settings(log_format="json")
        configure_logging(settings)

        root = logging.getLogger()
        handler = root.handlers[-1]
        formatter = handler.formatter
        assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)
        assert isinstance(formatter.processors[-1], structlog.processors.JSONRenderer)

class TestLogLevel:

    def test_log_level_set_to_debug(self):
        settings = _make_settings(log_level="DEBUG")
        configure_logging(settings)
        assert logging.getLogger().level == logging.DEBUG

    def test_log_level_set_to_warning(self):
        settings = _make_settings(log_level="WARNING")
        configure_logging(settings)
        assert logging.getLogger().level == logging.WARNING

    def test_log_level_set_to_info(self):
        settings = _make_settings(log_level="INFO")
        configure_logging(settings)
        assert logging.getLogger().level == logging.INFO

class TestThirdPartyLoggers:

    def test_httpx_logger_set_to_warning(self):
        settings = _make_settings()
        configure_logging(settings)
        assert logging.getLogger("httpx").level == logging.WARNING

    def test_openai_logger_set_to_warning(self):
        settings = _make_settings()
        configure_logging(settings)
        assert logging.getLogger("openai").level == logging.WARNING

    def test_openai_base_client_logger_set_to_warning(self):
        settings = _make_settings()
        configure_logging(settings)
        assert logging.getLogger("openai._base_client").level == logging.WARNING

    def test_openai_logger_handlers_cleared(self):
        settings = _make_settings()
        configure_logging(settings)
        assert logging.getLogger("openai").handlers == []

    def test_openai_logger_propagates(self):
        settings = _make_settings()
        configure_logging(settings)
        assert logging.getLogger("openai").propagate is True
