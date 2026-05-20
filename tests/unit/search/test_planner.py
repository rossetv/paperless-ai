"""Tests for search.planner — LLM query planner.

Verifies the QueryPlanner contract (spec §6.1):
- A well-formed mock LLM response is parsed into the expected QueryPlan.
- Relative-date language in the response produces date_from/date_to candidates.
- A malformed / empty / non-JSON response degrades to the safe fallback plan.
- The configured SEARCH_PLANNER_MODEL is the model requested.
- A warning is logged on degraded fallback.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from search.models import FilterCandidates, QueryPlan
from search.planner import QueryPlanner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(
    planner_model: str = "gpt-5.4-mini",
    ai_models: list[str] | None = None,
) -> MagicMock:
    """Build a minimal Settings-like mock for QueryPlanner."""
    mock = MagicMock()
    mock.SEARCH_PLANNER_MODEL = planner_model
    mock.AI_MODELS = ai_models or ["gpt-5.4-mini", "gpt-5.4", "o4-mini"]
    return mock


def _make_llm_client(response_content: str) -> MagicMock:
    """Build a mock LLM client that returns the given content string."""
    choice = MagicMock()
    choice.message.content = response_content
    completion = MagicMock()
    completion.choices = [choice]

    client = MagicMock()
    client.chat.completions.create.return_value = completion
    return client


def _make_planner_json(
    semantic_queries: list[str] | None = None,
    keyword_terms: list[str] | None = None,
    correspondent: str | None = None,
    document_type: str | None = None,
    tags: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sub_questions: list[str] | None = None,
) -> str:
    """Produce a valid planner JSON response string."""
    payload: dict[str, Any] = {
        "semantic_queries": semantic_queries or ["boiler warranty letter"],
        "keyword_terms": keyword_terms or ["boiler", "warranty"],
        "filter_candidates": {
            "correspondent": correspondent,
            "document_type": document_type,
            "tags": tags or [],
            "date_from": date_from,
            "date_to": date_to,
        },
        "sub_questions": sub_questions or [],
    }
    return json.dumps(payload)


def _empty_filter_candidates() -> FilterCandidates:
    return FilterCandidates(
        correspondent=None,
        document_type=None,
        tags=(),
        date_from=None,
        date_to=None,
    )


# ---------------------------------------------------------------------------
# Well-formed response: full parse
# ---------------------------------------------------------------------------


class TestWellFormedResponse:
    """A valid JSON response is parsed into a fully-populated QueryPlan."""

    def test_semantic_queries_are_parsed(self) -> None:
        payload = _make_planner_json(
            semantic_queries=["boiler warranty letter", "heating system guarantee"],
        )
        settings = _make_settings()
        llm_client = _make_llm_client(payload)

        planner = QueryPlanner(settings, llm_client)
        plan = planner.plan("find my boiler warranty")

        assert "boiler warranty letter" in plan.semantic_queries
        assert "heating system guarantee" in plan.semantic_queries

    def test_keyword_terms_are_parsed(self) -> None:
        payload = _make_planner_json(keyword_terms=["boiler", "warranty", "Worcester Bosch"])
        settings = _make_settings()
        llm_client = _make_llm_client(payload)

        plan = QueryPlanner(settings, llm_client).plan("Worcester Bosch boiler warranty")

        assert "boiler" in plan.keyword_terms
        assert "warranty" in plan.keyword_terms
        assert "Worcester Bosch" in plan.keyword_terms

    def test_filter_candidates_correspondent_is_parsed(self) -> None:
        payload = _make_planner_json(correspondent="npower")
        settings = _make_settings()
        llm_client = _make_llm_client(payload)

        plan = QueryPlanner(settings, llm_client).plan("npower electricity bill")

        assert plan.filter_candidates.correspondent == "npower"

    def test_filter_candidates_document_type_is_parsed(self) -> None:
        payload = _make_planner_json(document_type="invoice")
        settings = _make_settings()
        llm_client = _make_llm_client(payload)

        plan = QueryPlanner(settings, llm_client).plan("latest invoice")

        assert plan.filter_candidates.document_type == "invoice"

    def test_filter_candidates_tags_are_parsed(self) -> None:
        payload = _make_planner_json(tags=["electricity", "utility"])
        settings = _make_settings()
        llm_client = _make_llm_client(payload)

        plan = QueryPlanner(settings, llm_client).plan("electricity utility bills")

        assert "electricity" in plan.filter_candidates.tags
        assert "utility" in plan.filter_candidates.tags

    def test_sub_questions_are_parsed(self) -> None:
        payload = _make_planner_json(
            sub_questions=["When was the boiler installed?", "What is the expiry date?"],
        )
        settings = _make_settings()
        llm_client = _make_llm_client(payload)

        plan = QueryPlanner(settings, llm_client).plan("boiler installation and warranty expiry")

        assert "When was the boiler installed?" in plan.sub_questions
        assert "What is the expiry date?" in plan.sub_questions

    def test_returns_query_plan_dataclass(self) -> None:
        payload = _make_planner_json()
        settings = _make_settings()
        llm_client = _make_llm_client(payload)

        plan = QueryPlanner(settings, llm_client).plan("any query")

        assert isinstance(plan, QueryPlan)

    def test_filter_candidates_is_frozen_dataclass(self) -> None:
        payload = _make_planner_json()
        settings = _make_settings()
        llm_client = _make_llm_client(payload)

        plan = QueryPlanner(settings, llm_client).plan("any query")

        assert isinstance(plan.filter_candidates, FilterCandidates)
        with pytest.raises(Exception):  # FrozenInstanceError
            plan.filter_candidates.correspondent = "changed"  # type: ignore[misc]

    def test_json_wrapped_in_markdown_fences_is_still_parsed(self) -> None:
        """The LLM may wrap JSON in triple-backtick fences — tolerate this."""
        payload = "```json\n" + _make_planner_json(keyword_terms=["VAT", "invoice"]) + "\n```"
        settings = _make_settings()
        llm_client = _make_llm_client(payload)

        plan = QueryPlanner(settings, llm_client).plan("VAT invoice")

        assert "VAT" in plan.keyword_terms


# ---------------------------------------------------------------------------
# Relative-date language
# ---------------------------------------------------------------------------


class TestRelativeDateLanguage:
    """Date strings from the LLM end up in filter_candidates.date_from/date_to."""

    def test_date_from_is_propagated(self) -> None:
        payload = _make_planner_json(date_from="2024-01-01", date_to="2024-12-31")
        settings = _make_settings()
        llm_client = _make_llm_client(payload)

        plan = QueryPlanner(settings, llm_client).plan("invoices from last year")

        assert plan.filter_candidates.date_from == "2024-01-01"
        assert plan.filter_candidates.date_to == "2024-12-31"

    def test_date_to_only_is_propagated(self) -> None:
        payload = _make_planner_json(date_to="2025-03-31")
        settings = _make_settings()
        llm_client = _make_llm_client(payload)

        plan = QueryPlanner(settings, llm_client).plan("documents since March")

        assert plan.filter_candidates.date_to == "2025-03-31"
        assert plan.filter_candidates.date_from is None

    def test_null_dates_produce_none(self) -> None:
        payload = _make_planner_json(date_from=None, date_to=None)
        settings = _make_settings()
        llm_client = _make_llm_client(payload)

        plan = QueryPlanner(settings, llm_client).plan("all documents")

        assert plan.filter_candidates.date_from is None
        assert plan.filter_candidates.date_to is None


# ---------------------------------------------------------------------------
# Malformed / empty / non-JSON response: safe fallback
# ---------------------------------------------------------------------------


class TestFallbackOnBadResponse:
    """A bad LLM response degrades to a safe single-query plan and logs a warning."""

    def _assert_is_fallback_plan(self, plan: QueryPlan, raw_query: str) -> None:
        assert plan.semantic_queries == (raw_query,)
        assert plan.keyword_terms == ()
        assert plan.sub_questions == ()
        assert plan.filter_candidates == _empty_filter_candidates()

    def test_empty_response_produces_fallback(self) -> None:
        settings = _make_settings()
        llm_client = _make_llm_client("")

        with patch("search.planner.log") as mock_log:
            plan = QueryPlanner(settings, llm_client).plan("find boiler warranty")

        mock_log.warning.assert_called()
        self._assert_is_fallback_plan(plan, "find boiler warranty")

    def test_non_json_response_produces_fallback(self) -> None:
        settings = _make_settings()
        llm_client = _make_llm_client("Sorry, I cannot help with that.")

        with patch("search.planner.log") as mock_log:
            plan = QueryPlanner(settings, llm_client).plan("find boiler warranty")

        mock_log.warning.assert_called()
        self._assert_is_fallback_plan(plan, "find boiler warranty")

    def test_json_missing_required_keys_produces_fallback(self) -> None:
        """A JSON object that lacks 'semantic_queries' is treated as malformed."""
        settings = _make_settings()
        # Valid JSON but missing the required planner keys.
        llm_client = _make_llm_client('{"something": "unexpected"}')

        with patch("search.planner.log") as mock_log:
            plan = QueryPlanner(settings, llm_client).plan("missing key query")

        mock_log.warning.assert_called()
        self._assert_is_fallback_plan(plan, "missing key query")

    def test_json_array_response_produces_fallback(self) -> None:
        """A JSON array (not an object) is treated as malformed."""
        settings = _make_settings()
        llm_client = _make_llm_client("[1, 2, 3]")

        with patch("search.planner.log") as mock_log:
            plan = QueryPlanner(settings, llm_client).plan("array response query")

        mock_log.warning.assert_called()
        self._assert_is_fallback_plan(plan, "array response query")

    def test_none_content_produces_fallback(self) -> None:
        """A None choices[0].message.content is treated as empty."""
        choice = MagicMock()
        choice.message.content = None
        completion = MagicMock()
        completion.choices = [choice]
        llm_client = MagicMock()
        llm_client.chat.completions.create.return_value = completion

        settings = _make_settings()
        with patch("search.planner.log") as mock_log:
            plan = QueryPlanner(settings, llm_client).plan("none content query")

        mock_log.warning.assert_called()
        self._assert_is_fallback_plan(plan, "none content query")

    def test_fallback_plan_raw_query_preserved(self) -> None:
        """The raw query is always the sole semantic_query in the fallback."""
        raw = "find my tax return from 2023"
        settings = _make_settings()
        llm_client = _make_llm_client("not json at all")

        plan = QueryPlanner(settings, llm_client).plan(raw)

        assert plan.semantic_queries == (raw,)


# ---------------------------------------------------------------------------
# Model selection: SEARCH_PLANNER_MODEL is the model requested
# ---------------------------------------------------------------------------


class TestModelSelection:
    """The planner uses SEARCH_PLANNER_MODEL as the primary model."""

    def test_configured_model_is_requested(self) -> None:
        payload = _make_planner_json()
        settings = _make_settings(planner_model="gpt-5.4-mini", ai_models=["gpt-5.4-mini", "gpt-5.4"])
        llm_client = _make_llm_client(payload)

        QueryPlanner(settings, llm_client).plan("test query")

        call_kwargs = llm_client.chat.completions.create.call_args
        assert call_kwargs is not None
        # model= may be a positional arg or keyword arg; check both
        model_used = call_kwargs.kwargs.get("model") or call_kwargs.args[0]
        assert model_used == "gpt-5.4-mini"

    def test_different_configured_model_is_requested(self) -> None:
        payload = _make_planner_json()
        settings = _make_settings(planner_model="gemma3:12b", ai_models=["gemma3:12b"])
        llm_client = _make_llm_client(payload)

        QueryPlanner(settings, llm_client).plan("test query")

        call_kwargs = llm_client.chat.completions.create.call_args
        model_used = call_kwargs.kwargs.get("model") or call_kwargs.args[0]
        assert model_used == "gemma3:12b"

    def test_exactly_one_llm_call_per_plan(self) -> None:
        """The planner makes exactly one LLM call per plan() invocation."""
        payload = _make_planner_json()
        settings = _make_settings()
        llm_client = _make_llm_client(payload)

        QueryPlanner(settings, llm_client).plan("single call test")

        assert llm_client.chat.completions.create.call_count == 1


# ---------------------------------------------------------------------------
# AI_MODELS fallback chain: fallback model is tried on error
# ---------------------------------------------------------------------------


class TestModelFallback:
    """When the primary model raises an OpenAI error, the next in AI_MODELS is tried."""

    def test_fallback_to_second_model_on_api_error(self) -> None:
        import openai

        payload = _make_planner_json(semantic_queries=["fallback worked"])
        settings = _make_settings(
            planner_model="gpt-5.4-mini",
            ai_models=["gpt-5.4-mini", "gpt-5.4"],
        )

        # First call raises; second call succeeds.
        success_choice = MagicMock()
        success_choice.message.content = payload
        success_completion = MagicMock()
        success_completion.choices = [success_choice]

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.headers = {}

        llm_client = MagicMock()
        llm_client.chat.completions.create.side_effect = [
            openai.InternalServerError(
                message="server error",
                response=mock_response,
                body=None,
            ),
            success_completion,
        ]

        plan = QueryPlanner(settings, llm_client).plan("test fallback")

        assert llm_client.chat.completions.create.call_count == 2
        assert "fallback worked" in plan.semantic_queries
