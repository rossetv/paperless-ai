"""Tests for common.shutdown."""

from __future__ import annotations

import signal

import pytest

from common.shutdown import (
    is_shutdown_requested,
    register_signal_handlers,
    request_shutdown,
    reset_shutdown,
)

@pytest.fixture(autouse=True)
def _clean_shutdown():
    """Reset the shutdown flag and restore original signal handlers."""
    original_sigterm = signal.getsignal(signal.SIGTERM)
    original_sigint = signal.getsignal(signal.SIGINT)
    reset_shutdown()
    yield
    reset_shutdown()
    signal.signal(signal.SIGTERM, original_sigterm)
    signal.signal(signal.SIGINT, original_sigint)

class TestInitialState:

    def test_not_shutdown_initially(self):
        assert is_shutdown_requested() is False

class TestRequestShutdown:

    def test_sets_flag(self):
        request_shutdown()
        assert is_shutdown_requested() is True

    def test_idempotent(self):
        request_shutdown()
        request_shutdown()
        assert is_shutdown_requested() is True

class TestIsShutdownRequested:

    def test_returns_false_before_request(self):
        assert is_shutdown_requested() is False

    def test_returns_true_after_request(self):
        request_shutdown()
        assert is_shutdown_requested() is True

class TestResetShutdown:

    def test_clears_flag(self):
        request_shutdown()
        assert is_shutdown_requested() is True
        reset_shutdown()
        assert is_shutdown_requested() is False

    def test_reset_when_already_clear(self):
        """Resetting an already-clear flag is a no-op."""
        reset_shutdown()
        assert is_shutdown_requested() is False

class TestRegisterSignalHandlers:

    def test_installs_sigterm_handler(self):
        register_signal_handlers()
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        assert handler is not signal.SIG_DFL
        assert handler is not signal.SIG_IGN

    def test_installs_sigint_handler(self):
        register_signal_handlers()
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)
        assert handler is not signal.SIG_DFL
        assert handler is not signal.SIG_IGN

class TestSignalHandlerBehavior:

    def test_sigterm_handler_triggers_shutdown(self):
        register_signal_handlers()
        handler = signal.getsignal(signal.SIGTERM)
        # Simulate calling the handler directly
        handler(signal.SIGTERM, None)
        assert is_shutdown_requested() is True

    def test_sigint_handler_triggers_shutdown(self):
        register_signal_handlers()
        handler = signal.getsignal(signal.SIGINT)
        handler(signal.SIGINT, None)
        assert is_shutdown_requested() is True

    def test_handler_is_idempotent(self):
        register_signal_handlers()
        handler = signal.getsignal(signal.SIGTERM)
        handler(signal.SIGTERM, None)
        handler(signal.SIGTERM, None)
        assert is_shutdown_requested() is True
