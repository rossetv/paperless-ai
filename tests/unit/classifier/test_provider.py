"""Tests for classifier.provider — the ``classify_text`` model-fallback flow.

The parameter-compatibility retry machinery (``_create_with_compat`` and the
temperature / response-format / max-tokens stripping) is covered in
``test_provider_compat``; this file is split off it for the 500-line ceiling
(CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from classifier.result import ClassificationResult
from classifier.taxonomy import TaxonomyContext
from tests.unit.classifier.conftest import (
    make_api_error,
    make_completion_response,
    make_provider,
    valid_classification_json,
)

_EMPTY_TAXONOMY = TaxonomyContext(correspondents=[], document_types=[], tags=[])


class TestClassifyTextHappyPath:
    """Successful classification on the first model."""

    def test_returns_result_and_model_on_first_try(self):
        provider = make_provider(AI_MODELS=["gpt-5.4-mini"])
        response = make_completion_response(valid_classification_json())
        provider._create_completion = MagicMock(return_value=response)

        result, model = provider.classify_text(
            "Some document text",
            TaxonomyContext(correspondents=["Acme"], document_types=["Invoice"], tags=["bills"]),
        )

        assert isinstance(result, ClassificationResult)
        assert result.title == "Test Invoice"
        assert model == "gpt-5.4-mini"

    def test_stats_show_single_attempt(self):
        provider = make_provider(AI_MODELS=["gpt-5.4-mini"])
        response = make_completion_response(valid_classification_json())
        provider._create_completion = MagicMock(return_value=response)

        provider.classify_text("text", _EMPTY_TAXONOMY)

        stats = provider.get_stats()
        assert stats["attempts"] == 1
        assert stats["api_errors"] == 0
        assert stats["fallback_successes"] == 0

class TestClassifyTextInvalidJsonFallback:
    """Fallback to the next model when JSON parsing fails."""

    def test_falls_back_on_invalid_json(self):
        provider = make_provider(AI_MODELS=["model-a", "model-b"])
        bad_response = make_completion_response("NOT JSON AT ALL")
        good_response = make_completion_response(valid_classification_json())
        provider._create_completion = MagicMock(
            side_effect=[bad_response, good_response]
        )

        result, model = provider.classify_text("text", _EMPTY_TAXONOMY)

        assert result is not None
        assert model == "model-b"
        stats = provider.get_stats()
        assert stats["invalid_json"] == 1
        assert stats["fallback_successes"] == 1

    def test_content_none_treated_as_invalid_json(self):
        provider = make_provider(AI_MODELS=["model-a", "model-b"])
        none_response = make_completion_response(None)
        # content=None means message.content returns None, provider does `or ""`
        none_response.choices[0].message.content = None
        good_response = make_completion_response(valid_classification_json())
        provider._create_completion = MagicMock(
            side_effect=[none_response, good_response]
        )

        result, model = provider.classify_text("text", _EMPTY_TAXONOMY)

        assert result is not None
        assert model == "model-b"
        assert provider.get_stats()["invalid_json"] == 1

class TestClassifyTextApiErrorFallback:
    """Fallback when _create_with_compat returns None (API error)."""

    def test_falls_back_on_api_error(self):
        provider = make_provider(AI_MODELS=["model-a", "model-b"])
        good_response = make_completion_response(valid_classification_json())
        provider._create_completion = MagicMock(
            side_effect=[make_api_error(), good_response]
        )

        result, model = provider.classify_text("text", _EMPTY_TAXONOMY)

        assert result is not None
        assert model == "model-b"
        stats = provider.get_stats()
        assert stats["api_errors"] == 1
        assert stats["fallback_successes"] == 1

class TestClassifyTextAllModelsFail:
    """When every model fails, returns (None, "")."""

    def test_returns_none_when_all_fail(self):
        provider = make_provider(AI_MODELS=["model-a", "model-b"])
        provider._create_completion = MagicMock(side_effect=make_api_error())

        result, model = provider.classify_text("text", _EMPTY_TAXONOMY)

        assert result is None
        assert model == ""

    def test_returns_none_when_all_return_invalid_json(self):
        provider = make_provider(AI_MODELS=["model-a", "model-b"])
        bad_response = make_completion_response("garbage")
        provider._create_completion = MagicMock(return_value=bad_response)

        result, model = provider.classify_text("text", _EMPTY_TAXONOMY)

        assert result is None
        assert model == ""
        assert provider.get_stats()["invalid_json"] == 2

class TestClassifyTextEmptyInput:
    """Empty or whitespace-only text should short-circuit."""

    def test_empty_string_returns_none(self):
        provider = make_provider()

        result, model = provider.classify_text("", _EMPTY_TAXONOMY)

        assert result is None
        assert model == ""

    def test_whitespace_only_returns_none(self):
        provider = make_provider()

        result, model = provider.classify_text("   \n\t  ", _EMPTY_TAXONOMY)

        assert result is None
        assert model == ""

    def test_no_api_call_on_empty_text(self):
        provider = make_provider()
        provider._create_completion = MagicMock()

        provider.classify_text("   ", _EMPTY_TAXONOMY)

        provider._create_completion.assert_not_called()

class TestClassifyTextTruncationNote:
    """Truncation note is appended to the user message."""

    def test_truncation_note_included_in_message(self):
        provider = make_provider(AI_MODELS=["gpt-5.4-mini"])
        response = make_completion_response(valid_classification_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        provider.classify_text(
            "text",
            TaxonomyContext(correspondents=["Acme"], document_types=["Invoice"], tags=["tag"]),
            truncation_note="NOTE: Truncated to 3 pages.",
        )

        user_msg = captured_kwargs["messages"][1]["content"]
        assert "NOTE: Truncated to 3 pages." in user_msg

    def test_no_truncation_note_when_none(self):
        provider = make_provider(AI_MODELS=["gpt-5.4-mini"])
        response = make_completion_response(valid_classification_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion

        provider.classify_text("text", _EMPTY_TAXONOMY, truncation_note=None)

        user_msg = captured_kwargs["messages"][1]["content"]
        assert "NOTE:" not in user_msg

class TestStatsTracking:
    """get_stats returns accurate counters."""

    def test_stats_accumulate_across_calls(self):
        provider = make_provider(AI_MODELS=["model-a"])
        response = make_completion_response(valid_classification_json())
        provider._create_completion = MagicMock(return_value=response)

        provider.classify_text("text", _EMPTY_TAXONOMY)
        provider.classify_text("text", _EMPTY_TAXONOMY)

        stats = provider.get_stats()
        assert stats["attempts"] == 2

    def test_reset_stats_clears_counters(self):
        provider = make_provider(AI_MODELS=["model-a"])
        response = make_completion_response(valid_classification_json())
        provider._create_completion = MagicMock(return_value=response)

        provider.classify_text("text", _EMPTY_TAXONOMY)
        provider.reset_stats()

        stats = provider.get_stats()
        assert stats["attempts"] == 0

    def test_stats_empty_before_any_call(self):
        provider = make_provider()

        stats = provider.get_stats()

        assert all(v == 0 for v in stats.values())

class TestModelDeduplication:
    """Duplicate models in AI_MODELS are tried only once."""

    def test_duplicate_models_deduplicated(self):
        provider = make_provider(AI_MODELS=["model-a", "model-a", "model-b"])
        provider._create_completion = MagicMock(side_effect=make_api_error())

        provider.classify_text("text", _EMPTY_TAXONOMY)

        assert provider.get_stats()["attempts"] == 2
