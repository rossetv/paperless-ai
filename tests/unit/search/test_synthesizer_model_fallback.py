"""Tests for search.synthesizer — model selection and the AI_MODELS fallback.

Verifies:
- The configured SEARCH_ANSWER_MODEL is the model requested.
- Exactly one LLM call is made per synthesise() invocation (per model attempt).
- When the primary model raises an OpenAI error, the next in AI_MODELS is tried.
- Every OpenAI API error — retryable AND non-retryable (AuthenticationError,
  etc.) — degrades gracefully per mode; synthesise() never raises (C1/C2).

Outcome behaviour and prompt-injection safety are in :mod:`test_synthesizer`
(split for the 500-line ceiling, §3.1).

LLM mocking: these tests build a bare Synthesizer and assign
``_create_completion`` a ``side_effect`` mock directly, since they script
multiple model attempts in one call.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from search.models import Answered, NeedsMore, RetrievedChunk
from search.synthesizer import Synthesizer
from tests.helpers.factories import make_retrieved_chunk, make_search_settings
from tests.helpers.llm import (
    answered_response_json,
    make_authentication_error,
    make_chat_completion,
    make_internal_server_error,
)
from tests.unit.search.conftest import build_synthesizer


def _chunk(document_id: int, text: str) -> RetrievedChunk:
    """Build a RetrievedChunk for *document_id* — a terse local alias."""
    return make_retrieved_chunk(
        chunk_id=document_id * 10, document_id=document_id, text=text
    )


# ---------------------------------------------------------------------------
# Model selection: SEARCH_ANSWER_MODEL is used
# ---------------------------------------------------------------------------


class TestModelSelection:
    """The synthesiser uses SEARCH_ANSWER_MODEL as the primary model."""

    def test_configured_answer_model_is_requested(self) -> None:
        chunks = [_chunk(1, "Some text.")]
        settings = make_search_settings(
            SEARCH_ANSWER_MODEL="gpt-5.4", AI_MODELS=["gpt-5.4-mini", "gpt-5.4"]
        )
        synthesiser = build_synthesizer(
            settings, answered_response_json("answer", citations=[1])
        )
        synthesiser.synthesise("query", chunks, mode="exploratory")

        call_args = synthesiser._create_completion.call_args  # type: ignore[attr-defined]
        assert call_args is not None
        assert call_args.kwargs["model"] == "gpt-5.4"

    def test_different_configured_model_is_requested(self) -> None:
        chunks = [_chunk(1, "Some text.")]
        settings = make_search_settings(
            SEARCH_ANSWER_MODEL="gemma3:27b", AI_MODELS=["gemma3:27b"]
        )
        synthesiser = build_synthesizer(
            settings, answered_response_json("answer", citations=[1])
        )
        synthesiser.synthesise("query", chunks, mode="final")

        call_args = synthesiser._create_completion.call_args  # type: ignore[attr-defined]
        assert call_args.kwargs["model"] == "gemma3:27b"

    def test_exactly_one_llm_call_per_synthesise(self) -> None:
        chunks = [_chunk(1, "Some text.")]
        synthesiser = build_synthesizer(
            make_search_settings(), answered_response_json("answer", citations=[1])
        )
        synthesiser.synthesise("query", chunks, mode="exploratory")

        assert synthesiser._create_completion.call_count == 1  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AI_MODELS fallback chain
# ---------------------------------------------------------------------------


class TestModelFallback:
    """When the primary model raises an OpenAI error, the next in AI_MODELS is tried."""

    def test_fallback_to_second_model_on_api_error(self) -> None:
        chunks = [_chunk(1, "Boiler warranty text.")]
        settings = make_search_settings(
            SEARCH_ANSWER_MODEL="gpt-5.4", AI_MODELS=["gpt-5.4", "gpt-5.4-mini"]
        )
        synthesiser = Synthesizer(settings)
        # First model raises a retryable error; second model succeeds.
        synthesiser._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                make_internal_server_error(),
                make_chat_completion(
                    answered_response_json("fallback answer [1].", citations=[1])
                ),
            ]
        )

        outcome = synthesiser.synthesise("query", chunks, mode="exploratory")

        assert synthesiser._create_completion.call_count == 2  # type: ignore[attr-defined]
        assert isinstance(outcome, Answered)


# ---------------------------------------------------------------------------
# C1/C2 — every OpenAI API error degrades gracefully; synthesise() never raises
# ---------------------------------------------------------------------------


class TestApiErrorNeverEscapes:
    """synthesise() catches every openai.APIError subclass — retryable or not.

    Finding C1/C2: the old hand-rolled loop caught only the retryable errors
    plus BadRequestError, so AuthenticationError / PermissionDeniedError /
    NotFoundError propagated out of synthesise() and turned every search into
    an unhandled 500.  The migration to OpenAIChatMixin catches the whole
    openai.APIError family as the terminal skip-model branch, then degrades
    per mode.
    """

    def test_authentication_error_in_final_mode_returns_answered(self) -> None:
        """A wrong/expired key in final mode degrades to Answered, never raises."""
        chunks = [_chunk(1, "Some text.")]
        settings = make_search_settings(
            SEARCH_ANSWER_MODEL="gpt-5.4", AI_MODELS=["gpt-5.4", "gpt-5.4-mini"]
        )
        synthesiser = Synthesizer(settings)
        synthesiser._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=make_authentication_error()
        )

        with patch("search.synthesizer.log") as mock_log:
            outcome = synthesiser.synthesise("a query", chunks, mode="final")

        assert isinstance(outcome, Answered)
        mock_log.warning.assert_called()
        # Both configured models were attempted before degrading.
        assert synthesiser._create_completion.call_count == 2  # type: ignore[attr-defined]

    def test_authentication_error_in_exploratory_mode_returns_needs_more(self) -> None:
        """A wrong/expired key in exploratory mode degrades to NeedsMore, never raises."""
        chunks = [_chunk(1, "Some text.")]
        settings = make_search_settings(SEARCH_ANSWER_MODEL="m", AI_MODELS=["m"])
        synthesiser = Synthesizer(settings)
        synthesiser._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=make_authentication_error()
        )

        outcome = synthesiser.synthesise("a query", chunks, mode="exploratory")

        assert isinstance(outcome, NeedsMore)

    def test_authentication_then_success_falls_through(self) -> None:
        """A non-retryable error on model 1 still lets model 2 answer."""
        chunks = [_chunk(1, "Boiler warranty text.")]
        settings = make_search_settings(
            SEARCH_ANSWER_MODEL="gpt-5.4", AI_MODELS=["gpt-5.4", "gpt-5.4-mini"]
        )
        synthesiser = Synthesizer(settings)
        synthesiser._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                make_authentication_error(),
                make_chat_completion(
                    answered_response_json("model two answered [1].", citations=[1])
                ),
            ]
        )

        outcome = synthesiser.synthesise("a query", chunks, mode="exploratory")

        assert isinstance(outcome, Answered)
        assert outcome.answer == "model two answered [1]."
        assert synthesiser._create_completion.call_count == 2  # type: ignore[attr-defined]
