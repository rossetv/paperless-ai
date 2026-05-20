"""Tests for search.planner — LLM query planner.

Verifies the QueryPlanner contract (spec §6.1):
- A well-formed mock LLM response is parsed into the expected QueryPlan.
- Relative-date language in the response produces date_from/date_to candidates.
- A malformed / empty / non-JSON response degrades to the safe fallback plan.
- The configured SEARCH_PLANNER_MODEL is the model requested.
- A warning is logged on degraded fallback.
- Every OpenAI API error — retryable AND non-retryable (AuthenticationError,
  etc.) — degrades to the fallback plan; plan() never raises (findings C1/C2).
- String-valued list fields are not iterated character-by-character (I1).

LLM mocking: QueryPlanner subclasses OpenAIChatMixin.  Tests patch the
instance's ``_create_completion`` with a fake — exactly as
tests/unit/classifier/test_provider.py does — never via constructor injection
(QueryPlanner takes only ``settings``).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import openai
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
    """Build a minimal Settings-like mock for QueryPlanner.

    ``MAX_RETRIES`` / ``MAX_RETRY_BACKOFF_SECONDS`` are real ints so the
    inherited ``@retry`` decorator is well-formed even though tests patch
    ``_create_completion`` and never actually exercise the retry loop.
    """
    mock = MagicMock()
    mock.SEARCH_PLANNER_MODEL = planner_model
    mock.AI_MODELS = ai_models or ["gpt-5.4-mini", "gpt-5.4", "o4-mini"]
    mock.MAX_RETRIES = 3
    mock.MAX_RETRY_BACKOFF_SECONDS = 30
    return mock


def _make_completion(response_content: str | None) -> MagicMock:
    """Build an OpenAI-shaped chat completion returning *response_content*."""
    choice = MagicMock()
    choice.message.content = response_content
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _make_planner(
    settings: MagicMock,
    response_content: str | None,
) -> QueryPlanner:
    """Build a QueryPlanner whose ``_create_completion`` returns *response_content*."""
    planner = QueryPlanner(settings)
    planner._create_completion = MagicMock(  # type: ignore[method-assign]
        return_value=_make_completion(response_content)
    )
    return planner


def _api_error(message: str = "server error") -> openai.APIError:
    """Create a generic (non-typed) APIError — the base of the openai error tree."""
    return openai.APIError(message=message, request=MagicMock(), body=None)


def _internal_server_error() -> openai.InternalServerError:
    """Create a retryable 5xx error."""
    response = MagicMock()
    response.status_code = 500
    response.headers = {}
    return openai.InternalServerError(message="boom", response=response, body=None)


def _authentication_error() -> openai.AuthenticationError:
    """Create a non-retryable 401 — a wrong/expired OPENAI_API_KEY."""
    response = MagicMock()
    response.status_code = 401
    response.headers = {}
    return openai.AuthenticationError(
        message="Incorrect API key provided", response=response, body=None
    )


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
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("find my boiler warranty")

        assert "boiler warranty letter" in plan.semantic_queries
        assert "heating system guarantee" in plan.semantic_queries

    def test_keyword_terms_are_parsed(self) -> None:
        payload = _make_planner_json(keyword_terms=["boiler", "warranty", "Worcester Bosch"])
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("Worcester Bosch boiler warranty")

        assert "boiler" in plan.keyword_terms
        assert "warranty" in plan.keyword_terms
        assert "Worcester Bosch" in plan.keyword_terms

    def test_filter_candidates_correspondent_is_parsed(self) -> None:
        payload = _make_planner_json(correspondent="npower")
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("npower electricity bill")

        assert plan.filter_candidates.correspondent == "npower"

    def test_filter_candidates_document_type_is_parsed(self) -> None:
        payload = _make_planner_json(document_type="invoice")
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("latest invoice")

        assert plan.filter_candidates.document_type == "invoice"

    def test_filter_candidates_tags_are_parsed(self) -> None:
        payload = _make_planner_json(tags=["electricity", "utility"])
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("electricity utility bills")

        assert "electricity" in plan.filter_candidates.tags
        assert "utility" in plan.filter_candidates.tags

    def test_sub_questions_are_parsed(self) -> None:
        payload = _make_planner_json(
            sub_questions=["When was the boiler installed?", "What is the expiry date?"],
        )
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("boiler installation and warranty expiry")

        assert "When was the boiler installed?" in plan.sub_questions
        assert "What is the expiry date?" in plan.sub_questions

    def test_returns_query_plan_dataclass(self) -> None:
        planner = _make_planner(_make_settings(), _make_planner_json())
        plan = planner.plan("any query")

        assert isinstance(plan, QueryPlan)

    def test_filter_candidates_is_frozen_dataclass(self) -> None:
        planner = _make_planner(_make_settings(), _make_planner_json())
        plan = planner.plan("any query")

        assert isinstance(plan.filter_candidates, FilterCandidates)
        with pytest.raises(Exception):  # FrozenInstanceError
            plan.filter_candidates.correspondent = "changed"  # type: ignore[misc]

    def test_json_wrapped_in_markdown_fences_is_still_parsed(self) -> None:
        """The LLM may wrap JSON in triple-backtick fences — tolerate this."""
        payload = "```json\n" + _make_planner_json(keyword_terms=["VAT", "invoice"]) + "\n```"
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("VAT invoice")

        assert "VAT" in plan.keyword_terms


# ---------------------------------------------------------------------------
# Relative-date language
# ---------------------------------------------------------------------------


class TestRelativeDateLanguage:
    """Date strings from the LLM end up in filter_candidates.date_from/date_to."""

    def test_date_from_is_propagated(self) -> None:
        payload = _make_planner_json(date_from="2024-01-01", date_to="2024-12-31")
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("invoices from last year")

        assert plan.filter_candidates.date_from == "2024-01-01"
        assert plan.filter_candidates.date_to == "2024-12-31"

    def test_date_to_only_is_propagated(self) -> None:
        payload = _make_planner_json(date_to="2025-03-31")
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("documents since March")

        assert plan.filter_candidates.date_to == "2025-03-31"
        assert plan.filter_candidates.date_from is None

    def test_null_dates_produce_none(self) -> None:
        payload = _make_planner_json(date_from=None, date_to=None)
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("all documents")

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
        planner = _make_planner(_make_settings(), "")

        with patch("search.planner.log") as mock_log:
            plan = planner.plan("find boiler warranty")

        mock_log.warning.assert_called()
        self._assert_is_fallback_plan(plan, "find boiler warranty")

    def test_non_json_response_produces_fallback(self) -> None:
        planner = _make_planner(_make_settings(), "Sorry, I cannot help with that.")

        with patch("search.planner.log") as mock_log:
            plan = planner.plan("find boiler warranty")

        mock_log.warning.assert_called()
        self._assert_is_fallback_plan(plan, "find boiler warranty")

    def test_json_missing_required_keys_produces_fallback(self) -> None:
        """A JSON object that lacks 'semantic_queries' is treated as malformed."""
        planner = _make_planner(_make_settings(), '{"something": "unexpected"}')

        with patch("search.planner.log") as mock_log:
            plan = planner.plan("missing key query")

        mock_log.warning.assert_called()
        self._assert_is_fallback_plan(plan, "missing key query")

    def test_json_array_response_produces_fallback(self) -> None:
        """A JSON array (not an object) is treated as malformed."""
        planner = _make_planner(_make_settings(), "[1, 2, 3]")

        with patch("search.planner.log") as mock_log:
            plan = planner.plan("array response query")

        mock_log.warning.assert_called()
        self._assert_is_fallback_plan(plan, "array response query")

    def test_none_content_produces_fallback(self) -> None:
        """A None choices[0].message.content is treated as empty."""
        planner = _make_planner(_make_settings(), None)

        with patch("search.planner.log") as mock_log:
            plan = planner.plan("none content query")

        mock_log.warning.assert_called()
        self._assert_is_fallback_plan(plan, "none content query")

    def test_fallback_plan_raw_query_preserved(self) -> None:
        """The raw query is always the sole semantic_query in the fallback."""
        raw = "find my tax return from 2023"
        planner = _make_planner(_make_settings(), "not json at all")
        plan = planner.plan(raw)

        assert plan.semantic_queries == (raw,)


# ---------------------------------------------------------------------------
# Model selection: SEARCH_PLANNER_MODEL is the model requested
# ---------------------------------------------------------------------------


class TestModelSelection:
    """The planner uses SEARCH_PLANNER_MODEL as the primary model."""

    def test_configured_model_is_requested(self) -> None:
        settings = _make_settings(planner_model="gpt-5.4-mini", ai_models=["gpt-5.4-mini", "gpt-5.4"])
        planner = _make_planner(settings, _make_planner_json())
        planner.plan("test query")

        call_kwargs = planner._create_completion.call_args  # type: ignore[attr-defined]
        assert call_kwargs is not None
        assert call_kwargs.kwargs["model"] == "gpt-5.4-mini"

    def test_different_configured_model_is_requested(self) -> None:
        settings = _make_settings(planner_model="gemma3:12b", ai_models=["gemma3:12b"])
        planner = _make_planner(settings, _make_planner_json())
        planner.plan("test query")

        call_kwargs = planner._create_completion.call_args  # type: ignore[attr-defined]
        assert call_kwargs.kwargs["model"] == "gemma3:12b"

    def test_exactly_one_llm_call_per_plan(self) -> None:
        """The planner makes exactly one LLM call per plan() invocation."""
        planner = _make_planner(_make_settings(), _make_planner_json())
        planner.plan("single call test")

        assert planner._create_completion.call_count == 1  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AI_MODELS fallback chain: fallback model is tried on error
# ---------------------------------------------------------------------------


class TestModelFallback:
    """When the primary model raises an OpenAI error, the next in AI_MODELS is tried."""

    def test_fallback_to_second_model_on_api_error(self) -> None:
        settings = _make_settings(
            planner_model="gpt-5.4-mini",
            ai_models=["gpt-5.4-mini", "gpt-5.4"],
        )
        payload = _make_planner_json(semantic_queries=["fallback worked"])

        planner = QueryPlanner(settings)
        # First model raises a retryable error; second model succeeds.
        planner._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=[_internal_server_error(), _make_completion(payload)]
        )

        plan = planner.plan("test fallback")

        assert planner._create_completion.call_count == 2  # type: ignore[attr-defined]
        assert "fallback worked" in plan.semantic_queries


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

    def _assert_is_fallback_plan(self, plan: QueryPlan, raw_query: str) -> None:
        assert plan.semantic_queries == (raw_query,)
        assert plan.keyword_terms == ()
        assert plan.sub_questions == ()
        assert plan.filter_candidates == _empty_filter_candidates()

    def test_authentication_error_degrades_to_fallback(self) -> None:
        """A wrong/expired OPENAI_API_KEY must not raise out of plan()."""
        settings = _make_settings(
            planner_model="gpt-5.4-mini", ai_models=["gpt-5.4-mini", "gpt-5.4"]
        )
        planner = QueryPlanner(settings)
        # Every model attempt raises AuthenticationError — non-retryable.
        planner._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=_authentication_error()
        )

        # Must NOT raise.
        plan = planner.plan("find my boiler warranty")

        self._assert_is_fallback_plan(plan, "find my boiler warranty")
        # Both configured models were attempted before giving up.
        assert planner._create_completion.call_count == 2  # type: ignore[attr-defined]

    def test_generic_api_error_degrades_to_fallback(self) -> None:
        """A bare openai.APIError (no subclass) also degrades, never escapes."""
        settings = _make_settings(planner_model="m", ai_models=["m"])
        planner = QueryPlanner(settings)
        planner._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=_api_error()
        )

        plan = planner.plan("a query")

        self._assert_is_fallback_plan(plan, "a query")

    def test_authentication_then_success_falls_through(self) -> None:
        """A non-retryable error on model 1 still lets model 2 answer."""
        settings = _make_settings(
            planner_model="gpt-5.4-mini", ai_models=["gpt-5.4-mini", "gpt-5.4"]
        )
        payload = _make_planner_json(semantic_queries=["second model answered"])
        planner = QueryPlanner(settings)
        planner._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=[_authentication_error(), _make_completion(payload)]
        )

        plan = planner.plan("a query")

        assert "second model answered" in plan.semantic_queries
        assert planner._create_completion.call_count == 2  # type: ignore[attr-defined]


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
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("find the invoice")

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
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("the raw query")

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
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("the raw query")

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
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("the raw query")

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
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("the raw query")

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
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("the raw query")

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
        planner = _make_planner(_make_settings(), payload)
        plan = planner.plan("the raw query")

        assert plan.filter_candidates.document_type is None
