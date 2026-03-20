"""Tests for common.llm."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch

import openai
import pytest

from common.concurrency import LLMConcurrencyLimiter
from common.llm import OpenAIChatMixin, unique_models, _openai_holder

class TestUniqueModels:

    def test_deduplicates_preserving_order(self):
        result = unique_models(["a", "b", "a", "c", "b"])
        assert result == ["a", "b", "c"]

    def test_empty_list(self):
        assert unique_models([]) == []

    def test_all_duplicates(self):
        result = unique_models(["x", "x", "x"])
        assert result == ["x"]

    def test_no_duplicates(self):
        result = unique_models(["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_single_element(self):
        assert unique_models(["only"]) == ["only"]

    def test_preserves_insertion_order(self):
        result = unique_models(["c", "b", "a", "c", "a"])
        assert result == ["c", "b", "a"]

class _TestClient(OpenAIChatMixin):
    """Concrete class to test the mixin."""

    def __init__(self, settings):
        self.settings = settings


class TestCreateCompletion:

    @pytest.fixture()
    def client(self):
        settings = MagicMock()
        settings.MAX_RETRIES = 3
        settings.MAX_RETRY_BACKOFF_SECONDS = 30
        return _TestClient(settings)

    @pytest.fixture(autouse=True)
    def _restore_holder(self):
        """Save and restore the holder's client after each test."""
        orig = _openai_holder._client
        yield
        _openai_holder._client = orig

    @patch("common.llm.llm_limiter")
    def test_delegates_to_openai(self, mock_limiter, client):
        """_create_completion passes kwargs through to the OpenAI client."""
        mock_openai = MagicMock()
        expected = MagicMock()
        mock_openai.chat.completions.create.return_value = expected
        _openai_holder.init(mock_openai)

        result = client._create_completion(
            model="gpt-5.4-mini",
            messages=[{"role": "user", "content": "hello"}],
        )

        assert result is expected
        mock_openai.chat.completions.create.assert_called_once_with(
            model="gpt-5.4-mini",
            messages=[{"role": "user", "content": "hello"}],
        )

    @patch("common.llm.llm_limiter")
    def test_uses_llm_limiter(self, mock_limiter, client):
        """_create_completion wraps the call in llm_limiter.acquire()."""
        mock_openai = MagicMock()
        _openai_holder.init(mock_openai)
        client._create_completion(model="m")

        mock_limiter.acquire.assert_called_once()

    @patch("common.llm.llm_limiter")
    def test_extra_kwargs_forwarded(self, mock_limiter, client):
        """All keyword arguments are forwarded to the OpenAI API."""
        mock_openai = MagicMock()
        _openai_holder.init(mock_openai)

        client._create_completion(
            model="gpt-5.4-mini",
            messages=[],
            temperature=0.5,
            max_tokens=100,
        )

        mock_openai.chat.completions.create.assert_called_once_with(
            model="gpt-5.4-mini",
            messages=[],
            temperature=0.5,
            max_tokens=100,
        )

    @patch("common.llm.llm_limiter")
    def test_raises_when_client_not_initialized(self, mock_limiter, client):
        """_create_completion raises RuntimeError when client is None."""
        _openai_holder._client = None
        with pytest.raises(RuntimeError, match="OpenAI client not initialised"):
            client._create_completion(model="m")


class TestRetryLimiterIntegration:
    """Integration tests for the retry decorator + LLMConcurrencyLimiter interaction.

    These tests use a *real* LLMConcurrencyLimiter (not a mock) so we can
    verify that the semaphore is correctly acquired and released on every
    attempt, including retries and failures.
    """

    @pytest.fixture()
    def client(self):
        settings = MagicMock()
        settings.MAX_RETRIES = 3
        settings.MAX_RETRY_BACKOFF_SECONDS = 0
        return _TestClient(settings)

    @pytest.fixture(autouse=True)
    def _restore_holder(self):
        orig = _openai_holder._client
        yield
        _openai_holder._client = orig

    @pytest.fixture()
    def real_limiter(self):
        """Create a real LLMConcurrencyLimiter with concurrency=1."""
        limiter = LLMConcurrencyLimiter()
        limiter.init(1)
        return limiter

    @patch("common.retry._sleep_backoff")
    def test_limiter_acquired_and_released_on_each_retry(
        self, mock_sleep, client, real_limiter
    ):
        """On each retry attempt the limiter semaphore is acquired then released."""
        mock_openai = MagicMock()
        _openai_holder.init(mock_openai)

        # Fail twice with a retryable error, succeed on the third attempt.
        expected = MagicMock(name="chat_completion_result")
        mock_openai.chat.completions.create.side_effect = [
            openai.APIConnectionError(request=MagicMock()),
            openai.APITimeoutError(request=MagicMock()),
            expected,
        ]

        # Track acquire/release calls on the underlying semaphore.
        sem = real_limiter._semaphore
        original_acquire = sem.acquire
        original_release = sem.release
        acquire_count = 0
        release_count = 0

        def tracking_acquire(*a, **kw):
            nonlocal acquire_count
            acquire_count += 1
            return original_acquire(*a, **kw)

        def tracking_release(*a, **kw):
            nonlocal release_count
            release_count += 1
            return original_release(*a, **kw)

        sem.acquire = tracking_acquire
        sem.release = tracking_release

        with patch("common.llm.llm_limiter", real_limiter):
            result = client._create_completion(model="m")

        assert result is expected
        # 3 attempts = 3 acquires and 3 releases (2 failures + 1 success).
        assert acquire_count == 3
        assert release_count == 3
        assert mock_openai.chat.completions.create.call_count == 3

    @patch("common.retry._sleep_backoff")
    def test_limiter_released_on_final_failure(self, mock_sleep, client, real_limiter):
        """When all retries are exhausted the limiter is still released every time."""
        mock_openai = MagicMock()
        _openai_holder.init(mock_openai)

        mock_openai.chat.completions.create.side_effect = openai.APIConnectionError(
            request=MagicMock()
        )

        sem = real_limiter._semaphore
        original_acquire = sem.acquire
        original_release = sem.release
        acquire_count = 0
        release_count = 0

        def tracking_acquire(*a, **kw):
            nonlocal acquire_count
            acquire_count += 1
            return original_acquire(*a, **kw)

        def tracking_release(*a, **kw):
            nonlocal release_count
            release_count += 1
            return original_release(*a, **kw)

        sem.acquire = tracking_acquire
        sem.release = tracking_release

        with patch("common.llm.llm_limiter", real_limiter):
            with pytest.raises(openai.APIConnectionError):
                client._create_completion(model="m")

        # All 3 attempts should acquire and release, even though all failed.
        assert acquire_count == 3
        assert release_count == 3

    @patch("common.retry._sleep_backoff")
    def test_api_call_happens_inside_limiter_context(
        self, mock_sleep, client
    ):
        """The OpenAI API call occurs strictly inside the limiter context manager."""
        mock_openai = MagicMock()
        expected = MagicMock(name="chat_completion_result")
        mock_openai.chat.completions.create.return_value = expected
        _openai_holder.init(mock_openai)

        call_log: list[str] = []

        class OrderTrackingLimiter:
            """A fake limiter that records acquire/release ordering."""

            _initialized = True
            _semaphore = True  # truthy so the branch enters the semaphore path

            @contextmanager
            def acquire(self):
                call_log.append("acquire")
                try:
                    yield
                finally:
                    call_log.append("release")

        # Wrap the real create to log when the API call happens.
        original_create = mock_openai.chat.completions.create

        def logging_create(**kwargs):
            call_log.append("api_call")
            return original_create(**kwargs)

        mock_openai.chat.completions.create = logging_create

        with patch("common.llm.llm_limiter", OrderTrackingLimiter()):
            result = client._create_completion(model="m")

        assert result is expected
        assert call_log == ["acquire", "api_call", "release"]

    @patch("common.retry._sleep_backoff")
    def test_retry_reacquires_limiter_each_attempt(self, mock_sleep, client):
        """Each retry attempt goes through the full acquire-call-release cycle."""
        mock_openai = MagicMock()
        _openai_holder.init(mock_openai)

        expected = MagicMock(name="chat_completion_result")
        mock_openai.chat.completions.create.side_effect = [
            openai.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429),
                body=None,
            ),
            expected,
        ]

        call_log: list[str] = []

        class OrderTrackingLimiter:
            _initialized = True
            _semaphore = True

            @contextmanager
            def acquire(self):
                call_log.append("acquire")
                try:
                    yield
                finally:
                    call_log.append("release")

        original_create = mock_openai.chat.completions.create

        def logging_create(**kwargs):
            call_log.append("api_call")
            return original_create(**kwargs)

        mock_openai.chat.completions.create = logging_create

        with patch("common.llm.llm_limiter", OrderTrackingLimiter()):
            result = client._create_completion(model="m")

        assert result is expected
        # First attempt: acquire, api_call (raises), release
        # Second attempt: acquire, api_call (succeeds), release
        assert call_log == [
            "acquire", "api_call", "release",
            "acquire", "api_call", "release",
        ]

    @patch("common.retry._sleep_backoff")
    def test_semaphore_not_leaked_on_exception(self, mock_sleep, client, real_limiter):
        """After all retries fail, the semaphore is fully released (not leaked)."""
        mock_openai = MagicMock()
        _openai_holder.init(mock_openai)

        mock_openai.chat.completions.create.side_effect = openai.InternalServerError(
            message="server error",
            response=MagicMock(status_code=500),
            body=None,
        )

        with patch("common.llm.llm_limiter", real_limiter):
            with pytest.raises(openai.InternalServerError):
                client._create_completion(model="m")

        # The semaphore should be fully available again (not leaked).
        # With BoundedSemaphore(1), we can acquire once more without blocking.
        acquired = real_limiter._semaphore.acquire(blocking=False)
        assert acquired, "Semaphore was leaked - could not re-acquire after all retries failed"
        real_limiter._semaphore.release()
