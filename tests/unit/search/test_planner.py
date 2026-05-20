"""Tests for search.planner — parsing the LLM planner response.

Verifies the QueryPlanner parsing contract (spec §6.1):
- A well-formed mock LLM response is parsed into the expected QueryPlan.
- Relative-date language in the response produces date_from/date_to candidates.
- A malformed / empty / non-JSON response degrades to the safe fallback plan.
- String-valued list fields are not iterated character-by-character (I1).
- A list/dict value for a scalar filter field becomes None, not its repr (I2).

Model selection, the AI_MODELS fallback chain, and the "every API error
degrades, plan() never raises" contract are in
:mod:`test_planner_model_fallback` (split for the 500-line ceiling, §3.1).

LLM mocking: QueryPlanner subclasses OpenAIChatMixin; ``build_planner`` (see
conftest.py) patches the instance's ``_create_completion`` with a fake —
mirroring ``tests/unit/classifier`` — never via constructor injection.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from search.models import EMPTY_FILTER_CANDIDATES, FilterCandidates, QueryPlan
from tests.helpers.factories import make_search_settings
from tests.helpers.llm import planner_response_json
from tests.unit.search.conftest import build_planner


# ---------------------------------------------------------------------------
# Well-formed response: full parse
# ---------------------------------------------------------------------------


class TestWellFormedResponse:
    """A valid JSON response is parsed into a fully-populated QueryPlan."""

    def test_semantic_queries_are_parsed(self) -> None:
        payload = planner_response_json(
            semantic_queries=["boiler warranty letter", "heating system guarantee"]
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "find my boiler warranty"
        )

        assert "boiler warranty letter" in plan.semantic_queries
        assert "heating system guarantee" in plan.semantic_queries

    def test_keyword_terms_are_parsed(self) -> None:
        payload = planner_response_json(
            keyword_terms=["boiler", "warranty", "Worcester Bosch"]
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "Worcester Bosch boiler warranty"
        )

        assert "boiler" in plan.keyword_terms
        assert "warranty" in plan.keyword_terms
        assert "Worcester Bosch" in plan.keyword_terms

    def test_filter_candidates_correspondent_is_parsed(self) -> None:
        payload = planner_response_json(correspondent="npower")
        plan = build_planner(make_search_settings(), payload).plan(
            "npower electricity bill"
        )

        assert plan.filter_candidates.correspondent == "npower"

    def test_filter_candidates_document_type_is_parsed(self) -> None:
        payload = planner_response_json(document_type="invoice")
        plan = build_planner(make_search_settings(), payload).plan(
            "latest invoice"
        )

        assert plan.filter_candidates.document_type == "invoice"

    def test_filter_candidates_tags_are_parsed(self) -> None:
        payload = planner_response_json(tags=["electricity", "utility"])
        plan = build_planner(make_search_settings(), payload).plan(
            "electricity utility bills"
        )

        assert "electricity" in plan.filter_candidates.tags
        assert "utility" in plan.filter_candidates.tags

    def test_sub_questions_are_parsed(self) -> None:
        payload = planner_response_json(
            sub_questions=[
                "When was the boiler installed?",
                "What is the expiry date?",
            ]
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "boiler installation and warranty expiry"
        )

        assert "When was the boiler installed?" in plan.sub_questions
        assert "What is the expiry date?" in plan.sub_questions

    def test_returns_query_plan_dataclass(self) -> None:
        plan = build_planner(
            make_search_settings(), planner_response_json()
        ).plan("any query")

        assert isinstance(plan, QueryPlan)

    def test_filter_candidates_is_frozen_dataclass(self) -> None:
        plan = build_planner(
            make_search_settings(), planner_response_json()
        ).plan("any query")

        assert isinstance(plan.filter_candidates, FilterCandidates)
        with pytest.raises(Exception):  # FrozenInstanceError
            plan.filter_candidates.correspondent = "changed"  # type: ignore[misc]

    def test_json_wrapped_in_markdown_fences_is_still_parsed(self) -> None:
        """The LLM may wrap JSON in triple-backtick fences — tolerate this."""
        payload = (
            "```json\n"
            + planner_response_json(keyword_terms=["VAT", "invoice"])
            + "\n```"
        )
        plan = build_planner(make_search_settings(), payload).plan("VAT invoice")

        assert "VAT" in plan.keyword_terms


# ---------------------------------------------------------------------------
# Relative-date language
# ---------------------------------------------------------------------------


class TestRelativeDateLanguage:
    """Date strings from the LLM end up in filter_candidates.date_from/date_to."""

    def test_date_from_is_propagated(self) -> None:
        payload = planner_response_json(
            date_from="2024-01-01", date_to="2024-12-31"
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "invoices from last year"
        )

        assert plan.filter_candidates.date_from == "2024-01-01"
        assert plan.filter_candidates.date_to == "2024-12-31"

    def test_date_to_only_is_propagated(self) -> None:
        payload = planner_response_json(date_to="2025-03-31")
        plan = build_planner(make_search_settings(), payload).plan(
            "documents since March"
        )

        assert plan.filter_candidates.date_to == "2025-03-31"
        assert plan.filter_candidates.date_from is None

    def test_null_dates_produce_none(self) -> None:
        payload = planner_response_json(date_from=None, date_to=None)
        plan = build_planner(make_search_settings(), payload).plan(
            "all documents"
        )

        assert plan.filter_candidates.date_from is None
        assert plan.filter_candidates.date_to is None


# ---------------------------------------------------------------------------
# Malformed / empty / non-JSON response: safe fallback
# ---------------------------------------------------------------------------


def _assert_is_fallback_plan(plan: QueryPlan, raw_query: str) -> None:
    """Assert *plan* is the minimal safe fallback for *raw_query*."""
    assert plan.semantic_queries == (raw_query,)
    assert plan.keyword_terms == ()
    assert plan.sub_questions == ()
    assert plan.filter_candidates == EMPTY_FILTER_CANDIDATES


class TestFallbackOnBadResponse:
    """A bad LLM response degrades to a safe single-query plan and logs a warning."""

    def test_empty_response_produces_fallback(self) -> None:
        planner = build_planner(make_search_settings(), "")

        with patch("search.planner.log") as mock_log:
            plan = planner.plan("find boiler warranty")

        mock_log.warning.assert_called()
        _assert_is_fallback_plan(plan, "find boiler warranty")

    def test_non_json_response_produces_fallback(self) -> None:
        planner = build_planner(
            make_search_settings(), "Sorry, I cannot help with that."
        )

        with patch("search.planner.log") as mock_log:
            plan = planner.plan("find boiler warranty")

        mock_log.warning.assert_called()
        _assert_is_fallback_plan(plan, "find boiler warranty")

    def test_json_missing_required_keys_produces_fallback(self) -> None:
        """A JSON object that lacks 'semantic_queries' is treated as malformed."""
        planner = build_planner(
            make_search_settings(), '{"something": "unexpected"}'
        )

        with patch("search.planner.log") as mock_log:
            plan = planner.plan("missing key query")

        mock_log.warning.assert_called()
        _assert_is_fallback_plan(plan, "missing key query")

    def test_json_array_response_produces_fallback(self) -> None:
        """A JSON array (not an object) is treated as malformed."""
        planner = build_planner(make_search_settings(), "[1, 2, 3]")

        with patch("search.planner.log") as mock_log:
            plan = planner.plan("array response query")

        mock_log.warning.assert_called()
        _assert_is_fallback_plan(plan, "array response query")

    def test_none_content_produces_fallback(self) -> None:
        """A None choices[0].message.content is treated as empty."""
        planner = build_planner(make_search_settings(), None)

        with patch("search.planner.log") as mock_log:
            plan = planner.plan("none content query")

        mock_log.warning.assert_called()
        _assert_is_fallback_plan(plan, "none content query")

    def test_fallback_plan_raw_query_preserved(self) -> None:
        """The raw query is always the sole semantic_query in the fallback."""
        raw = "find my tax return from 2023"
        plan = build_planner(make_search_settings(), "not json at all").plan(raw)

        assert plan.semantic_queries == (raw,)


# ---------------------------------------------------------------------------
# I1 — string-valued list fields are not iterated character-by-character
# ---------------------------------------------------------------------------


class TestStringValuedListFields:
    """An LLM that emits a bare string for a list field must not poison retrieval.

    Finding I1: ``tuple(str(t) for t in "invoice")`` yields
    ``('i','n','v','o','i','c','e')``.  The planner coerces a bare string into
    a single-element list instead.
    """

    def test_string_keyword_terms_becomes_single_term(self) -> None:
        """keyword_terms="invoice" → ("invoice",), not the characters of it."""
        payload = json.dumps(
            {
                "semantic_queries": ["find the invoice"],
                "keyword_terms": "invoice",  # WRONG shape: a bare string.
                "filter_candidates": {
                    "correspondent": None,
                    "document_type": None,
                    "tags": [],
                    "date_from": None,
                    "date_to": None,
                },
                "sub_questions": [],
            }
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "find the invoice"
        )

        assert plan.keyword_terms == ("invoice",)

    def test_string_semantic_queries_becomes_single_query(self) -> None:
        """semantic_queries as a bare string is wrapped, not exploded."""
        payload = json.dumps(
            {
                "semantic_queries": "boiler warranty expiry",
                "keyword_terms": [],
                "filter_candidates": {
                    "correspondent": None,
                    "document_type": None,
                    "tags": [],
                    "date_from": None,
                    "date_to": None,
                },
                "sub_questions": [],
            }
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "the raw query"
        )

        assert plan.semantic_queries == ("boiler warranty expiry",)

    def test_string_sub_questions_becomes_single_question(self) -> None:
        payload = json.dumps(
            {
                "semantic_queries": ["q"],
                "keyword_terms": [],
                "filter_candidates": {
                    "correspondent": None,
                    "document_type": None,
                    "tags": [],
                    "date_from": None,
                    "date_to": None,
                },
                "sub_questions": "when was it installed?",
            }
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "the raw query"
        )

        assert plan.sub_questions == ("when was it installed?",)

    def test_string_filter_tags_becomes_single_tag(self) -> None:
        """filter_candidates.tags as a bare string is wrapped, not exploded."""
        payload = json.dumps(
            {
                "semantic_queries": ["q"],
                "keyword_terms": [],
                "filter_candidates": {
                    "correspondent": None,
                    "document_type": None,
                    "tags": "electricity",  # WRONG shape: a bare string.
                    "date_from": None,
                    "date_to": None,
                },
                "sub_questions": [],
            }
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "the raw query"
        )

        assert plan.filter_candidates.tags == ("electricity",)

    def test_non_string_scalar_list_field_becomes_empty(self) -> None:
        """A non-string scalar (e.g. an int) for a list field yields no terms."""
        payload = json.dumps(
            {
                "semantic_queries": ["q"],
                "keyword_terms": 12345,  # WRONG shape: an int.
                "filter_candidates": {
                    "correspondent": None,
                    "document_type": None,
                    "tags": [],
                    "date_from": None,
                    "date_to": None,
                },
                "sub_questions": [],
            }
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "the raw query"
        )

        assert plan.keyword_terms == ()


# ---------------------------------------------------------------------------
# I2 — _str_or_none rejects containers rather than repr-ing them
# ---------------------------------------------------------------------------


class TestStrOrNoneRejectsContainers:
    """A list/dict value for a scalar filter field must not become its repr.

    Finding I2: ``str(["npower", "EDF"]).strip()`` produces the filter
    candidate ``"['npower', 'EDF']"`` which resolves against nothing.
    """

    def test_list_correspondent_becomes_none(self) -> None:
        payload = json.dumps(
            {
                "semantic_queries": ["q"],
                "keyword_terms": [],
                "filter_candidates": {
                    "correspondent": ["npower", "EDF"],  # WRONG shape: a list.
                    "document_type": None,
                    "tags": [],
                    "date_from": None,
                    "date_to": None,
                },
                "sub_questions": [],
            }
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "the raw query"
        )

        assert plan.filter_candidates.correspondent is None

    def test_dict_document_type_becomes_none(self) -> None:
        payload = json.dumps(
            {
                "semantic_queries": ["q"],
                "keyword_terms": [],
                "filter_candidates": {
                    "correspondent": None,
                    "document_type": {"name": "invoice"},  # WRONG shape: a dict.
                    "tags": [],
                    "date_from": None,
                    "date_to": None,
                },
                "sub_questions": [],
            }
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "the raw query"
        )

        assert plan.filter_candidates.document_type is None
