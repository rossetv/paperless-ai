"""Tests for common.llm — unique_models, extract_json_object, and _create_completion.

Model-fallback and retry/limiter integration tests live in
test_llm_fallback.py (§3.1 500-line ceiling split).
"""

from __future__ import annotations

import itertools
import json
from unittest.mock import MagicMock, patch

import openai
import pytest

from common.llm import (
    OpenAIChatMixin,
    _STRIPPABLE_PARAMS,
    _strippable_param_for_error,
    _wait_for_flex_capacity,
    extract_json_object,
    service_tier_params,
    unique_models,
    _openai_holder,
)
from common.model_compat import model_compat_cache


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


class TestExtractJsonObject:
    """Tests for the shared extract_json_object(text) LLM-output parser."""

    def test_valid_json_object(self):
        assert extract_json_object('{"title": "Invoice"}') == {"title": "Invoice"}

    def test_json_in_markdown_fences(self):
        text = '```json\n{"title": "Invoice"}\n```'
        assert extract_json_object(text) == {"title": "Invoice"}

    def test_json_in_bare_fences(self):
        text = '```\n{"title": "Invoice"}\n```'
        assert extract_json_object(text) == {"title": "Invoice"}

    def test_json_with_preamble_text(self):
        text = 'Here is the classification:\n{"title": "Invoice", "tags": []}'
        assert extract_json_object(text) == {"title": "Invoice", "tags": []}

    def test_json_with_trailing_text(self):
        text = '{"title": "Test"}\nSome trailing text'
        assert extract_json_object(text) == {"title": "Test"}

    def test_nested_json(self):
        text = '{"outer": {"inner": 1}}'
        assert extract_json_object(text) == {"outer": {"inner": 1}}

    def test_strict_parse_accepts_a_bare_array(self):
        """The strict json.loads path accepts non-object JSON; callers type-check."""
        assert extract_json_object("[1, 2, 3]") == [1, 2, 3]

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json_object("this is not json at all")

    def test_empty_string_raises(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json_object("")

    def test_no_closing_brace_raises(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json_object('{"title": "Test"')

    def test_only_closing_brace_raises(self):
        """A closing brace before any opening brace is not recoverable."""
        with pytest.raises(json.JSONDecodeError):
            extract_json_object("} not json {")


class _TestClient(OpenAIChatMixin):
    """Concrete class to test the mixin."""

    def __init__(self, settings):
        self.settings = settings


class _ProviderAwareClient(OpenAIChatMixin):
    """A step that routes by its settings provider, like the real step providers."""

    def __init__(self, settings):
        self.settings = settings

    @property
    def _provider(self) -> str:
        return self.settings.OCR_PROVIDER


class TestProviderRouting:
    """A step's chat call routes to ITS provider's client, not a global one."""

    @pytest.fixture(autouse=True)
    def _restore_holder(self):
        orig = dict(_openai_holder._clients)
        yield
        _openai_holder._clients = dict(orig)

    @patch("common.llm.llm_limiter")
    def test_routes_to_the_steps_provider_client(self, mock_limiter):
        openai_client = MagicMock(name="openai_client")
        ollama_client = MagicMock(name="ollama_client")
        _openai_holder.init("openai", openai_client)
        _openai_holder.init("ollama", ollama_client)

        settings = MagicMock()
        settings.MAX_RETRIES = 3
        settings.MAX_RETRY_BACKOFF_SECONDS = 30
        settings.OCR_PROVIDER = "ollama"
        client = _ProviderAwareClient(settings)

        client._create_completion(model="gemma3:12b", messages=[])

        ollama_client.chat.completions.create.assert_called_once()
        openai_client.chat.completions.create.assert_not_called()

    @patch("common.llm.llm_limiter")
    def test_raises_when_the_steps_provider_client_is_absent(self, mock_limiter):
        _openai_holder.init("openai", MagicMock())
        _openai_holder.init("ollama", None)

        settings = MagicMock()
        settings.MAX_RETRIES = 3
        settings.MAX_RETRY_BACKOFF_SECONDS = 30
        settings.OCR_PROVIDER = "ollama"
        client = _ProviderAwareClient(settings)

        with pytest.raises(RuntimeError, match="ollama chat client not initialised"):
            client._create_completion(model="gemma3:12b", messages=[])


class TestCreateCompletion:
    @pytest.fixture()
    def client(self):
        settings = MagicMock()
        settings.MAX_RETRIES = 3
        settings.MAX_RETRY_BACKOFF_SECONDS = 30
        return _TestClient(settings)

    @pytest.fixture(autouse=True)
    def _restore_holder(self):
        """Save and restore the holder's client registry after each test."""
        orig = dict(_openai_holder._clients)
        yield
        _openai_holder._clients = dict(orig)

    @patch("common.llm.llm_limiter")
    def test_delegates_to_openai(self, mock_limiter, client):
        """_create_completion passes kwargs through to the OpenAI client."""
        mock_openai = MagicMock()
        expected = MagicMock()
        mock_openai.chat.completions.create.return_value = expected
        _openai_holder.init("openai", mock_openai)

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
        _openai_holder.init("openai", mock_openai)
        client._create_completion(model="m")

        mock_limiter.acquire.assert_called_once()

    @patch("common.llm.llm_limiter")
    def test_extra_kwargs_forwarded(self, mock_limiter, client):
        """All keyword arguments are forwarded to the OpenAI API."""
        mock_openai = MagicMock()
        _openai_holder.init("openai", mock_openai)

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
        _openai_holder._clients["openai"] = None
        with pytest.raises(RuntimeError, match="openai chat client not initialised"):
            client._create_completion(model="m")


def _bad_request(message: str) -> openai.BadRequestError:
    """Build an openai.BadRequestError carrying *message* (no token spent)."""
    response = MagicMock()
    response.status_code = 400
    response.headers = {}
    response.json.return_value = {"error": {"message": message}}
    return openai.BadRequestError(
        message=message,
        response=response,
        body={"error": {"message": message}},
    )


class TestStrippableParamForError:
    """_strippable_param_for_error names the param a 400 says is unsupported."""

    def test_temperature_unsupported(self):
        error = _bad_request("temperature is unsupported for this model")
        assert _strippable_param_for_error(error) == "temperature"

    def test_response_format_unsupported(self):
        error = _bad_request("response_format is not supported")
        assert _strippable_param_for_error(error) == "response_format"

    def test_json_schema_wording_maps_to_response_format(self):
        error = _bad_request("json_schema is not supported by this model")
        assert _strippable_param_for_error(error) == "response_format"

    def test_max_tokens_underscore_form(self):
        error = _bad_request("max_tokens is not supported")
        assert _strippable_param_for_error(error) == "max_tokens"

    def test_max_tokens_space_form(self):
        error = _bad_request("max tokens parameter not allowed")
        assert _strippable_param_for_error(error) == "max_tokens"

    def test_max_completion_tokens(self):
        error = _bad_request("max_completion_tokens is not supported")
        assert _strippable_param_for_error(error) == "max_completion_tokens"

    def test_reasoning_effort(self):
        error = _bad_request("reasoning_effort is not supported for this model")
        assert _strippable_param_for_error(error) == "reasoning_effort"

    def test_verbosity(self):
        error = _bad_request("verbosity is not a supported parameter")
        assert _strippable_param_for_error(error) == "verbosity"

    def test_unrelated_400_returns_none(self):
        error = _bad_request("messages: array too long")
        assert _strippable_param_for_error(error) is None

    def test_registry_param_keys_are_the_seven_documented(self):
        keys = {param_key for param_key, _, _ in _STRIPPABLE_PARAMS}
        assert keys == {
            "temperature",
            "response_format",
            "max_tokens",
            "max_completion_tokens",
            "reasoning_effort",
            "verbosity",
            "service_tier",
        }


class TestServiceTierParams:
    def test_flex_enabled_floors_timeout(self):
        assert service_tier_params(flex_enabled=True, request_timeout=180) == {
            "service_tier": "flex",
            "timeout": 600,
        }

    def test_flex_enabled_keeps_larger_operator_timeout(self):
        assert service_tier_params(flex_enabled=True, request_timeout=900) == {
            "service_tier": "flex",
            "timeout": 900,
        }

    def test_flex_disabled_is_standard_tier(self):
        assert service_tier_params(flex_enabled=False, request_timeout=180) == {
            "service_tier": "default",
            "timeout": 180,
        }


class _StatsClient(OpenAIChatMixin):
    """A mixin subclass that declares a subset of strip stat keys."""

    _STAT_KEYS = ("attempts", "api_errors", "temperature_retries")

    def __init__(self):
        self.settings = MagicMock()
        self._init_stats()


class _NoStatsClient(OpenAIChatMixin):
    """A mixin subclass with no stat keys (like the planner / synthesiser)."""

    _STAT_KEYS = ()

    def __init__(self):
        self.settings = MagicMock()
        self._init_stats()


class TestGuardedStatHelpers:
    """The shared compat layer records stats only when the key is declared."""

    def test_record_attempt_increments_declared_key(self):
        client = _StatsClient()
        client._record_attempt()
        assert client.get_stats()["attempts"] == 1

    def test_record_api_error_increments_declared_key(self):
        client = _StatsClient()
        client._record_api_error()
        assert client.get_stats()["api_errors"] == 1

    def test_record_strip_increments_declared_stat_key(self):
        client = _StatsClient()
        client._record_strip("temperature")
        assert client.get_stats()["temperature_retries"] == 1

    def test_record_strip_is_a_noop_for_undeclared_stat_key(self):
        client = _StatsClient()
        # verbosity_retries is not in _STAT_KEYS -> must not raise, must not add.
        client._record_strip("verbosity")
        assert "verbosity_retries" not in client.get_stats()

    def test_helpers_are_safe_when_no_stats_declared(self):
        client = _NoStatsClient()
        client._record_attempt()
        client._record_api_error()
        client._record_strip("temperature")
        assert client.get_stats() == {}


class _CompatClient(OpenAIChatMixin):
    """A mixin subclass for exercising _create_with_compat with strip stats."""

    _STAT_KEYS = (
        "attempts",
        "api_errors",
        "temperature_retries",
        "response_format_retries",
        "max_tokens_retries",
    )

    def __init__(self):
        self.settings = MagicMock()
        self._init_stats()


def _fake_completion(content: str) -> MagicMock:
    """An OpenAI-shaped completion carrying *content* as its message text."""
    choice = MagicMock()
    choice.message.content = content
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _ok_completion() -> MagicMock:
    """A successful OpenAI-shaped completion."""
    return _fake_completion("ok")


def _rate_limit_error(message: str = "rate limit reached") -> openai.RateLimitError:
    """Build an openai.RateLimitError carrying *message* (no token spent)."""
    response = MagicMock()
    response.status_code = 429
    response.headers = {}
    response.json.return_value = {"error": {"message": message}}
    return openai.RateLimitError(
        message=message,
        response=response,
        body={"error": {"message": message}},
    )


class TestCreateWithCompat:
    """OpenAIChatMixin._create_with_compat — adaptive strip-on-400 with cache."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        model_compat_cache.reset()
        yield
        model_compat_cache.reset()

    def test_passes_params_through_on_success(self):
        client = _CompatClient()
        client._create_completion = MagicMock(return_value=_ok_completion())

        result = client._create_with_compat(
            {"model": "m", "messages": [], "temperature": 0.2}, "m"
        )

        assert result is not None
        client._create_completion.assert_called_once_with(
            model="m", messages=[], temperature=0.2
        )

    def test_strips_temperature_on_400_and_retries(self):
        client = _CompatClient()
        client._create_completion = MagicMock(
            side_effect=[_bad_request("temperature is unsupported"), _ok_completion()]
        )

        result = client._create_with_compat(
            {"model": "m", "messages": [], "temperature": 0.2}, "m"
        )

        assert result is not None
        assert client._create_completion.call_count == 2
        # second call carries no temperature
        assert "temperature" not in client._create_completion.call_args.kwargs
        assert client.get_stats()["temperature_retries"] == 1

    def test_records_a_strip_in_the_cache(self):
        client = _CompatClient()
        client._create_completion = MagicMock(
            side_effect=[_bad_request("temperature is unsupported"), _ok_completion()]
        )

        client._create_with_compat(
            {"model": "m", "messages": [], "temperature": 0.2}, "m"
        )

        assert "temperature" in model_compat_cache.rejected_params_for("m")

    def test_pre_strips_a_cached_rejected_param_without_a_400(self):
        model_compat_cache.record_rejected("m", "temperature")
        client = _CompatClient()
        client._create_completion = MagicMock(return_value=_ok_completion())

        client._create_with_compat(
            {"model": "m", "messages": [], "temperature": 0.2}, "m"
        )

        # One call only — no wasted 400 round-trip — and temperature was pre-stripped.
        assert client._create_completion.call_count == 1
        assert "temperature" not in client._create_completion.call_args.kwargs

    def test_non_strippable_400_returns_none(self):
        client = _CompatClient()
        client._create_completion = MagicMock(
            side_effect=_bad_request("messages: array too long")
        )

        result = client._create_with_compat({"model": "m", "messages": []}, "m")

        assert result is None
        assert client.get_stats()["api_errors"] == 1

    def test_other_api_error_returns_none(self):
        client = _CompatClient()
        client._create_completion = MagicMock(
            side_effect=openai.APIError(message="boom", request=MagicMock(), body=None)
        )

        result = client._create_with_compat({"model": "m", "messages": []}, "m")

        assert result is None
        assert client.get_stats()["api_errors"] == 1

    def test_strip_loop_is_bounded_and_gives_up(self):
        """A 400 that always names a present param but never succeeds still ends."""
        client = _CompatClient()
        # Always rejects temperature; after stripping it, the SAME message no
        # longer matches a present param -> give up as api_error.
        client._create_completion = MagicMock(
            side_effect=_bad_request("temperature is unsupported")
        )

        result = client._create_with_compat(
            {"model": "m", "messages": [], "temperature": 0.2}, "m"
        )

        assert result is None
        assert client.get_stats()["temperature_retries"] == 1
        assert client.get_stats()["api_errors"] == 1
        # bounded: at most len(params)+1 attempts, never infinite.
        assert client._create_completion.call_count <= len(_STRIPPABLE_PARAMS) + 1

    def test_strips_three_distinct_params_across_three_400s(self):
        client = _CompatClient()
        client._create_completion = MagicMock(
            side_effect=[
                _bad_request("temperature is unsupported"),
                _bad_request("response_format not supported"),
                _bad_request("max_tokens not supported"),
                _ok_completion(),
            ]
        )

        result = client._create_with_compat(
            {
                "model": "m",
                "messages": [],
                "temperature": 0.2,
                "response_format": {"type": "json_schema"},
                "max_tokens": 500,
            },
            "m",
        )

        assert result is not None
        stats = client.get_stats()
        assert stats["temperature_retries"] == 1
        assert stats["response_format_retries"] == 1
        assert stats["max_tokens_retries"] == 1
        assert stats["attempts"] == 4


class TestFlexCapacityPatience:
    """_create_with_compat waits out RateLimitError on flex calls (spec D5)."""

    @pytest.fixture()
    def provider(self):
        model_compat_cache.reset()
        yield _CompatClient()
        model_compat_cache.reset()

    def test_flex_429_retries_until_success(self, provider, mocker):
        mocker.patch("common.llm._wait_for_flex_capacity", return_value=True)
        completion = _fake_completion("ok")
        provider._create_completion = mocker.Mock(
            side_effect=[_rate_limit_error(), _rate_limit_error(), completion]
        )
        result = provider._create_with_compat(
            {"model": "m", "messages": [], "service_tier": "flex"}, "m"
        )
        assert result is completion
        assert provider._create_completion.call_count == 3

    def test_flex_429_backoff_doubles_and_caps(self, provider, mocker):
        waits = mocker.patch("common.llm._wait_for_flex_capacity", return_value=True)
        provider._create_completion = mocker.Mock(
            side_effect=[_rate_limit_error()] * 8 + [_fake_completion("ok")]
        )
        provider._create_with_compat(
            {"model": "m", "messages": [], "service_tier": "flex"}, "m"
        )
        waited = [call.args[0] for call in waits.call_args_list]
        assert waited == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]

    def test_flex_429_aborts_on_shutdown(self, provider, mocker):
        mocker.patch("common.llm._wait_for_flex_capacity", return_value=False)
        provider._create_completion = mocker.Mock(side_effect=_rate_limit_error())
        result = provider._create_with_compat(
            {"model": "m", "messages": [], "service_tier": "flex"}, "m"
        )
        assert result is None

    def test_non_flex_429_stays_terminal(self, provider, mocker):
        wait = mocker.patch("common.llm._wait_for_flex_capacity")
        provider._create_completion = mocker.Mock(side_effect=_rate_limit_error())
        result = provider._create_with_compat({"model": "m", "messages": []}, "m")
        assert result is None
        wait.assert_not_called()

    def test_flex_quota_exhaustion_is_terminal_not_patient(self, provider, mocker):
        # insufficient_quota is also a 429, but no amount of waiting fixes an
        # empty account — the patient loop must not freeze the worker on it.
        wait = mocker.patch("common.llm._wait_for_flex_capacity")
        quota_error = openai.RateLimitError(
            message="You exceeded your current quota",
            response=MagicMock(status_code=429, headers={}),
            body={"code": "insufficient_quota"},
        )
        provider._create_completion = mocker.Mock(side_effect=quota_error)
        result = provider._create_with_compat(
            {"model": "m", "messages": [], "service_tier": "flex"}, "m"
        )
        assert result is None
        wait.assert_not_called()


class TestWaitForFlexCapacity:
    """_wait_for_flex_capacity — chunked sleep, shutdown-interruptible."""

    def test_returns_true_when_no_shutdown(self, mocker):
        mocker.patch("common.llm.is_shutdown_requested", return_value=False)
        sleep = mocker.patch("common.llm.time.sleep")
        counter = itertools.count()
        mocker.patch("common.llm.time.monotonic", side_effect=lambda: next(counter))
        assert _wait_for_flex_capacity(3.0) is True
        assert sleep.called

    def test_returns_false_immediately_on_shutdown(self, mocker):
        mocker.patch("common.llm.is_shutdown_requested", return_value=True)
        sleep = mocker.patch("common.llm.time.sleep")
        assert _wait_for_flex_capacity(3.0) is False
        sleep.assert_not_called()
