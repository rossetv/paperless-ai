"""Tests for the classifier.provider parameter-compatibility retries.

``_create_with_compat`` retries a model after stripping a parameter the model
rejected (temperature, response_format, max_tokens).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from classifier.taxonomy import TaxonomyContext
from common.model_compat import model_compat_cache
from tests.unit.classifier.conftest import (
    make_api_error,
    make_bad_request_error,
    make_completion_response,
    make_provider,
    valid_classification_json,
)

_EMPTY_TAXONOMY = TaxonomyContext(correspondents=[], document_types=[], tags=[])


@pytest.fixture(autouse=True)
def _reset_model_compat_cache():
    """The per-model compat cache is a process singleton; empty it per test."""
    model_compat_cache.reset()
    yield
    model_compat_cache.reset()


class TestTemperatureSentThenAdapted:
    """Temperature is sent to every model; a 400 rejecting it strips and caches it."""

    def test_temperature_is_sent_on_the_first_call_for_gpt5(self):
        provider = make_provider(CLASSIFY_MODELS=["gpt-5.4-mini"])
        response = make_completion_response(valid_classification_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        provider.classify_text("text", _EMPTY_TAXONOMY)

        # A real gpt-5 model would 400 here; the mock only proves it was sent.
        assert captured_kwargs["temperature"] == 0.2

    def test_temperature_is_included_for_non_gpt5_model(self):
        provider = make_provider(CLASSIFY_MODELS=["claude-3"])
        response = make_completion_response(valid_classification_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        provider.classify_text("text", _EMPTY_TAXONOMY)

        assert captured_kwargs["temperature"] == 0.2

    def test_gpt5_strips_temperature_after_one_400_then_caches_it(self):
        provider = make_provider(CLASSIFY_MODELS=["gpt-5.4-mini"])
        good = make_completion_response(valid_classification_json())
        calls: list[dict] = []

        def track(**kwargs):
            calls.append(dict(kwargs))
            if len(calls) == 1:
                raise make_bad_request_error("temperature is unsupported")
            return good

        provider._create_completion = track

        result, model = provider.classify_text("text", _EMPTY_TAXONOMY)

        assert result is not None
        assert "temperature" in calls[0]
        assert "temperature" not in calls[1]
        assert "temperature" in model_compat_cache.rejected_params_for("gpt-5.4-mini")


class TestMaxTokensHandling:
    def test_max_tokens_added_when_positive(self):
        provider = make_provider(CLASSIFY_MODELS=["claude-3"], CLASSIFY_MAX_TOKENS=500)
        response = make_completion_response(valid_classification_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        provider.classify_text("text", _EMPTY_TAXONOMY)

        assert captured_kwargs["max_tokens"] == 500

    def test_max_tokens_not_added_when_zero(self):
        provider = make_provider(CLASSIFY_MODELS=["claude-3"], CLASSIFY_MAX_TOKENS=0)
        response = make_completion_response(valid_classification_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        provider.classify_text("text", _EMPTY_TAXONOMY)

        assert "max_tokens" not in captured_kwargs


class TestCreateWithCompatTemperature:
    def test_strips_temperature_and_retries(self):
        provider = make_provider()
        provider._stats.reset(provider._STAT_KEYS)
        response = make_completion_response(valid_classification_json())
        error = make_bad_request_error("temperature is unsupported for this model")
        provider._create_completion = MagicMock(side_effect=[error, response])
        params = {"model": "m", "messages": [], "temperature": 0.2}

        result = provider._create_with_compat(params, "m")

        assert result is not None
        assert provider._create_completion.call_count == 2
        stats = provider.get_stats()
        assert stats["temperature_retries"] == 1

    def test_retried_call_has_no_temperature(self):
        provider = make_provider()
        response = make_completion_response()
        error = make_bad_request_error("temperature is unsupported for this model")
        calls = []

        def track_calls(**kwargs):
            calls.append(dict(kwargs))
            if len(calls) == 1:
                raise error
            return response

        provider._create_completion = track_calls
        provider._stats.reset(provider._STAT_KEYS)
        params = {"model": "m", "messages": [], "temperature": 0.2}

        provider._create_with_compat(params, "m")

        assert "temperature" in calls[0]
        assert "temperature" not in calls[1]


class TestCreateWithCompatResponseFormat:
    def test_strips_response_format_and_retries(self):
        provider = make_provider()
        response = make_completion_response()
        error = make_bad_request_error("response_format is not supported")
        provider._create_completion = MagicMock(side_effect=[error, response])
        provider._stats.reset(provider._STAT_KEYS)
        params = {
            "model": "m",
            "messages": [],
            "response_format": {"type": "json_schema"},
        }

        result = provider._create_with_compat(params, "m")

        assert result is not None
        assert provider.get_stats()["response_format_retries"] == 1

    def test_strips_response_format_on_json_schema_error(self):
        provider = make_provider()
        response = make_completion_response()
        error = make_bad_request_error("json_schema is not supported by this model")
        provider._create_completion = MagicMock(side_effect=[error, response])
        provider._stats.reset(provider._STAT_KEYS)
        params = {
            "model": "m",
            "messages": [],
            "response_format": {"type": "json_schema"},
        }

        result = provider._create_with_compat(params, "m")

        assert result is not None


class TestCreateWithCompatMaxTokens:
    def test_strips_max_tokens_and_retries(self):
        provider = make_provider()
        response = make_completion_response()
        error = make_bad_request_error("max_tokens is not supported")
        provider._create_completion = MagicMock(side_effect=[error, response])
        provider._stats.reset(provider._STAT_KEYS)
        params = {"model": "m", "messages": [], "max_tokens": 500}

        result = provider._create_with_compat(params, "m")

        assert result is not None
        assert provider.get_stats()["max_tokens_retries"] == 1

    def test_strips_max_tokens_on_space_form(self):
        provider = make_provider()
        response = make_completion_response()
        error = make_bad_request_error("max tokens parameter not allowed")
        provider._create_completion = MagicMock(side_effect=[error, response])
        provider._stats.reset(provider._STAT_KEYS)
        params = {"model": "m", "messages": [], "max_tokens": 500}

        result = provider._create_with_compat(params, "m")

        assert result is not None
        assert provider.get_stats()["max_tokens_retries"] == 1


class TestCreateWithCompatNon400:
    def test_generic_api_error_returns_none(self):
        provider = make_provider()
        provider._create_completion = MagicMock(side_effect=make_api_error())
        provider._stats.reset(provider._STAT_KEYS)
        params = {"model": "m", "messages": []}

        result = provider._create_with_compat(params, "m")

        assert result is None
        assert provider.get_stats()["api_errors"] == 1


class TestCreateWithCompatRetryExhaustion:
    def test_exhausts_all_compat_retries(self):
        # Every call fails with the same temperature 400.
        provider = make_provider()
        error = make_bad_request_error("temperature is unsupported for this model")
        provider._create_completion = MagicMock(side_effect=error)
        provider._stats.reset(provider._STAT_KEYS)
        params = {
            "model": "m",
            "messages": [],
            "temperature": 0.2,
            "response_format": {"type": "json_schema"},
            "max_tokens": 500,
        }

        result = provider._create_with_compat(params, "m")

        assert result is None
        stats = provider.get_stats()
        # Only temperature is stripped; the repeated error matches no other
        # parameter, so it falls through to api_errors.
        assert stats["temperature_retries"] == 1
        assert stats["api_errors"] == 1

    def test_three_different_compat_errors_all_stripped(self):
        provider = make_provider()
        response = make_completion_response()
        temp_error = make_bad_request_error("temperature is unsupported")
        fmt_error = make_bad_request_error("response_format not supported")
        tokens_error = make_bad_request_error("max_tokens not supported")
        provider._create_completion = MagicMock(
            side_effect=[temp_error, fmt_error, tokens_error, response]
        )
        provider._stats.reset(provider._STAT_KEYS)
        params = {
            "model": "m",
            "messages": [],
            "temperature": 0.2,
            "response_format": {"type": "json_schema"},
            "max_tokens": 500,
        }

        result = provider._create_with_compat(params, "m")

        assert result is not None
        stats = provider.get_stats()
        assert stats["temperature_retries"] == 1
        assert stats["response_format_retries"] == 1
        assert stats["max_tokens_retries"] == 1
        assert stats["attempts"] == 4

    def test_compat_retries_capped_at_three(self):
        """After 3 compat retries, further 400s are counted as api_errors."""
        provider = make_provider()
        temp_error = make_bad_request_error("temperature is unsupported")
        fmt_error = make_bad_request_error("response_format not supported")
        tokens_error = make_bad_request_error("max_tokens not supported")
        # 4th call: another bad request — retries exhausted
        fourth_error = make_bad_request_error("temperature is unsupported")
        provider._create_completion = MagicMock(
            side_effect=[temp_error, fmt_error, tokens_error, fourth_error]
        )
        provider._stats.reset(provider._STAT_KEYS)
        params = {
            "model": "m",
            "messages": [],
            "temperature": 0.2,
            "response_format": {"type": "json_schema"},
            "max_tokens": 500,
        }

        result = provider._create_with_compat(params, "m")

        assert result is None
        stats = provider.get_stats()
        assert stats["api_errors"] == 1


class TestResponseFormat:
    """response_format is only included for openai provider."""

    def test_response_format_included_for_openai(self):
        provider = make_provider(
            CLASSIFY_PROVIDER="openai", CLASSIFY_MODELS=["claude-3"]
        )
        response = make_completion_response(valid_classification_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        provider.classify_text("text", _EMPTY_TAXONOMY)

        assert "response_format" in captured_kwargs

    def test_response_format_excluded_for_ollama(self):
        provider = make_provider(CLASSIFY_PROVIDER="ollama", CLASSIFY_MODELS=["llama3"])
        response = make_completion_response(valid_classification_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        provider.classify_text("text", _EMPTY_TAXONOMY)

        assert "response_format" not in captured_kwargs


class TestReasoningEffort:
    """reasoning_effort is sent from settings and is strippable on rejection."""

    def test_reasoning_effort_sent_from_settings(self):
        # "medium" is the default effort; it must reach the outgoing params.
        provider = make_provider(
            CLASSIFY_MODELS=["gpt-5.4-mini"], CLASSIFY_REASONING_EFFORT="medium"
        )
        response = make_completion_response(valid_classification_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        provider.classify_text("text", _EMPTY_TAXONOMY)

        assert captured_kwargs["reasoning_effort"] == "medium"

    def test_reasoning_effort_uses_configured_value(self):
        provider = make_provider(
            CLASSIFY_MODELS=["gpt-5.4"], CLASSIFY_REASONING_EFFORT="high"
        )
        response = make_completion_response(valid_classification_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        provider.classify_text("text", _EMPTY_TAXONOMY)

        assert captured_kwargs["reasoning_effort"] == "high"

    def test_reasoning_effort_stripped_on_400_then_retried(self):
        provider = make_provider(CLASSIFY_MODELS=["gpt-5.4-mini"])
        response = make_completion_response(valid_classification_json())
        error = make_bad_request_error("Unsupported parameter: 'reasoning_effort'")
        calls: list[dict] = []

        def track_calls(**kwargs):
            calls.append(dict(kwargs))
            if len(calls) == 1:
                raise error
            return response

        provider._create_completion = track_calls

        result, _ = provider.classify_text("text", _EMPTY_TAXONOMY)

        assert result is not None
        assert "reasoning_effort" in calls[0]
        assert "reasoning_effort" not in calls[1]


class TestServiceTier:
    """service_tier is provider-gated like reasoning_effort; flex floors timeout."""

    def test_flex_on_openai_floors_timeout(self):
        provider = make_provider(
            CLASSIFY_PROVIDER="openai",
            CLASSIFY_MODELS=["gpt-5.4-mini"],
            OPENAI_FLEX_TIER=True,
            REQUEST_TIMEOUT=180,
        )

        params = provider._build_params("gpt-5.4-mini", [])

        assert params["service_tier"] == "flex"
        assert params["timeout"] == 600

    def test_flex_off_openai_is_default_tier(self):
        provider = make_provider(
            CLASSIFY_PROVIDER="openai",
            CLASSIFY_MODELS=["gpt-5.4-mini"],
            OPENAI_FLEX_TIER=False,
            REQUEST_TIMEOUT=180,
        )

        params = provider._build_params("gpt-5.4-mini", [])

        assert params["service_tier"] == "default"
        assert params["timeout"] == 180

    def test_omitted_for_non_openai(self):
        provider = make_provider(
            CLASSIFY_PROVIDER="ollama",
            CLASSIFY_MODELS=["llama3"],
            OPENAI_FLEX_TIER=True,
        )

        params = provider._build_params("llama3", [])

        assert "service_tier" not in params
