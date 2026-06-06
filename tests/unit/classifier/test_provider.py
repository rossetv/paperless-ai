"""Tests for classifier.provider — the ``classify_text`` model-fallback flow.

The parameter-compatibility retry machinery (``_create_with_compat`` and the
temperature / response-format / max-tokens stripping) is covered in
``test_provider_compat``; this file is split off it for the 500-line ceiling
(CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from classifier.prompts import DOCUMENT_CONTENT_DELIMITER
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
            TaxonomyContext(
                correspondents=["Acme"], document_types=["Invoice"], tags=["bills"]
            ),
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
    """Truncation note sits after the taxonomy and before the transcription."""

    def _capture_user_message(self, provider, **classify_kwargs) -> str:
        response = make_completion_response(valid_classification_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion
        provider.classify_text(**classify_kwargs)
        return captured_kwargs["messages"][1]["content"]

    def test_truncation_note_included_after_taxonomy(self):
        provider = make_provider(AI_MODELS=["gpt-5.4-mini"])
        user_msg = self._capture_user_message(
            provider,
            text="body text",
            taxonomy=TaxonomyContext(
                correspondents=["Acme"], document_types=["Invoice"], tags=["tag"]
            ),
            truncation_note="NOTE: Truncated to 3 pages.",
        )

        assert "NOTE: Truncated to 3 pages." in user_msg
        assert user_msg.index("Acme") < user_msg.index("NOTE: Truncated to 3 pages.")
        assert user_msg.index("NOTE: Truncated to 3 pages.") < user_msg.index(
            DOCUMENT_CONTENT_DELIMITER
        )

    def test_no_truncation_note_when_none(self):
        provider = make_provider(AI_MODELS=["gpt-5.4-mini"])
        user_msg = self._capture_user_message(
            provider, text="body text", taxonomy=_EMPTY_TAXONOMY, truncation_note=None
        )

        assert "NOTE:" not in user_msg


class TestUserMessageOrdering:
    """Stable prefix (taxonomy) first; document transcription last."""

    def _capture_user_message(self, provider, text, taxonomy) -> str:
        response = make_completion_response(valid_classification_json())
        captured_kwargs = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion
        provider.classify_text(text, taxonomy)
        return captured_kwargs["messages"][1]["content"]

    def test_taxonomy_precedes_transcription(self):
        provider = make_provider(AI_MODELS=["gpt-5.4-mini"])
        taxonomy = TaxonomyContext(
            correspondents=["Acme"], document_types=["Invoice"], tags=["bills"]
        )

        user_msg = self._capture_user_message(provider, "body text", taxonomy)

        assert user_msg.index("Acme") < user_msg.index(DOCUMENT_CONTENT_DELIMITER)

    def test_document_text_is_the_final_segment(self):
        provider = make_provider(AI_MODELS=["gpt-5.4-mini"])

        user_msg = self._capture_user_message(
            provider, "UNIQUE-DOC-BODY", _EMPTY_TAXONOMY
        )

        assert user_msg.rstrip().endswith("UNIQUE-DOC-BODY")

    def test_two_docs_share_an_identical_taxonomy_prefix(self):
        provider = make_provider(AI_MODELS=["gpt-5.4-mini"])
        taxonomy = TaxonomyContext(
            correspondents=["Acme"], document_types=["Invoice"], tags=["bills"]
        )

        msg_a = self._capture_user_message(provider, "first document body", taxonomy)
        msg_b = self._capture_user_message(provider, "second different body", taxonomy)

        marker = DOCUMENT_CONTENT_DELIMITER
        prefix_a = msg_a[: msg_a.index(marker)]
        prefix_b = msg_b[: msg_b.index(marker)]
        assert prefix_a == prefix_b
        assert "Acme" in prefix_a

    def test_taxonomy_json_serialisation_unchanged(self):
        provider = make_provider(AI_MODELS=["gpt-5.4-mini"])
        taxonomy = TaxonomyContext(
            correspondents=["Acmé & Co"], document_types=["Invoice"], tags=["bills"]
        )

        user_msg = self._capture_user_message(provider, "body", taxonomy)

        # ensure_ascii=True escaping must be preserved by the reorder.
        import json as _json

        assert _json.dumps(["Acmé & Co"], ensure_ascii=True) in user_msg


class TestPromptInjectionGuard:
    """Untrusted document content is fenced with a data-isolation delimiter.

    §10.2: every prompt that embeds retrieved/untrusted content places it below
    an explicit delimiter and instructs the model to treat it as data, never as
    instructions. The classifier's user message is the only site where untrusted
    document text is interpolated.
    """

    def _capture_messages(self, provider, text, taxonomy) -> list[dict]:
        response = make_completion_response(valid_classification_json())
        captured_kwargs: dict = {}

        def capture_completion(**kwargs):
            captured_kwargs.update(kwargs)
            return response

        provider._create_completion = capture_completion
        provider.classify_text(text, taxonomy)
        return captured_kwargs["messages"]

    def test_system_prompt_instructs_to_treat_content_as_data(self):
        provider = make_provider(AI_MODELS=["gpt-5.4-mini"])
        messages = self._capture_messages(provider, "body", _EMPTY_TAXONOMY)
        system = messages[0]["content"]
        assert "DOCUMENT CONTENT" in system
        assert "data" in system.lower()
        assert "instruction" in system.lower()

    def test_user_message_fences_document_content_with_delimiter(self):
        provider = make_provider(AI_MODELS=["gpt-5.4-mini"])
        messages = self._capture_messages(provider, "UNIQUE-BODY-TEXT", _EMPTY_TAXONOMY)
        user_msg = messages[1]["content"]
        # The delimiter must appear immediately before the interpolated content.
        assert "DOCUMENT CONTENT" in user_msg
        assert "DATA ONLY" in user_msg
        assert user_msg.index("DOCUMENT CONTENT") < user_msg.index("UNIQUE-BODY-TEXT")


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
