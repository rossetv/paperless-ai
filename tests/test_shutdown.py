import signal
from unittest.mock import patch

from common.shutdown import (
    is_shutdown_requested,
    register_signal_handlers,
    request_shutdown,
    reset_shutdown,
)


def setup_function():
    reset_shutdown()


def test_initial_state_is_not_shutdown():
    assert not is_shutdown_requested()


def test_request_shutdown_sets_flag():
    request_shutdown()
    assert is_shutdown_requested()


def test_reset_clears_flag():
    request_shutdown()
    reset_shutdown()
    assert not is_shutdown_requested()


def test_register_signal_handlers_installs_sigterm_and_sigint():
    with patch("common.shutdown.signal.signal") as mock_signal:
        register_signal_handlers()
        registered_signals = {call.args[0] for call in mock_signal.call_args_list}
        assert signal.SIGTERM in registered_signals
        assert signal.SIGINT in registered_signals


def test_signal_handler_sets_shutdown_flag():
    register_signal_handlers()
    # Simulate SIGTERM delivery by calling the registered handler directly
    handler = signal.getsignal(signal.SIGTERM)
    handler(signal.SIGTERM, None)
    assert is_shutdown_requested()
