"""Tests for classifier.provider — the parameter-compatibility retry machinery.

``_create_with_compat`` retries a model after stripping a parameter the model
rejected (temperature, response_format, max_tokens).  Split from
``test_provider`` (the ``classify_text`` flow) for the 500-line ceiling
(CODE_GUIDELINES §3.1).
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
    """Each compat test starts with an empty per-model cache (process singleton)."""
    model_compat_cache.reset()
    yield
    model_compat_cache.reset()


class TestTemperatureNowAlwaysSentThenAdapted:
    """Temperature is no longer proactively withheld from gpt-5*; it is sent,
    and a 400 strips-and-caches it (spec §4.3 accepted behaviour change)."""

    def test_temperature_is_sent_on_the_first_call_for_gpt5(self):
        provider = make_provider(CLASSIFY_MODELS=["gpt-5.4-mini"])
        response = make_completion_response(valid_classification_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        provider.classify_text("text", _EMPTY_TAXONOMY)

        # First ever call for this model sends temperature (then a real model
        # would 400; the mock just succeeds, proving the param was present).
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
    """CLASSIFY_MAX_TOKENS > 0 adds max_tokens param."""

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
    """Strips temperature on 400 error mentioning 'temperature unsupported'."""

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
    """Strips response_format on 400 error mentioning 'response_format'."""

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
    """Strips max_tokens on 400 error mentioning 'max_tokens'."""

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
    """Non-BadRequestError (e.g. 500) is not retried via compat."""

    def test_generic_api_error_returns_none(self):
        provider = make_provider()
        provider._create_completion = MagicMock(side_effect=make_api_error())
        provider._stats.reset(provider._STAT_KEYS)
        params = {"model": "m", "messages": []}

        result = provider._create_with_compat(params, "m")

        assert result is None
        assert provider.get_stats()["api_errors"] == 1


class TestCreateWithCompatRetryExhaustion:
    """All compat params stripped but model still rejects — returns None."""

    def test_exhausts_all_compat_retries(self):
        # Arrange — always returns a 400 with temperature error
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
        # Only temperature is stripped (the error mentions temperature),
        # after stripping temperature the same error won't match response_format/max_tokens
        # so it falls through to api_errors
        assert stats["temperature_retries"] == 1
        assert stats["api_errors"] == 1

    def test_three_different_compat_errors_all_stripped(self):
        """Each call fails with a different parameter error, all three stripped."""
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
        # Default effort is "medium" (the models' own default); prove it flows
        # through to the outgoing params unchanged.
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
