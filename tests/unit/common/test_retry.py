"""Tests for common.retry."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from common.retry import _sleep_backoff, retry

class _FakeSettings:
    """Minimal object satisfying the ``RetrySettings`` protocol."""

    def __init__(self, max_retries: int = 3, max_backoff: int = 30):
        self.MAX_RETRIES = max_retries
        self.MAX_RETRY_BACKOFF_SECONDS = max_backoff


class _Client:
    """Dummy class that hosts retry-decorated methods."""

    def __init__(self, settings: _FakeSettings | None = None):
        self.settings = settings or _FakeSettings()
        self._call_count = 0

    @retry(retryable_exceptions=(ConnectionError, TimeoutError))
    def flaky(self, value: str) -> str:
        """Flaky method that may raise ConnectionError."""
        self._call_count += 1
        return value

    @retry(retryable_exceptions=(ConnectionError,))
    def only_connection(self) -> str:
        self._call_count += 1
        return "ok"

class TestSuccessFirstAttempt:

    def test_returns_value_immediately(self):
        client = _Client()
        result = client.flaky("hello")
        assert result == "hello"
        assert client._call_count == 1

class TestRetryAfterTransientFailure:

    @patch("common.retry._sleep_backoff")
    def test_retries_then_succeeds(self, mock_sleep):
        call_count = 0

        def side_effect(self_inner, value):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return value

        with patch.object(
            _Client, "flaky",
            retry(retryable_exceptions=(ConnectionError, TimeoutError))(side_effect),
        ):
            c = _Client(_FakeSettings(max_retries=5))
            result = c.flaky("world")

        assert result == "world"
        assert call_count == 3
        assert mock_sleep.call_count == 2

    @patch("common.retry._sleep_backoff")
    def test_succeeds_on_last_attempt(self, mock_sleep):
        attempts = []

        def fragile(self_inner):
            attempts.append(1)
            if len(attempts) < 3:
                raise ConnectionError("oops")
            return "done"

        decorated = retry(retryable_exceptions=(ConnectionError,))(fragile)
        client = _Client(_FakeSettings(max_retries=3))
        result = decorated(client)

        assert result == "done"
        assert len(attempts) == 3

class TestExhaustedRetries:

    @patch("common.retry._sleep_backoff")
    def test_raises_after_all_retries(self, mock_sleep):
        def always_fail(self_inner):
            raise ConnectionError("persistent")

        decorated = retry(retryable_exceptions=(ConnectionError,))(always_fail)
        client = _Client(_FakeSettings(max_retries=3))

        with pytest.raises(ConnectionError, match="persistent"):
            decorated(client)

        assert mock_sleep.call_count == 2  # sleeps between attempts 1-2, 2-3

class TestInvalidMaxRetries:

    def test_zero_retries_raises(self):
        client = _Client(_FakeSettings(max_retries=0))
        with pytest.raises(ValueError, match="MAX_RETRIES must be >= 1"):
            client.flaky("x")

    def test_negative_retries_raises(self):
        client = _Client(_FakeSettings(max_retries=-1))
        with pytest.raises(ValueError, match="MAX_RETRIES must be >= 1"):
            client.flaky("x")

class TestExceptionFiltering:

    def test_non_retryable_exception_propagates_immediately(self):
        """ValueError is not retryable so it should not be caught."""
        call_count = 0

        def raise_value_error(self_inner):
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        decorated = retry(retryable_exceptions=(ConnectionError,))(raise_value_error)
        client = _Client(_FakeSettings(max_retries=5))

        with pytest.raises(ValueError, match="not retryable"):
            decorated(client)

        assert call_count == 1  # no retry attempted

    @patch("common.retry._sleep_backoff")
    def test_retryable_timeout_error(self, mock_sleep):
        """TimeoutError is retryable for the `flaky` method."""
        attempts = []

        def raise_timeout(self_inner, value):
            attempts.append(1)
            if len(attempts) < 2:
                raise TimeoutError("timeout")
            return value

        decorated = retry(retryable_exceptions=(ConnectionError, TimeoutError))(
            raise_timeout
        )
        client = _Client(_FakeSettings(max_retries=3))
        result = decorated(client, "ok")
        assert result == "ok"
        assert len(attempts) == 2

class TestSleepBackoff:

    @patch("common.retry.time.sleep")
    @patch("common.retry.random.uniform", return_value=1.0)
    def test_exponential_base(self, mock_uniform, mock_sleep):
        """With jitter fixed at 1.0, delay = 2^attempt."""
        settings = _FakeSettings(max_retries=5, max_backoff=1000)
        _sleep_backoff(1, settings)
        mock_sleep.assert_called_once()
        delay = mock_sleep.call_args[0][0]
        assert delay == pytest.approx(2.0)  # 2^1 * 1.0

    @patch("common.retry.time.sleep")
    @patch("common.retry.random.uniform", return_value=1.0)
    def test_exponential_attempt_3(self, mock_uniform, mock_sleep):
        settings = _FakeSettings(max_retries=5, max_backoff=1000)
        _sleep_backoff(3, settings)
        delay = mock_sleep.call_args[0][0]
        assert delay == pytest.approx(8.0)  # 2^3 * 1.0

    @patch("common.retry.time.sleep")
    @patch("common.retry.random.uniform", return_value=0.8)
    def test_jitter_lower_bound(self, mock_uniform, mock_sleep):
        settings = _FakeSettings(max_retries=5, max_backoff=1000)
        _sleep_backoff(2, settings)
        delay = mock_sleep.call_args[0][0]
        assert delay == pytest.approx(3.2)  # 2^2 * 0.8

    @patch("common.retry.time.sleep")
    @patch("common.retry.random.uniform", return_value=1.2)
    def test_jitter_upper_bound(self, mock_uniform, mock_sleep):
        settings = _FakeSettings(max_retries=5, max_backoff=1000)
        _sleep_backoff(2, settings)
        delay = mock_sleep.call_args[0][0]
        assert delay == pytest.approx(4.8)  # 2^2 * 1.2

    @patch("common.retry.time.sleep")
    @patch("common.retry.random.uniform", return_value=1.0)
    def test_uniform_called_with_correct_range(self, mock_uniform, mock_sleep):
        settings = _FakeSettings(max_retries=5, max_backoff=1000)
        _sleep_backoff(1, settings)
        mock_uniform.assert_called_once_with(0.8, 1.2)

class TestBackoffCap:

    @patch("common.retry.time.sleep")
    @patch("common.retry.random.uniform", return_value=1.0)
    def test_delay_capped(self, mock_uniform, mock_sleep):
        settings = _FakeSettings(max_retries=20, max_backoff=10)
        _sleep_backoff(10, settings)  # 2^10 = 1024, capped to 10
        delay = mock_sleep.call_args[0][0]
        assert delay == 10.0

    @patch("common.retry.time.sleep")
    @patch("common.retry.random.uniform", return_value=1.2)
    def test_delay_capped_with_jitter(self, mock_uniform, mock_sleep):
        settings = _FakeSettings(max_retries=20, max_backoff=5)
        _sleep_backoff(8, settings)  # 2^8 * 1.2 = 307.2, capped to 5
        delay = mock_sleep.call_args[0][0]
        assert delay == 5.0

class TestWraps:

    def test_function_name_preserved(self):
        # The method on the class should preserve the original name
        assert _Client.flaky.__name__ == "flaky"

    def test_docstring_preserved(self):
        assert "Flaky method" in (_Client.flaky.__doc__ or "")
