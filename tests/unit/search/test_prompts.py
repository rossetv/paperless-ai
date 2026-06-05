"""Tests for search.prompts — schemas, response-format gating, and ordering.

Covers RAG-06 (strict json_schema response_format for planner + synthesiser)
and RAG-09 (planner system prompt byte-stability + synth delimiter ordering).
The LLM is never called here — these are pure prompt/string builders.
"""

from __future__ import annotations

from search.prompts import (
    PLANNER_JSON_SCHEMA,
    SYNTHESISER_JSON_SCHEMA,
    _planner_response_format,
    _synthesiser_response_format,
    build_planner_system_prompt,
    build_planner_user_message,
)
from tests.helpers.factories import make_search_settings


class TestPlannerSchema:
    """The planner schema is a strict json_schema mirroring QueryPlan."""

    def test_schema_is_strict(self) -> None:
        assert PLANNER_JSON_SCHEMA["strict"] is True

    def test_schema_forbids_additional_properties(self) -> None:
        assert PLANNER_JSON_SCHEMA["schema"]["additionalProperties"] is False

    def test_schema_requires_every_property(self) -> None:
        props = set(PLANNER_JSON_SCHEMA["schema"]["properties"])
        required = set(PLANNER_JSON_SCHEMA["schema"]["required"])
        assert props == required  # OpenAI strict mode: required == properties

    def test_schema_models_the_query_plan_keys(self) -> None:
        props = PLANNER_JSON_SCHEMA["schema"]["properties"]
        assert {
            "semantic_queries",
            "keyword_terms",
            "filter_candidates",
            "sub_questions",
        } <= set(props)

    def test_nested_filter_candidates_is_also_strict(self) -> None:
        fc = PLANNER_JSON_SCHEMA["schema"]["properties"]["filter_candidates"]
        assert fc["additionalProperties"] is False
        assert set(fc["properties"]) == set(fc["required"])


class TestSynthesiserSchema:
    """The synthesiser schema is a strict required-superset of the union."""

    def test_schema_is_strict(self) -> None:
        assert SYNTHESISER_JSON_SCHEMA["strict"] is True

    def test_schema_requires_every_property(self) -> None:
        props = set(SYNTHESISER_JSON_SCHEMA["schema"]["properties"])
        required = set(SYNTHESISER_JSON_SCHEMA["schema"]["required"])
        assert props == required

    def test_schema_carries_discriminant_and_both_branches(self) -> None:
        props = set(SYNTHESISER_JSON_SCHEMA["schema"]["properties"])
        assert {"outcome", "answer", "citations", "adjustment"} <= props


class TestResponseFormatGating:
    """response_format is built for OpenAI and None otherwise (mirrors classifier)."""

    def test_planner_response_format_for_openai(self) -> None:
        settings = make_search_settings(LLM_PROVIDER="openai")
        rf = _planner_response_format(settings)
        assert rf == {"type": "json_schema", "json_schema": PLANNER_JSON_SCHEMA}

    def test_planner_response_format_none_for_ollama(self) -> None:
        settings = make_search_settings(LLM_PROVIDER="ollama")
        assert _planner_response_format(settings) is None

    def test_synthesiser_response_format_for_openai(self) -> None:
        settings = make_search_settings(LLM_PROVIDER="openai")
        rf = _synthesiser_response_format(settings)
        assert rf == {"type": "json_schema", "json_schema": SYNTHESISER_JSON_SCHEMA}

    def test_synthesiser_response_format_none_for_ollama(self) -> None:
        settings = make_search_settings(LLM_PROVIDER="ollama")
        assert _synthesiser_response_format(settings) is None


class TestPlannerSystemPromptByteStable:
    """The planner system prompt no longer interpolates {today} (RAG-09)."""

    def test_system_prompt_takes_no_argument(self) -> None:
        prompt = build_planner_system_prompt()
        assert "search-query planning engine" in prompt

    def test_system_prompt_has_no_date_placeholder(self) -> None:
        prompt = build_planner_system_prompt()
        assert "{today}" not in prompt
        # No concrete date leaked in either — it lives in the user turn now.
        assert "Today's date is 20" not in prompt

    def test_system_prompt_is_identical_across_calls(self) -> None:
        assert build_planner_system_prompt() == build_planner_system_prompt()


class TestPlannerUserMessageCarriesDate:
    """The date moves into the user turn so the system prompt is cacheable."""

    def test_user_message_contains_the_date(self) -> None:
        msg = build_planner_user_message(query="find my invoice", today="2026-06-05")
        assert "2026-06-05" in msg

    def test_user_message_contains_the_query(self) -> None:
        msg = build_planner_user_message(query="find my invoice", today="2026-06-05")
        assert "find my invoice" in msg
