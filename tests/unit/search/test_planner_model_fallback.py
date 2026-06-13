"""Tests for search.planner — model selection and the AI_MODELS fallback chain.

Verifies:
- The configured SEARCH_PLANNER_MODEL is the model requested.
- Exactly one LLM call is made per plan() invocation (per model attempt).
- When the primary model raises an OpenAI error, the next in AI_MODELS is tried.
- Every OpenAI API error — retryable AND non-retryable (AuthenticationError,
  etc.) — degrades to the fallback plan; plan() never raises (findings C1/C2).

Response-parsing behaviour is in :mod:`test_planner` (split for the 500-line
ceiling, §3.1).

LLM mocking: QueryPlanner subclasses OpenAIChatMixin; these tests build a bare
QueryPlanner and assign ``_create_completion`` a ``side_effect`` mock directly,
since they script multiple model attempts in one call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from search.models import EMPTY_FILTER_CANDIDATES, RetrievalPlan
from search.planner import QueryPlanner
from tests.helpers.factories import make_search_settings
from tests.helpers.llm import (
    _make_spec,
    make_authentication_error,
    make_api_error,
    make_chat_completion,
    make_internal_server_error,
    planner_response_json,
)
from tests.unit.search.conftest import build_planner


def _assert_is_fallback_plan(plan: RetrievalPlan, raw_query: str) -> None:
    """Assert *plan* is the minimal safe fallback for *raw_query*."""
    assert isinstance(plan, RetrievalPlan)
    assert len(plan.specs) == 1
    spec = plan.specs[0]
    assert spec.mode == "semantic"
    assert spec.semantic == raw_query
    assert spec.keywords == ()
    assert spec.filter_guess == EMPTY_FILTER_CANDIDATES


# ---------------------------------------------------------------------------
# Model selection: SEARCH_PLANNER_MODEL is the model requested
# ---------------------------------------------------------------------------


class TestModelSelection:
    """The planner uses SEARCH_PLANNER_MODEL as the primary model."""

    def test_configured_model_is_requested(self) -> None:
        settings = make_search_settings(
            SEARCH_PLANNER_MODEL="gpt-5.4-mini",
            CLASSIFY_MODELS=["gpt-5.4-mini", "gpt-5.4"],
        )
        planner = build_planner(settings, planner_response_json())
        planner.plan("test query")

        call_kwargs = planner._create_completion.call_args  # type: ignore[attr-defined]
        assert call_kwargs is not None
        assert call_kwargs.kwargs["model"] == "gpt-5.4-mini"

    def test_different_configured_model_is_requested(self) -> None:
        settings = make_search_settings(
            SEARCH_PLANNER_MODEL="gemma3:12b", CLASSIFY_MODELS=["gemma3:12b"]
        )
        planner = build_planner(settings, planner_response_json())
        planner.plan("test query")

        call_kwargs = planner._create_completion.call_args  # type: ignore[attr-defined]
        assert call_kwargs.kwargs["model"] == "gemma3:12b"

    def test_exactly_one_llm_call_per_plan(self) -> None:
        """The planner makes exactly one LLM call per plan() invocation."""
        planner = build_planner(make_search_settings(), planner_response_json())
        planner.plan("single call test")

        assert planner._create_completion.call_count == 1  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AI_MODELS fallback chain: fallback model is tried on error
# ---------------------------------------------------------------------------


class TestModelFallback:
    """When the primary model raises an OpenAI error, the next in AI_MODELS is tried."""

    def test_fallback_to_second_model_on_api_error(self) -> None:
        settings = make_search_settings(
            SEARCH_PLANNER_MODEL="gpt-5.4-mini",
            CLASSIFY_MODELS=["gpt-5.4-mini", "gpt-5.4"],
        )
        payload = planner_response_json(specs=[_make_spec(semantic="fallback worked")])

        planner = QueryPlanner(settings)
        # First model raises a retryable error; second model succeeds.
        planner._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                make_internal_server_error(),
                make_chat_completion(payload),
            ]
        )

        plan = planner.plan("test fallback")

        assert planner._create_completion.call_count == 2  # type: ignore[attr-defined]
        assert isinstance(plan, RetrievalPlan)
        assert any(s.semantic == "fallback worked" for s in plan.specs)


# ---------------------------------------------------------------------------
# C1/C2 — every OpenAI API error degrades to the fallback; plan() never raises
# ---------------------------------------------------------------------------


class TestApiErrorNeverEscapes:
    """plan() catches every openai.APIError subclass — retryable or not.

    Finding C1/C2: the old hand-rolled loop caught only the retryable errors
    plus BadRequestError, so AuthenticationError / PermissionDeniedError /
    NotFoundError propagated out of plan() and turned every search into an
    unhandled 500.  The migration to OpenAIChatMixin catches the whole
    openai.APIError family as the terminal skip-model branch.
    """

    def test_authentication_error_degrades_to_fallback(self) -> None:
        """A wrong/expired OPENAI_API_KEY must not raise out of plan()."""
        settings = make_search_settings(
            SEARCH_PLANNER_MODEL="gpt-5.4-mini",
            CLASSIFY_MODELS=["gpt-5.4-mini", "gpt-5.4"],
        )
        planner = QueryPlanner(settings)
        # Every model attempt raises AuthenticationError — non-retryable.
        planner._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=make_authentication_error()
        )

        # Must NOT raise.
        plan = planner.plan("find my boiler warranty")

        _assert_is_fallback_plan(plan, "find my boiler warranty")
        # Both configured models were attempted before giving up.
        assert planner._create_completion.call_count == 2  # type: ignore[attr-defined]

    def test_generic_api_error_degrades_to_fallback(self) -> None:
        """A bare openai.APIError (no subclass) also degrades, never escapes."""
        settings = make_search_settings(SEARCH_PLANNER_MODEL="m", CLASSIFY_MODELS=["m"])
        planner = QueryPlanner(settings)
        planner._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=make_api_error()
        )

        plan = planner.plan("a query")

        _assert_is_fallback_plan(plan, "a query")

    def test_authentication_then_success_falls_through(self) -> None:
        """A non-retryable error on model 1 still lets model 2 answer."""
        settings = make_search_settings(
            SEARCH_PLANNER_MODEL="gpt-5.4-mini",
            CLASSIFY_MODELS=["gpt-5.4-mini", "gpt-5.4"],
        )
        payload = planner_response_json(
            specs=[_make_spec(semantic="second model answered")]
        )
        planner = QueryPlanner(settings)
        planner._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                make_authentication_error(),
                make_chat_completion(payload),
            ]
        )

        plan = planner.plan("a query")

        assert isinstance(plan, RetrievalPlan)
        assert any(s.semantic == "second model answered" for s in plan.specs)
        assert planner._create_completion.call_count == 2  # type: ignore[attr-defined]


class TestReasoningEffortForwarded:
    """The planner forwards its configured reasoning_effort to the LLM call."""

    def test_planner_forwards_configured_reasoning_effort(self) -> None:
        # "medium" is the shipped default — proves the wiring forwards it verbatim.
        settings = make_search_settings(
            SEARCH_PLANNER_MODEL="gpt-5.4-mini",
            CLASSIFY_MODELS=["gpt-5.4-mini"],
            SEARCH_PLANNER_REASONING_EFFORT="medium",
        )
        planner = build_planner(settings, planner_response_json())
        planner.plan("any query")

        call = planner._create_completion.call_args  # type: ignore[attr-defined]
        assert call.kwargs["reasoning_effort"] == "medium"

    def test_planner_forwards_tuned_down_reasoning_effort(self) -> None:
        # The realistic per-env tuning: an operator lowers the planner to "minimal"
        # to capture the saving. Proves a non-default value forwards too.
        settings = make_search_settings(
            SEARCH_PLANNER_MODEL="gpt-5.4-mini",
            CLASSIFY_MODELS=["gpt-5.4-mini"],
            SEARCH_PLANNER_REASONING_EFFORT="minimal",
        )
        planner = build_planner(settings, planner_response_json())
        planner.plan("any query")

        call = planner._create_completion.call_args  # type: ignore[attr-defined]
        assert call.kwargs["reasoning_effort"] == "minimal"


class TestResponseFormatForwarded:
    """The planner forwards a strict json_schema response_format on OpenAI."""

    def test_planner_forwards_response_format_for_openai(self) -> None:
        from search.prompts import PLANNER_JSON_SCHEMA

        settings = make_search_settings(
            LLM_PROVIDER="openai",
            SEARCH_PLANNER_MODEL="gpt-5.4-mini",
            CLASSIFY_MODELS=["gpt-5.4-mini"],
        )
        planner = build_planner(settings, planner_response_json())
        planner.plan("any query")

        call = planner._create_completion.call_args  # type: ignore[attr-defined]
        assert call.kwargs["response_format"] == {
            "type": "json_schema",
            "json_schema": PLANNER_JSON_SCHEMA,
        }

    def test_planner_omits_response_format_for_ollama(self) -> None:
        settings = make_search_settings(
            SEARCH_PLANNER_PROVIDER="ollama",
            SEARCH_PLANNER_MODEL="gemma3:12b",
            CLASSIFY_MODELS=["gemma3:12b"],
        )
        planner = build_planner(settings, planner_response_json())
        planner.plan("any query")

        call = planner._create_completion.call_args  # type: ignore[attr-defined]
        assert "response_format" not in call.kwargs


class TestPlannerReadsClassifyModels:
    """Search planner fallback chain must use CLASSIFY_MODELS, not AI_MODELS."""

    def test_fallback_chain_uses_classify_models(self) -> None:
        """When the primary model fails, the planner falls back through CLASSIFY_MODELS."""
        payload = planner_response_json(
            specs=[_make_spec(semantic="classify-fallback worked")]
        )
        settings = make_search_settings(
            SEARCH_PLANNER_MODEL="gpt-5.4-mini",
            CLASSIFY_MODELS=["gpt-5.4-mini", "gpt-5.4"],
        )

        planner = QueryPlanner(settings)
        planner._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                make_internal_server_error(),
                make_chat_completion(payload),
            ]
        )

        plan = planner.plan("test fallback via classify")

        assert planner._create_completion.call_count == 2  # type: ignore[attr-defined]
        assert isinstance(plan, RetrievalPlan)
        assert any(s.semantic == "classify-fallback worked" for s in plan.specs)

    def test_no_cross_provider_fallback_when_planner_and_classify_differ(self) -> None:
        """A planner on Ollama must NOT fall back through an OpenAI CLASSIFY_MODELS
        list — those models belong to a different endpoint and would 404 on the
        Ollama client. When the providers differ the planner only tries its own
        model, then degrades (spec §4.4)."""
        settings = make_search_settings(
            SEARCH_PLANNER_PROVIDER="ollama",
            CLASSIFY_PROVIDER="openai",
            SEARCH_PLANNER_MODEL="gemma3:12b",
            CLASSIFY_MODELS=["gpt-5.4-mini", "gpt-5.4"],
        )

        planner = QueryPlanner(settings)
        planner._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=make_internal_server_error()
        )

        plan = planner.plan("query that fails")

        # Only the Ollama primary is attempted — no cross-provider GPT fallback.
        assert planner._create_completion.call_count == 1  # type: ignore[attr-defined]
        models_called = [
            call.kwargs["model"]
            for call in planner._create_completion.call_args_list  # type: ignore[attr-defined]
        ]
        assert models_called == ["gemma3:12b"]
        assert "gpt-5.4-mini" not in models_called
        # A degraded plan (no specs) is acceptable; the point is no GPT call.
        assert isinstance(plan, RetrievalPlan)
