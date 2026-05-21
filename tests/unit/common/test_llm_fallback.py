"""Tests for common.llm — model-fallback chain and retry/limiter integration.

Split from test_llm.py to stay within the §3.1 500-line ceiling.
Covers: OpenAIChatMixin._complete_with_model_fallback and the
retry-decorator + LLMConcurrencyLimiter interaction tests.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import openai
import pytest

from common.concurrency import LLMConcurrencyLimiter
from common.llm import (
    OpenAIChatMixin,
    _openai_holder,
)


class _TestClient(OpenAIChatMixin):
    """Concrete class to test the mixin."""

    def __init__(self, settings):
        self.settings = settings


def _completion(content: str | None) -> MagicMock:
    """Build an OpenAI-shaped chat completion whose message content is *content*."""
    choice = MagicMock()
    choice.message.content = content
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _api_error() -> openai.APIError:
    """Build a generic openai.APIError — the base of the OpenAI error tree."""
    return openai.APIError(message="boom", request=MagicMock(), body=None)


class TestCompleteWithModelFallback:
    """Tests for OpenAIChatMixin._complete_with_model_fallback.

    The shared model-fallback loop owns the chain that the planner and the
    synthesiser both use (CODE_GUIDELINES.md §8.1).  These tests pin it
    directly; the planner and synthesiser tests cover the same behaviour
    through their public ``plan`` / ``synthesise`` entry points.
    """

    @pytest.fixture()
    def client(self):
        settings = MagicMock()
        settings.MAX_RETRIES = 3
        settings.MAX_RETRY_BACKOFF_SECONDS = 30
        return _TestClient(settings)

    def test_returns_primary_model_content_on_success(self, client):
        """The first model's content is returned when the primary call succeeds."""
        client._create_completion = MagicMock(return_value=_completion("primary answer"))

        result = client._complete_with_model_fallback(
            primary_model="m1",
            messages=[{"role": "user", "content": "q"}],
            fallback_models=["m2", "m3"],
            log_event_prefix="planner",
        )

        assert result == "primary answer"
        assert client._create_completion.call_count == 1
        assert client._create_completion.call_args.kwargs["model"] == "m1"

    def test_falls_through_to_the_next_model_on_api_error(self, client):
        """An openai.APIError on a model skips it and tries the next."""
        client._create_completion = MagicMock(
            side_effect=[_api_error(), _completion("second answer")]
        )

        result = client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=["m2"],
            log_event_prefix="synthesiser",
        )

        assert result == "second answer"
        assert client._create_completion.call_count == 2

    def test_returns_none_when_every_model_fails(self, client):
        """When every model in the chain raises, the helper returns None."""
        client._create_completion = MagicMock(side_effect=_api_error())

        result = client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=["m2", "m3"],
            log_event_prefix="planner",
        )

        assert result is None
        # primary + 2 fallbacks = 3 attempts.
        assert client._create_completion.call_count == 3

    def test_primary_model_is_not_tried_twice(self, client):
        """A primary that also appears in the fallback list is deduplicated."""
        client._create_completion = MagicMock(side_effect=_api_error())

        client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=["m1", "m2"],
            log_event_prefix="planner",
        )

        # m1 is deduplicated against the fallback list — m1, m2 → 2 attempts.
        assert client._create_completion.call_count == 2
        models_tried = [
            call.kwargs["model"] for call in client._create_completion.call_args_list
        ]
        assert models_tried == ["m1", "m2"]

    def test_none_content_is_coerced_to_empty_string(self, client):
        """A successful call whose message content is None yields ''."""
        client._create_completion = MagicMock(return_value=_completion(None))

        result = client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=[],
            log_event_prefix="planner",
        )

        assert result == ""

    def test_non_retryable_api_error_is_caught(self, client):
        """A non-retryable openai.APIError subclass also skips the model."""
        response = MagicMock(status_code=401, headers={})
        auth_error = openai.AuthenticationError(
            message="bad key", response=response, body=None
        )
        client._create_completion = MagicMock(
            side_effect=[auth_error, _completion("recovered")]
        )

        result = client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=["m2"],
            log_event_prefix="synthesiser",
        )

        assert result == "recovered"

    def test_per_model_failure_is_logged_without_the_messages(self, client):
        """A skipped model logs a warning carrying the model name, not the prompt."""
        client._create_completion = MagicMock(side_effect=[_api_error(), _completion("ok")])

        with patch("common.llm.log") as mock_log:
            client._complete_with_model_fallback(
                primary_model="m1",
                messages=[{"role": "user", "content": "secret prompt"}],
                fallback_models=["m2"],
                log_event_prefix="planner",
            )

        mock_log.warning.assert_called_once()
        event, kwargs = mock_log.warning.call_args.args[0], mock_log.warning.call_args.kwargs
        assert event == "planner.model_failed"
        assert kwargs["model"] == "m1"


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
