"""Tests for search.planner — parsing the LLM planner response.

Verifies the QueryPlanner parsing contract (spec §6.1):
- A well-formed mock LLM response is parsed into the expected RetrievalPlan.
- A multi-spec response produces multiple PlannedSpec objects with the right
  modes, semantic/keywords, filter_guess fields, and rationale strings.
- A malformed / empty / non-JSON response degrades to the safe fallback plan.
- The fallback plan is a RetrievalPlan with a single broad semantic spec.
- More than SEARCH_PLANNER_MAX_SPECS specs in the response → capped.
- Clarify response → ClarifyNeeded when the gate is on.
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

import json as _json
from unittest.mock import patch

import pytest

from search.models import (
    EMPTY_FILTER_CANDIDATES,
    ClarifyNeeded,
    FilterCandidates,
    PlannedSpec,
    RetrievalPlan,
)
from tests.helpers.factories import make_search_settings
from tests.helpers.llm import _make_spec, planner_response_json
from tests.unit.search.conftest import build_planner


def _clarify_json(reason: str = "Query is too vague.") -> str:
    """Return a well-formed clarify JSON response (new planner shape)."""
    return _json.dumps({"specs": [], "clarify": {"reason": reason}})


def test_plan_forwards_taxonomy_block_into_the_user_message() -> None:
    """The taxonomy block reaches the planner LLM call's user message."""
    planner = build_planner(make_search_settings(), planner_response_json())

    planner.plan("how much tax did I pay", taxonomy_block="TAXBLOCK-MARKER")

    messages = planner._create_completion.call_args.kwargs["messages"]
    user = next(m["content"] for m in messages if m["role"] == "user")
    assert "TAXBLOCK-MARKER" in user


def _assert_is_fallback_plan(plan: RetrievalPlan, raw_query: str) -> None:
    """Assert *plan* is the minimal safe fallback for *raw_query*."""
    assert isinstance(plan, RetrievalPlan)
    assert len(plan.specs) == 1
    spec = plan.specs[0]
    assert spec.mode == "semantic"
    assert spec.semantic == raw_query
    assert spec.keywords == ()
    assert spec.filter_guess == EMPTY_FILTER_CANDIDATES
    assert "fallback" in spec.rationale


# ---------------------------------------------------------------------------
# Well-formed multi-spec response
# ---------------------------------------------------------------------------


class TestWellFormedResponse:
    """A valid JSON response is parsed into a fully-populated RetrievalPlan."""

    def test_returns_retrieval_plan_dataclass(self) -> None:
        plan = build_planner(make_search_settings(), planner_response_json()).plan(
            "any query"
        )

        assert isinstance(plan, RetrievalPlan)

    def test_single_spec_parsed_correctly(self) -> None:
        payload = planner_response_json(
            specs=[
                _make_spec(
                    mode="semantic",
                    semantic="boiler warranty letter",
                    rationale="broad semantic search",
                )
            ]
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "find my boiler warranty"
        )

        assert isinstance(plan, RetrievalPlan)
        assert len(plan.specs) == 1
        spec = plan.specs[0]
        assert spec.mode == "semantic"
        assert spec.semantic == "boiler warranty letter"
        assert spec.rationale == "broad semantic search"

    def test_multiple_specs_are_all_parsed(self) -> None:
        payload = planner_response_json(
            specs=[
                _make_spec(
                    mode="semantic",
                    semantic="boiler warranty letter",
                    rationale="semantic spec",
                ),
                _make_spec(
                    mode="keyword",
                    semantic=None,
                    keywords=["Worcester Bosch", "warranty"],
                    rationale="keyword spec",
                ),
                _make_spec(
                    mode="semantic",
                    semantic="heating system guarantee",
                    rationale="broad recall spec",
                ),
            ]
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "find my boiler warranty"
        )

        assert isinstance(plan, RetrievalPlan)
        assert len(plan.specs) == 3
        modes = [s.mode for s in plan.specs]
        assert "semantic" in modes
        assert "keyword" in modes

    def test_semantic_field_is_parsed(self) -> None:
        payload = planner_response_json(
            specs=[
                _make_spec(
                    mode="semantic",
                    semantic="boiler warranty letter",
                )
            ]
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "find my boiler warranty"
        )

        assert plan.specs[0].semantic == "boiler warranty letter"

    def test_keywords_are_parsed(self) -> None:
        payload = planner_response_json(
            specs=[
                _make_spec(
                    mode="keyword",
                    semantic=None,
                    keywords=["boiler", "warranty", "Worcester Bosch"],
                )
            ]
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "Worcester Bosch boiler warranty"
        )

        assert "boiler" in plan.specs[0].keywords
        assert "warranty" in plan.specs[0].keywords
        assert "Worcester Bosch" in plan.specs[0].keywords

    def test_filter_guess_correspondent_is_parsed(self) -> None:
        payload = planner_response_json(specs=[_make_spec(correspondent="npower")])
        plan = build_planner(make_search_settings(), payload).plan(
            "npower electricity bill"
        )

        assert plan.specs[0].filter_guess.correspondent == "npower"

    def test_filter_guess_document_type_is_parsed(self) -> None:
        payload = planner_response_json(specs=[_make_spec(document_type="invoice")])
        plan = build_planner(make_search_settings(), payload).plan("latest invoice")

        assert plan.specs[0].filter_guess.document_type == "invoice"

    def test_filter_guess_tags_are_parsed(self) -> None:
        payload = planner_response_json(
            specs=[_make_spec(tags=["electricity", "utility"])]
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "electricity utility bills"
        )

        assert "electricity" in plan.specs[0].filter_guess.tags
        assert "utility" in plan.specs[0].filter_guess.tags

    def test_filter_guess_dates_are_parsed(self) -> None:
        payload = planner_response_json(
            specs=[_make_spec(date_from="2024-01-01", date_to="2024-12-31")]
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "invoices from last year"
        )

        assert plan.specs[0].filter_guess.date_from == "2024-01-01"
        assert plan.specs[0].filter_guess.date_to == "2024-12-31"

    def test_rationale_is_parsed(self) -> None:
        payload = planner_response_json(
            specs=[_make_spec(rationale="tight keyword + filter for precision")]
        )
        plan = build_planner(make_search_settings(), payload).plan("my query")

        assert plan.specs[0].rationale == "tight keyword + filter for precision"

    def test_filter_guess_is_frozen_dataclass(self) -> None:
        plan = build_planner(make_search_settings(), planner_response_json()).plan(
            "any query"
        )

        assert isinstance(plan.specs[0].filter_guess, FilterCandidates)
        with pytest.raises(Exception):  # FrozenInstanceError
            plan.specs[0].filter_guess.correspondent = "changed"  # type: ignore[misc]

    def test_specs_is_frozen_tuple(self) -> None:
        plan = build_planner(make_search_settings(), planner_response_json()).plan(
            "any query"
        )

        assert isinstance(plan.specs, tuple)

    def test_spec_is_planned_spec_dataclass(self) -> None:
        plan = build_planner(make_search_settings(), planner_response_json()).plan(
            "any query"
        )

        assert isinstance(plan.specs[0], PlannedSpec)

    def test_json_wrapped_in_markdown_fences_is_still_parsed(self) -> None:
        """The LLM may wrap JSON in triple-backtick fences — tolerate this."""
        payload = (
            "```json\n"
            + planner_response_json(
                specs=[
                    _make_spec(
                        mode="keyword", semantic=None, keywords=["VAT", "invoice"]
                    )
                ]
            )
            + "\n```"
        )
        plan = build_planner(make_search_settings(), payload).plan("VAT invoice")

        assert "VAT" in plan.specs[0].keywords


# ---------------------------------------------------------------------------
# Plan-width cap
# ---------------------------------------------------------------------------


class TestPlanWidthIsCapped:
    """The number of specs is capped at SEARCH_PLANNER_MAX_SPECS.

    A misbehaving or adversarial model returning more specs than asked must not
    multiply the retrieval fan-out on a billable, network-facing endpoint.
    """

    def test_specs_are_capped_at_max(self) -> None:
        max_specs = 4
        payload = planner_response_json(
            specs=[
                _make_spec(semantic=f"query {i}", rationale=f"spec {i}")
                for i in range(10)
            ]
        )
        plan = build_planner(
            make_search_settings(SEARCH_PLANNER_MAX_SPECS=max_specs), payload
        ).plan("a query")

        assert len(plan.specs) == max_specs

    def test_cap_keeps_the_first_specs_in_order(self) -> None:
        """The cap truncates the tail, preserving the model's leading specs."""
        max_specs = 3
        payload = planner_response_json(
            specs=[
                _make_spec(semantic=f"spec {i}", rationale=f"rationale {i}")
                for i in range(5)
            ]
        )
        plan = build_planner(
            make_search_settings(SEARCH_PLANNER_MAX_SPECS=max_specs), payload
        ).plan("a query")

        assert len(plan.specs) == 3
        assert plan.specs[0].semantic == "spec 0"
        assert plan.specs[1].semantic == "spec 1"
        assert plan.specs[2].semantic == "spec 2"

    def test_within_limit_specs_are_untouched(self) -> None:
        """A compliant plan (≤ max_specs) is passed through unchanged."""
        payload = planner_response_json(
            specs=[
                _make_spec(semantic="spec one"),
                _make_spec(semantic="spec two"),
            ]
        )
        plan = build_planner(
            make_search_settings(SEARCH_PLANNER_MAX_SPECS=8), payload
        ).plan("a query")

        assert len(plan.specs) == 2

    def test_default_max_specs_is_eight(self) -> None:
        """The default SEARCH_PLANNER_MAX_SPECS is 8 — a model returning 8 is fine."""
        payload = planner_response_json(
            specs=[_make_spec(semantic=f"q {i}") for i in range(8)]
        )
        plan = build_planner(
            make_search_settings(SEARCH_PLANNER_MAX_SPECS=8), payload
        ).plan("a query")

        assert len(plan.specs) == 8


# ---------------------------------------------------------------------------
# Relative-date language
# ---------------------------------------------------------------------------


class TestRelativeDateLanguage:
    """Date strings from the LLM end up in filter_guess.date_from/date_to."""

    def test_date_from_is_propagated(self) -> None:
        payload = planner_response_json(
            specs=[_make_spec(date_from="2024-01-01", date_to="2024-12-31")]
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "invoices from last year"
        )

        assert plan.specs[0].filter_guess.date_from == "2024-01-01"
        assert plan.specs[0].filter_guess.date_to == "2024-12-31"

    def test_date_to_only_is_propagated(self) -> None:
        payload = planner_response_json(
            specs=[_make_spec(date_from=None, date_to="2025-03-31")]
        )
        plan = build_planner(make_search_settings(), payload).plan(
            "documents since March"
        )

        assert plan.specs[0].filter_guess.date_to == "2025-03-31"
        assert plan.specs[0].filter_guess.date_from is None

    def test_null_dates_produce_none(self) -> None:
        payload = planner_response_json(
            specs=[_make_spec(date_from=None, date_to=None)]
        )
        plan = build_planner(make_search_settings(), payload).plan("all documents")

        assert plan.specs[0].filter_guess.date_from is None
        assert plan.specs[0].filter_guess.date_to is None


# ---------------------------------------------------------------------------
# Malformed / empty / non-JSON response: safe fallback
# ---------------------------------------------------------------------------


class TestFallbackOnBadResponse:
    """A bad LLM response degrades to a safe single-spec plan and logs a warning."""

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
        """A JSON object that lacks 'specs' is treated as malformed."""
        planner = build_planner(make_search_settings(), '{"something": "unexpected"}')

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
        """The raw query is always the sole semantic spec in the fallback."""
        raw = "find my tax return from 2023"
        plan = build_planner(make_search_settings(), "not json at all").plan(raw)

        assert plan.specs[0].semantic == raw

    def test_fallback_plan_is_retrieval_plan(self) -> None:
        """The fallback is a RetrievalPlan, not a QueryPlan or ClarifyNeeded."""
        plan = build_planner(make_search_settings(), "").plan("any query")

        assert isinstance(plan, RetrievalPlan)

    def test_empty_specs_list_produces_broad_semantic_fallback(self) -> None:
        """A valid response with ``"specs": []`` yields the broad-semantic spec (H3).

        The pipeline invariant is "a plan always carries at least one spec". A
        model returning an empty specs list (well-formed JSON, just no specs)
        must not leave a spec-less plan with nothing to retrieve — the planner
        substitutes the single broad-semantic fallback on the raw query, exactly
        as the malformed-response path does.
        """
        payload = _json.dumps({"specs": []})
        planner = build_planner(make_search_settings(), payload)

        plan = planner.plan("find boiler warranty")

        _assert_is_fallback_plan(plan, "find boiler warranty")

    def test_specs_of_only_non_dict_junk_produces_fallback(self) -> None:
        """A specs list of only non-dict junk is filtered to empty → fallback (H3).

        The parser drops non-dict items; if that leaves the list empty the same
        broad-semantic back-fill must apply so the plan is never spec-less.
        """
        payload = _json.dumps({"specs": ["not-a-spec", 42, None]})
        planner = build_planner(make_search_settings(), payload)

        plan = planner.plan("array junk query")

        _assert_is_fallback_plan(plan, "array junk query")


# ---------------------------------------------------------------------------
# I1 — string-valued list fields are not iterated character-by-character
# ---------------------------------------------------------------------------


class TestStringValuedListFields:
    """An LLM that emits a bare string for a list field must not poison retrieval.

    Finding I1: ``tuple(str(t) for t in "invoice")`` yields
    ``('i','n','v','o','i','c','e')``.  The planner coerces a bare string into
    a single-element list instead.
    """

    def test_string_keywords_becomes_single_keyword(self) -> None:
        """keywords="invoice" → ("invoice",), not the characters of it."""
        payload = _json.dumps(
            {
                "specs": [
                    {
                        "mode": "keyword",
                        "semantic": None,
                        "keywords": "invoice",  # WRONG shape: a bare string.
                        "filter_guess": {
                            "correspondent": None,
                            "document_type": None,
                            "tags": [],
                            "date_from": None,
                            "date_to": None,
                        },
                        "rationale": "test",
                    }
                ],
                "clarify": None,
            }
        )
        plan = build_planner(make_search_settings(), payload).plan("find the invoice")

        assert plan.specs[0].keywords == ("invoice",)

    def test_string_filter_tags_becomes_single_tag(self) -> None:
        """filter_guess.tags as a bare string is wrapped, not exploded."""
        payload = _json.dumps(
            {
                "specs": [
                    {
                        "mode": "semantic",
                        "semantic": "q",
                        "keywords": [],
                        "filter_guess": {
                            "correspondent": None,
                            "document_type": None,
                            "tags": "electricity",  # WRONG shape: a bare string.
                            "date_from": None,
                            "date_to": None,
                        },
                        "rationale": "test",
                    }
                ],
                "clarify": None,
            }
        )
        plan = build_planner(make_search_settings(), payload).plan("the raw query")

        assert plan.specs[0].filter_guess.tags == ("electricity",)

    def test_non_string_scalar_list_field_becomes_empty(self) -> None:
        """A non-string scalar (e.g. an int) for a list field yields no terms."""
        payload = _json.dumps(
            {
                "specs": [
                    {
                        "mode": "keyword",
                        "semantic": None,
                        "keywords": 12345,  # WRONG shape: an int.
                        "filter_guess": {
                            "correspondent": None,
                            "document_type": None,
                            "tags": [],
                            "date_from": None,
                            "date_to": None,
                        },
                        "rationale": "test",
                    }
                ],
                "clarify": None,
            }
        )
        plan = build_planner(make_search_settings(), payload).plan("the raw query")

        assert plan.specs[0].keywords == ()


# ---------------------------------------------------------------------------
# I2 — _str_or_none rejects containers rather than repr-ing them
# ---------------------------------------------------------------------------


class TestStrOrNoneRejectsContainers:
    """A list/dict value for a scalar filter field must not become its repr.

    Finding I2: ``str(["npower", "EDF"]).strip()`` produces the filter
    candidate ``"['npower', 'EDF']"`` which resolves against nothing.
    """

    def test_list_correspondent_becomes_none(self) -> None:
        payload = _json.dumps(
            {
                "specs": [
                    {
                        "mode": "semantic",
                        "semantic": "q",
                        "keywords": [],
                        "filter_guess": {
                            "correspondent": ["npower", "EDF"],  # WRONG: a list.
                            "document_type": None,
                            "tags": [],
                            "date_from": None,
                            "date_to": None,
                        },
                        "rationale": "test",
                    }
                ],
                "clarify": None,
            }
        )
        plan = build_planner(make_search_settings(), payload).plan("the raw query")

        assert plan.specs[0].filter_guess.correspondent is None

    def test_dict_document_type_becomes_none(self) -> None:
        payload = _json.dumps(
            {
                "specs": [
                    {
                        "mode": "semantic",
                        "semantic": "q",
                        "keywords": [],
                        "filter_guess": {
                            "correspondent": None,
                            "document_type": {"name": "invoice"},  # WRONG: a dict.
                            "tags": [],
                            "date_from": None,
                            "date_to": None,
                        },
                        "rationale": "test",
                    }
                ],
                "clarify": None,
            }
        )
        plan = build_planner(make_search_settings(), payload).plan("the raw query")

        assert plan.specs[0].filter_guess.document_type is None


# ---------------------------------------------------------------------------
# Mode defaulting — malformed mode falls back to "semantic"
# ---------------------------------------------------------------------------


class TestModeCoercion:
    """A malformed or absent mode value falls back to 'semantic' rather than crashing."""

    def test_invalid_mode_defaults_to_semantic(self) -> None:
        payload = _json.dumps(
            {
                "specs": [
                    {
                        "mode": "vector",  # not a valid mode
                        "semantic": "some query",
                        "keywords": [],
                        "filter_guess": {
                            "correspondent": None,
                            "document_type": None,
                            "tags": [],
                            "date_from": None,
                            "date_to": None,
                        },
                        "rationale": "test",
                    }
                ],
                "clarify": None,
            }
        )
        plan = build_planner(make_search_settings(), payload).plan("a query")

        assert plan.specs[0].mode == "semantic"

    def test_null_mode_defaults_to_semantic(self) -> None:
        payload = _json.dumps(
            {
                "specs": [
                    {
                        "mode": None,
                        "semantic": "some query",
                        "keywords": [],
                        "filter_guess": {
                            "correspondent": None,
                            "document_type": None,
                            "tags": [],
                            "date_from": None,
                            "date_to": None,
                        },
                        "rationale": "test",
                    }
                ],
                "clarify": None,
            }
        )
        plan = build_planner(make_search_settings(), payload).plan("a query")

        assert plan.specs[0].mode == "semantic"


# ---------------------------------------------------------------------------
# System prompt byte-stability
# ---------------------------------------------------------------------------


class TestPlannerDateInUserTurn:
    """The planner sends a byte-stable system prompt and the date in the user turn."""

    def test_user_message_carries_todays_date(self) -> None:
        planner = build_planner(make_search_settings(), planner_response_json())
        planner.plan("any query")

        call = planner._create_completion.call_args  # type: ignore[attr-defined]
        messages = call.kwargs["messages"]
        system = next(m["content"] for m in messages if m["role"] == "system")
        user = next(m["content"] for m in messages if m["role"] == "user")
        assert "{today}" not in system
        assert "search-query planning engine" in system
        # The user turn carries both the query and a concrete ISO date.
        assert "any query" in user
        import re

        assert re.search(r"\d{4}-\d{2}-\d{2}", user) is not None


# ---------------------------------------------------------------------------
# Adequacy gate (Layer 1) — ClarifyNeeded vs RetrievalPlan, fail-open
# ---------------------------------------------------------------------------


class TestAdequacyGate:
    """The planner returns ClarifyNeeded when the LLM signals the query is too
    vague, but degrades safely to a RetrievalPlan on every failure path.

    Governed by SEARCH_GATE_ADEQUACY (default True). When False, a clarify
    JSON still produces a RetrievalPlan (the gate is bypassed).
    """

    def test_clarify_json_with_gate_on_returns_clarify_needed(self) -> None:
        """A valid clarify response → ClarifyNeeded when SEARCH_GATE_ADEQUACY=True."""
        planner = build_planner(
            make_search_settings(SEARCH_GATE_ADEQUACY=True),
            _clarify_json("Too vague — add more detail."),
        )
        outcome = planner.plan("life")

        assert isinstance(outcome, ClarifyNeeded)
        assert outcome.reason == "Too vague — add more detail."

    def test_clarify_json_carries_the_models_reason(self) -> None:
        """The ClarifyNeeded.reason is the model's reason verbatim."""
        reason = "A bare entity name gives me nothing to search for."
        planner = build_planner(
            make_search_settings(SEARCH_GATE_ADEQUACY=True),
            _clarify_json(reason),
        )
        outcome = planner.plan("HMRC")

        assert isinstance(outcome, ClarifyNeeded)
        assert outcome.reason == reason

    def test_normal_plan_json_still_returns_retrieval_plan(self) -> None:
        """A normal plan response → RetrievalPlan regardless of gate setting."""
        planner = build_planner(
            make_search_settings(SEARCH_GATE_ADEQUACY=True),
            planner_response_json(
                specs=[_make_spec(semantic="boiler warranty letter")]
            ),
        )
        outcome = planner.plan("find my boiler warranty")

        assert isinstance(outcome, RetrievalPlan)

    def test_gate_off_ignores_clarify_json(self) -> None:
        """When SEARCH_GATE_ADEQUACY=False a clarify JSON produces a RetrievalPlan.

        _clarify_json emits specs=[] so the gate is bypassed (the clarify object
        is not extracted) and the parser falls through to the plan path. With
        the gate off the pipeline must proceed rather than ask the user to
        clarify — and an empty specs list is substituted with the broad-semantic
        fallback spec so the "a plan always has >=1 spec" invariant holds.
        """
        planner = build_planner(
            make_search_settings(SEARCH_GATE_ADEQUACY=False),
            _clarify_json("Too vague."),
        )
        outcome = planner.plan("life")

        assert isinstance(outcome, RetrievalPlan)
        # Gate is off: the clarify object is ignored. specs=[] is back-filled
        # with the broad-semantic fallback so the plan is never spec-less.
        assert outcome.clarify is None
        assert len(outcome.specs) == 1
        assert outcome.specs[0].semantic == "life"

    def test_malformed_json_never_returns_clarify_needed(self) -> None:
        """A garbled LLM response degrades to a RetrievalPlan, never ClarifyNeeded."""
        planner = build_planner(
            make_search_settings(SEARCH_GATE_ADEQUACY=True),
            "this is not valid json at all",
        )
        outcome = planner.plan("life")

        assert isinstance(outcome, RetrievalPlan)

    def test_empty_response_never_returns_clarify_needed(self) -> None:
        """An empty LLM response → RetrievalPlan fallback, not ClarifyNeeded."""
        planner = build_planner(
            make_search_settings(SEARCH_GATE_ADEQUACY=True),
            "",
        )
        outcome = planner.plan("life")

        assert isinstance(outcome, RetrievalPlan)

    def test_clarify_with_empty_reason_falls_back_to_plan(self) -> None:
        """An empty clarify.reason is not a valid clarify — degrade to a plan."""
        payload = _json.dumps({"specs": [], "clarify": {"reason": ""}})
        planner = build_planner(
            make_search_settings(SEARCH_GATE_ADEQUACY=True),
            payload,
        )
        outcome = planner.plan("life")

        assert isinstance(outcome, RetrievalPlan)

    def test_clarify_with_missing_reason_field_falls_back_to_plan(self) -> None:
        """A clarify object missing the reason key falls back to a RetrievalPlan."""
        payload = _json.dumps({"specs": [], "clarify": {}})
        planner = build_planner(
            make_search_settings(SEARCH_GATE_ADEQUACY=True),
            payload,
        )
        outcome = planner.plan("life")

        assert isinstance(outcome, RetrievalPlan)

    def test_none_content_with_gate_on_produces_fallback_plan(self) -> None:
        """None LLM content → RetrievalPlan fallback even with the gate on."""
        planner = build_planner(
            make_search_settings(SEARCH_GATE_ADEQUACY=True),
            None,
        )
        outcome = planner.plan("life")

        assert isinstance(outcome, RetrievalPlan)


# ---------------------------------------------------------------------------
# Usage sink forwarding
# ---------------------------------------------------------------------------


class TestPlannerUsageSink:
    """planner.plan forwards a usage_sink into the shared completion helper."""

    def test_plan_forwards_usage_sink_into_completion_helper(self) -> None:
        """The passed sink is forwarded verbatim to _complete_with_model_fallback."""
        planner = build_planner(make_search_settings(), planner_response_json())
        seen: dict[str, object] = {}

        def _spy(**kwargs: object) -> str:
            seen.update(kwargs)
            return planner_response_json()

        planner._complete_with_model_fallback = _spy  # type: ignore[method-assign]
        sink: list = []
        planner.plan("a query", usage_sink=sink)
        assert seen.get("usage_sink") is sink

    def test_plan_populates_the_sink_end_to_end(self) -> None:
        """A real (mocked) call records one LlmCallUsage into the sink (zeros, as
        make_chat_completion pins usage=None)."""
        from common.llm import LlmCallUsage

        planner = build_planner(make_search_settings(), planner_response_json())
        sink: list[LlmCallUsage] = []
        planner.plan("a query", usage_sink=sink)
        assert len(sink) == 1
        assert sink[0] == LlmCallUsage(
            model="gpt-5.4-mini",
            provider="openai",
            prompt=0,
            completion=0,
            reasoning=0,
            total=0,
        )

    def test_plan_without_sink_still_works(self) -> None:
        """Omitting usage_sink (the default) leaves behaviour unchanged."""
        planner = build_planner(make_search_settings(), planner_response_json())
        outcome = planner.plan("a query")
        assert isinstance(outcome, RetrievalPlan)


# ---------------------------------------------------------------------------
# Asker forwarding
# ---------------------------------------------------------------------------


class TestPlannerAsker:
    """planner.plan forwards the asker into the user-turn message."""

    def test_plan_forwards_asker_into_the_prompt(self) -> None:
        """When asker is set, the planner user message must contain the name."""
        captured: list[str] = []

        def _capture_and_respond(*, model, messages, **rest):
            for m in messages:
                if m.get("role") == "user":
                    captured.append(m["content"])
            from tests.helpers.llm import make_chat_completion, planner_response_json

            return make_chat_completion(planner_response_json())

        planner = build_planner(make_search_settings(), planner_response_json())
        planner._create_completion = _capture_and_respond  # type: ignore[method-assign]
        planner.plan("my passport", asker="Vilmar Rosset")
        assert any("Vilmar Rosset" in m for m in captured), (
            "Asker not found in the planner's user message."
        )
