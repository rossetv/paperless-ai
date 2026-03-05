"""
Tests for classifier.provider — ClassificationProvider
=======================================================

Covers model fallback, parameter compatibility, JSON parsing errors,
temperature/response_format/max_tokens stripping, stats tracking, and
edge cases (empty text, whitespace, content=None, truncation notes).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import openai

from classifier.provider import ClassificationProvider
from classifier.result import ClassificationResult
from tests.helpers.factories import make_settings_obj


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider(**settings_overrides) -> ClassificationProvider:
    """Create a ClassificationProvider with a mock Settings object."""
    settings = make_settings_obj(**settings_overrides)
    return ClassificationProvider(settings)


def _make_response(content: str = "") -> MagicMock:
    """Build a fake OpenAI chat completion response."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def _valid_json(**overrides) -> str:
    """Return a valid classification JSON string."""
    data = {
        "title": "Test Invoice",
        "correspondent": "Acme Corp",
        "tags": ["invoice", "2025"],
        "document_date": "2025-01-15",
        "document_type": "Invoice",
        "language": "en",
        "person": "",
    }
    data.update(overrides)
    return json.dumps(data)


def _bad_request_error(message: str) -> openai.BadRequestError:
    """Create a BadRequestError with the given message."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.headers = {}
    mock_response.json.return_value = {"error": {"message": message}}
    return openai.BadRequestError(
        message=message,
        response=mock_response,
        body={"error": {"message": message}},
    )


def _api_error(message: str = "Server error") -> openai.APIError:
    """Create a generic APIError."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.headers = {}
    return openai.APIError(
        message=message,
        request=MagicMock(),
        body=None,
    )


# ===================================================================
# classify_text — happy path
# ===================================================================

class TestClassifyTextHappyPath:
    """Successful classification on the first model."""

    def test_returns_result_and_model_on_first_try(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["gpt-5-mini"])
        response = _make_response(_valid_json())
        provider._create_completion = MagicMock(return_value=response)

        # Act
        result, model = provider.classify_text(
            "Some document text", ["Acme"], ["Invoice"], ["bills"]
        )

        # Assert
        assert isinstance(result, ClassificationResult)
        assert result.title == "Test Invoice"
        assert model == "gpt-5-mini"

    def test_stats_show_single_attempt(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["gpt-5-mini"])
        response = _make_response(_valid_json())
        provider._create_completion = MagicMock(return_value=response)

        # Act
        provider.classify_text("text", [], [], [])

        # Assert
        stats = provider.get_stats()
        assert stats["attempts"] == 1
        assert stats["api_errors"] == 0
        assert stats["fallback_successes"] == 0


# ===================================================================
# classify_text — fallback on invalid JSON
# ===================================================================

class TestClassifyTextInvalidJsonFallback:
    """Fallback to the next model when JSON parsing fails."""

    def test_falls_back_on_invalid_json(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["model-a", "model-b"])
        bad_response = _make_response("NOT JSON AT ALL")
        good_response = _make_response(_valid_json())
        provider._create_completion = MagicMock(
            side_effect=[bad_response, good_response]
        )

        # Act
        result, model = provider.classify_text("text", [], [], [])

        # Assert
        assert result is not None
        assert model == "model-b"
        stats = provider.get_stats()
        assert stats["invalid_json"] == 1
        assert stats["fallback_successes"] == 1

    def test_content_none_treated_as_invalid_json(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["model-a", "model-b"])
        none_response = _make_response(None)
        # content=None means message.content returns None, provider does `or ""`
        none_response.choices[0].message.content = None
        good_response = _make_response(_valid_json())
        provider._create_completion = MagicMock(
            side_effect=[none_response, good_response]
        )

        # Act
        result, model = provider.classify_text("text", [], [], [])

        # Assert
        assert result is not None
        assert model == "model-b"
        assert provider.get_stats()["invalid_json"] == 1


# ===================================================================
# classify_text — fallback on API error
# ===================================================================

class TestClassifyTextApiErrorFallback:
    """Fallback when _create_with_compat returns None (API error)."""

    def test_falls_back_on_api_error(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["model-a", "model-b"])
        good_response = _make_response(_valid_json())
        provider._create_completion = MagicMock(
            side_effect=[_api_error(), good_response]
        )

        # Act
        result, model = provider.classify_text("text", [], [], [])

        # Assert
        assert result is not None
        assert model == "model-b"
        stats = provider.get_stats()
        assert stats["api_errors"] == 1
        assert stats["fallback_successes"] == 1


# ===================================================================
# classify_text — all models fail
# ===================================================================

class TestClassifyTextAllModelsFail:
    """When every model fails, returns (None, "")."""

    def test_returns_none_when_all_fail(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["model-a", "model-b"])
        provider._create_completion = MagicMock(side_effect=_api_error())

        # Act
        result, model = provider.classify_text("text", [], [], [])

        # Assert
        assert result is None
        assert model == ""

    def test_returns_none_when_all_return_invalid_json(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["model-a", "model-b"])
        bad_response = _make_response("garbage")
        provider._create_completion = MagicMock(return_value=bad_response)

        # Act
        result, model = provider.classify_text("text", [], [], [])

        # Assert
        assert result is None
        assert model == ""
        assert provider.get_stats()["invalid_json"] == 2


# ===================================================================
# classify_text — empty / whitespace text
# ===================================================================

class TestClassifyTextEmptyInput:
    """Empty or whitespace-only text should short-circuit."""

    def test_empty_string_returns_none(self):
        # Arrange
        provider = _make_provider()

        # Act
        result, model = provider.classify_text("", [], [], [])

        # Assert
        assert result is None
        assert model == ""

    def test_whitespace_only_returns_none(self):
        # Arrange
        provider = _make_provider()

        # Act
        result, model = provider.classify_text("   \n\t  ", [], [], [])

        # Assert
        assert result is None
        assert model == ""

    def test_no_api_call_on_empty_text(self):
        # Arrange
        provider = _make_provider()
        provider._create_completion = MagicMock()

        # Act
        provider.classify_text("   ", [], [], [])

        # Assert
        provider._create_completion.assert_not_called()


# ===================================================================
# classify_text — truncation note
# ===================================================================

class TestClassifyTextTruncationNote:
    """Truncation note is appended to the user message."""

    def test_truncation_note_included_in_message(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["gpt-5-mini"])
        response = _make_response(_valid_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        # Act
        provider.classify_text(
            "text", ["Acme"], ["Invoice"], ["tag"],
            truncation_note="NOTE: Truncated to 3 pages."
        )

        # Assert
        user_msg = captured_kwargs["messages"][1]["content"]
        assert "NOTE: Truncated to 3 pages." in user_msg

    def test_no_truncation_note_when_none(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["gpt-5-mini"])
        response = _make_response(_valid_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        # Act
        provider.classify_text("text", [], [], [], truncation_note=None)

        # Assert
        user_msg = captured_kwargs["messages"][1]["content"]
        assert "NOTE:" not in user_msg


# ===================================================================
# Temperature handling
# ===================================================================

class TestTemperatureHandling:
    """GPT-5 models skip temperature; others include it."""

    def test_temperature_omitted_for_gpt5_model(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["gpt-5-mini"])
        response = _make_response(_valid_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        # Act
        provider.classify_text("text", [], [], [])

        # Assert
        assert "temperature" not in captured_kwargs

    def test_temperature_included_for_non_gpt5_model(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["claude-3"])
        response = _make_response(_valid_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        # Act
        provider.classify_text("text", [], [], [])

        # Assert
        assert "temperature" in captured_kwargs
        assert captured_kwargs["temperature"] == 0.2


# ===================================================================
# max_tokens handling
# ===================================================================

class TestMaxTokensHandling:
    """CLASSIFY_MAX_TOKENS > 0 adds max_tokens param."""

    def test_max_tokens_added_when_positive(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["claude-3"], CLASSIFY_MAX_TOKENS=500)
        response = _make_response(_valid_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        # Act
        provider.classify_text("text", [], [], [])

        # Assert
        assert captured_kwargs["max_tokens"] == 500

    def test_max_tokens_not_added_when_zero(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["claude-3"], CLASSIFY_MAX_TOKENS=0)
        response = _make_response(_valid_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        # Act
        provider.classify_text("text", [], [], [])

        # Assert
        assert "max_tokens" not in captured_kwargs


# ===================================================================
# _create_with_compat — parameter stripping
# ===================================================================

class TestCreateWithCompatTemperature:
    """Strips temperature on 400 error mentioning 'temperature unsupported'."""

    def test_strips_temperature_and_retries(self):
        # Arrange
        provider = _make_provider()
        provider._stats.reset(provider._STAT_KEYS)
        response = _make_response(_valid_json())
        error = _bad_request_error("temperature is unsupported for this model")
        provider._create_completion = MagicMock(side_effect=[error, response])
        params = {"model": "m", "messages": [], "temperature": 0.2}

        # Act
        result = provider._create_with_compat(params, "m")

        # Assert
        assert result is not None
        assert provider._create_completion.call_count == 2
        stats = provider.get_stats()
        assert stats["temperature_retries"] == 1

    def test_retried_call_has_no_temperature(self):
        # Arrange
        provider = _make_provider()
        response = _make_response()
        error = _bad_request_error("temperature is unsupported for this model")
        calls = []

        def track_calls(**kwargs):
            calls.append(dict(kwargs))
            if len(calls) == 1:
                raise error
            return response

        provider._create_completion = track_calls
        provider._stats.reset(provider._STAT_KEYS)
        params = {"model": "m", "messages": [], "temperature": 0.2}

        # Act
        provider._create_with_compat(params, "m")

        # Assert
        assert "temperature" in calls[0]
        assert "temperature" not in calls[1]


class TestCreateWithCompatResponseFormat:
    """Strips response_format on 400 error mentioning 'response_format'."""

    def test_strips_response_format_and_retries(self):
        # Arrange
        provider = _make_provider()
        response = _make_response()
        error = _bad_request_error("response_format is not supported")
        provider._create_completion = MagicMock(side_effect=[error, response])
        provider._stats.reset(provider._STAT_KEYS)
        params = {"model": "m", "messages": [], "response_format": {"type": "json_schema"}}

        # Act
        result = provider._create_with_compat(params, "m")

        # Assert
        assert result is not None
        assert provider.get_stats()["response_format_retries"] == 1

    def test_strips_response_format_on_json_schema_error(self):
        # Arrange
        provider = _make_provider()
        response = _make_response()
        error = _bad_request_error("json_schema is not supported by this model")
        provider._create_completion = MagicMock(side_effect=[error, response])
        provider._stats.reset(provider._STAT_KEYS)
        params = {"model": "m", "messages": [], "response_format": {"type": "json_schema"}}

        # Act
        result = provider._create_with_compat(params, "m")

        # Assert
        assert result is not None


class TestCreateWithCompatMaxTokens:
    """Strips max_tokens on 400 error mentioning 'max_tokens'."""

    def test_strips_max_tokens_and_retries(self):
        # Arrange
        provider = _make_provider()
        response = _make_response()
        error = _bad_request_error("max_tokens is not supported")
        provider._create_completion = MagicMock(side_effect=[error, response])
        provider._stats.reset(provider._STAT_KEYS)
        params = {"model": "m", "messages": [], "max_tokens": 500}

        # Act
        result = provider._create_with_compat(params, "m")

        # Assert
        assert result is not None
        assert provider.get_stats()["max_tokens_retries"] == 1

    def test_strips_max_tokens_on_space_form(self):
        # Arrange — "max tokens" with a space
        provider = _make_provider()
        response = _make_response()
        error = _bad_request_error("max tokens parameter not allowed")
        provider._create_completion = MagicMock(side_effect=[error, response])
        provider._stats.reset(provider._STAT_KEYS)
        params = {"model": "m", "messages": [], "max_tokens": 500}

        # Act
        result = provider._create_with_compat(params, "m")

        # Assert
        assert result is not None
        assert provider.get_stats()["max_tokens_retries"] == 1


class TestCreateWithCompatNon400:
    """Non-BadRequestError (e.g. 500) is not retried via compat."""

    def test_generic_api_error_returns_none(self):
        # Arrange
        provider = _make_provider()
        provider._create_completion = MagicMock(side_effect=_api_error())
        provider._stats.reset(provider._STAT_KEYS)
        params = {"model": "m", "messages": []}

        # Act
        result = provider._create_with_compat(params, "m")

        # Assert
        assert result is None
        assert provider.get_stats()["api_errors"] == 1


class TestCreateWithCompatRetryExhaustion:
    """All compat params stripped but model still rejects — returns None."""

    def test_exhausts_all_compat_retries(self):
        # Arrange — always returns a 400 with temperature error
        provider = _make_provider()
        error = _bad_request_error("temperature is unsupported for this model")
        provider._create_completion = MagicMock(side_effect=error)
        provider._stats.reset(provider._STAT_KEYS)
        params = {
            "model": "m",
            "messages": [],
            "temperature": 0.2,
            "response_format": {"type": "json_schema"},
            "max_tokens": 500,
        }

        # Act
        result = provider._create_with_compat(params, "m")

        # Assert
        assert result is None
        stats = provider.get_stats()
        # Only temperature is stripped (the error mentions temperature),
        # after stripping temperature the same error won't match response_format/max_tokens
        # so it falls through to api_errors
        assert stats["temperature_retries"] == 1
        assert stats["api_errors"] == 1

    def test_three_different_compat_errors_all_stripped(self):
        """Each call fails with a different parameter error, all three stripped."""
        # Arrange
        provider = _make_provider()
        response = _make_response()
        temp_error = _bad_request_error("temperature is unsupported")
        fmt_error = _bad_request_error("response_format not supported")
        tokens_error = _bad_request_error("max_tokens not supported")
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

        # Act
        result = provider._create_with_compat(params, "m")

        # Assert
        assert result is not None
        stats = provider.get_stats()
        assert stats["temperature_retries"] == 1
        assert stats["response_format_retries"] == 1
        assert stats["max_tokens_retries"] == 1
        assert stats["attempts"] == 4

    def test_compat_retries_capped_at_three(self):
        """After 3 compat retries, further 400s are counted as api_errors."""
        # Arrange
        provider = _make_provider()
        temp_error = _bad_request_error("temperature is unsupported")
        fmt_error = _bad_request_error("response_format not supported")
        tokens_error = _bad_request_error("max_tokens not supported")
        # 4th call: another bad request — retries exhausted
        fourth_error = _bad_request_error("temperature is unsupported")
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

        # Act
        result = provider._create_with_compat(params, "m")

        # Assert
        assert result is None
        stats = provider.get_stats()
        assert stats["api_errors"] == 1


# ===================================================================
# Stats tracking
# ===================================================================

class TestStatsTracking:
    """get_stats returns accurate counters."""

    def test_stats_reset_on_each_call(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["model-a"])
        response = _make_response(_valid_json())
        provider._create_completion = MagicMock(return_value=response)

        # Act — two successive classify_text calls
        provider.classify_text("text", [], [], [])
        provider.classify_text("text", [], [], [])

        # Assert — stats reflect only the second call
        stats = provider.get_stats()
        assert stats["attempts"] == 1

    def test_stats_empty_before_any_call(self):
        # Arrange
        provider = _make_provider()

        # Act
        stats = provider.get_stats()

        # Assert
        assert all(v == 0 for v in stats.values())


# ===================================================================
# Response format (provider-specific)
# ===================================================================

class TestResponseFormat:
    """response_format is only included for openai provider."""

    def test_response_format_included_for_openai(self):
        # Arrange
        provider = _make_provider(LLM_PROVIDER="openai", AI_MODELS=["claude-3"])
        response = _make_response(_valid_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        # Act
        provider.classify_text("text", [], [], [])

        # Assert
        assert "response_format" in captured_kwargs

    def test_response_format_excluded_for_ollama(self):
        # Arrange
        provider = _make_provider(LLM_PROVIDER="ollama", AI_MODELS=["llama3"])
        response = _make_response(_valid_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        # Act
        provider.classify_text("text", [], [], [])

        # Assert
        assert "response_format" not in captured_kwargs


# ===================================================================
# Duplicate model deduplication
# ===================================================================

class TestModelDeduplication:
    """Duplicate models in AI_MODELS are tried only once."""

    def test_duplicate_models_deduplicated(self):
        # Arrange
        provider = _make_provider(AI_MODELS=["model-a", "model-a", "model-b"])
        provider._create_completion = MagicMock(side_effect=_api_error())

        # Act
        provider.classify_text("text", [], [], [])

        # Assert — only 2 unique models tried
        assert provider.get_stats()["attempts"] == 2
