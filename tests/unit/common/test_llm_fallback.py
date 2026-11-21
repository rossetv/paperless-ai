"""Tests for common.llm model fallback and retry/limiter integration."""

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
from common.model_compat import model_compat_cache


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
    """The model-fallback loop shared by the planner and the synthesiser."""

    @pytest.fixture()
    def client(self):
        settings = MagicMock()
        settings.MAX_RETRIES = 3
        settings.MAX_RETRY_BACKOFF_SECONDS = 30
        return _TestClient(settings)

    def test_returns_primary_model_content_on_success(self, client):
        client._create_completion = MagicMock(
            return_value=_completion("primary answer")
        )

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
        client._create_completion = MagicMock(return_value=_completion(None))

        result = client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=[],
            log_event_prefix="planner",
        )

        assert result == ""

    def test_non_retryable_api_error_is_caught(self, client):
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
        """A skipped model logs its name, never the prompt."""
        client._create_completion = MagicMock(
            side_effect=[_api_error(), _completion("ok")]
        )

        with patch("common.llm.log") as mock_log:
            client._complete_with_model_fallback(
                primary_model="m1",
                messages=[{"role": "user", "content": "secret prompt"}],
                fallback_models=["m2"],
                log_event_prefix="planner",
            )

        # A skipped model is logged by both the compat method (llm.model_failed)
        # and this loop (llm.fallback_model_failed); neither may carry the prompt.
        warning_calls = mock_log.warning.call_args_list
        events = [call.args[0] for call in warning_calls]
        assert "llm.fallback_model_failed" in events
        prefixed = next(
            call
            for call in warning_calls
            if call.args[0] == "llm.fallback_model_failed"
        )
        assert prefixed.kwargs["stage"] == "planner"
        assert prefixed.kwargs["model"] == "m1"
        # No warning anywhere leaks the prompt text.
        for call in warning_calls:
            assert "secret prompt" not in str(call)


class TestNoArgInvarianceCharacterisation:
    """With no optional kwargs the outgoing params are exactly ``{model, messages}``."""

    @pytest.fixture()
    def client(self):
        settings = MagicMock()
        settings.MAX_RETRIES = 3
        settings.MAX_RETRY_BACKOFF_SECONDS = 30
        return _TestClient(settings)

    def test_success_path_sends_only_model_and_messages(self, client):
        captured: list[dict] = []

        def capture(**kwargs):
            captured.append(dict(kwargs))
            return _completion("answer")

        client._create_completion = capture

        result = client._complete_with_model_fallback(
            primary_model="m1",
            messages=[{"role": "user", "content": "q"}],
            fallback_models=["m2"],
            log_event_prefix="planner",
        )

        assert result == "answer"
        assert captured == [
            {"model": "m1", "messages": [{"role": "user", "content": "q"}]}
        ]

    def test_all_models_fail_returns_none(self, client):
        client._create_completion = MagicMock(side_effect=_api_error())

        result = client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=["m2", "m3"],
            log_event_prefix="planner",
        )

        assert result is None
        assert client._create_completion.call_count == 3

    def test_first_success_wins_and_short_circuits(self, client):
        client._create_completion = MagicMock(
            side_effect=[_api_error(), _completion("second")]
        )

        result = client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=["m2", "m3"],
            log_event_prefix="planner",
        )

        assert result == "second"
        assert client._create_completion.call_count == 2


def _bad_request_fb(message: str) -> openai.BadRequestError:
    """openai.BadRequestError builder for the fallback tests (no token spent)."""
    response = MagicMock()
    response.status_code = 400
    response.headers = {}
    response.json.return_value = {"error": {"message": message}}
    return openai.BadRequestError(
        message=message,
        response=response,
        body={"error": {"message": message}},
    )


class TestCompleteWithModelFallbackOptionalKwargs:
    """The optional kwargs are forwarded through the compat layer."""

    @pytest.fixture()
    def client(self):
        settings = MagicMock()
        settings.MAX_RETRIES = 3
        settings.MAX_RETRY_BACKOFF_SECONDS = 30
        return _TestClient(settings)

    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        model_compat_cache.reset()
        yield
        model_compat_cache.reset()

    def test_reasoning_effort_is_forwarded(self, client):
        captured: list[dict] = []

        def capture(**kwargs):
            captured.append(dict(kwargs))
            return _completion("a")

        client._create_completion = capture

        client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=[],
            log_event_prefix="planner",
            reasoning_effort="low",
        )

        assert captured[0]["reasoning_effort"] == "low"

    def test_response_format_is_forwarded(self, client):
        captured: list[dict] = []

        def capture(**kwargs):
            captured.append(dict(kwargs))
            return _completion("a")

        client._create_completion = capture
        fmt = {"type": "json_object"}

        client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=[],
            log_event_prefix="synthesiser",
            response_format=fmt,
        )

        assert captured[0]["response_format"] == fmt

    def test_timeout_is_forwarded(self, client):
        captured: list[dict] = []

        def capture(**kwargs):
            captured.append(dict(kwargs))
            return _completion("a")

        client._create_completion = capture

        client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=[],
            log_event_prefix="planner",
            timeout=12.5,
        )

        assert captured[0]["timeout"] == 12.5

    def test_service_tier_is_forwarded(self, client):
        captured: list[dict] = []

        def capture(**kwargs):
            captured.append(dict(kwargs))
            return _completion("a")

        client._create_completion = capture

        client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=[],
            log_event_prefix="planner",
            service_tier="default",
        )

        assert captured[0]["service_tier"] == "default"

    def test_none_kwargs_are_omitted(self, client):
        captured: list[dict] = []

        def capture(**kwargs):
            captured.append(dict(kwargs))
            return _completion("a")

        client._create_completion = capture

        client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=[],
            log_event_prefix="planner",
            reasoning_effort=None,
            response_format=None,
            timeout=None,
            service_tier=None,
        )

        assert set(captured[0].keys()) == {"model", "messages"}

    def test_a_forwarded_param_is_stripped_via_compat_then_succeeds(self, client):
        client._create_completion = MagicMock(
            side_effect=[
                _bad_request_fb("reasoning_effort is not supported"),
                _completion("recovered"),
            ]
        )

        result = client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=[],
            log_event_prefix="planner",
            reasoning_effort="low",
        )

        assert result == "recovered"
        assert "reasoning_effort" in model_compat_cache.rejected_params_for("m1")

    def test_all_models_fail_through_compat_returns_none(self, client):
        client._create_completion = MagicMock(side_effect=_api_error())

        result = client._complete_with_model_fallback(
            primary_model="m1",
            messages=[],
            fallback_models=["m2"],
            log_event_prefix="planner",
            reasoning_effort="low",
        )

        assert result is None


class TestRetryLimiterIntegration:
    """A real limiter must be acquired and released on every retry attempt."""

    @pytest.fixture()
    def client(self):
        settings = MagicMock()
        settings.MAX_RETRIES = 3
        settings.MAX_RETRY_BACKOFF_SECONDS = 0
        return _TestClient(settings)

    @pytest.fixture(autouse=True)
    def _restore_holder(self):
        orig = dict(_openai_holder._clients)
        yield
        _openai_holder._clients = dict(orig)

    @pytest.fixture()
    def real_limiter(self):
        limiter = LLMConcurrencyLimiter()
        limiter.init(1)
        return limiter

    @patch("common.retry._sleep_backoff")
    def test_limiter_acquired_and_released_on_each_retry(
        self, mock_sleep, client, real_limiter
    ):
        mock_openai = MagicMock()
        _openai_holder.init("openai", mock_openai)

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
        mock_openai = MagicMock()
        _openai_holder.init("openai", mock_openai)

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

        assert acquire_count == 3
        assert release_count == 3

    @patch("common.retry._sleep_backoff")
    def test_api_call_happens_inside_limiter_context(self, mock_sleep, client):
        mock_openai = MagicMock()
        expected = MagicMock(name="chat_completion_result")
        mock_openai.chat.completions.create.return_value = expected
        _openai_holder.init("openai", mock_openai)

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
        mock_openai = MagicMock()
        _openai_holder.init("openai", mock_openai)

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
            "acquire",
            "api_call",
            "release",
            "acquire",
            "api_call",
            "release",
        ]

    @patch("common.retry._sleep_backoff")
    def test_semaphore_not_leaked_on_exception(self, mock_sleep, client, real_limiter):
        mock_openai = MagicMock()
        _openai_holder.init("openai", mock_openai)

        mock_openai.chat.completions.create.side_effect = openai.InternalServerError(
            message="server error",
            response=MagicMock(status_code=500),
            body=None,
        )

        with patch("common.llm.llm_limiter", real_limiter):
            with pytest.raises(openai.InternalServerError):
                client._create_completion(model="m")

        # With BoundedSemaphore(1) a non-blocking acquire succeeds only if none leaked.
        acquired = real_limiter._semaphore.acquire(blocking=False)
        assert acquired, (
            "Semaphore was leaked - could not re-acquire after all retries failed"
        )
        real_limiter._semaphore.release()
