"""Tests for ``QueryPlanner.replan`` — the hint-driven re-plan (Phase 2).

The re-plan reuses the byte-stable planner system prompt and the same parse
path as ``plan()``, but builds a richer USER message that carries the
synthesiser's gap hint, a rendering of the specs already tried, and the titles
already found.  These tests assert:

- the user message sent to the planner contains the hint, a rendering of the
  prior specs, and the prior findings;
- a scripted re-plan response is parsed into a ``RetrievalPlan`` with the new
  specs;
- a degraded (all-models-failed) re-plan degrades to the safe fallback plan.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from search.models import (
    ClarifyNeeded,
    RetrievalPlan,
    RetrievalSpec,
)
from search.planner import QueryPlanner
from store.models import SearchFilters
from tests.helpers.factories import make_search_settings
from tests.helpers.llm import (
    _make_spec,
    make_chat_completion,
    planner_response_json,
)


def _prior_spec(
    *,
    mode: str = "semantic",
    semantic: str | None = "boiler warranty",
    keywords: tuple[str, ...] = (),
    correspondent_id: int | None = None,
    document_type_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> RetrievalSpec:
    """Build a resolved RetrievalSpec for the prior-specs argument."""
    return RetrievalSpec(
        mode=mode,  # type: ignore[arg-type]
        semantic=semantic,
        keywords=keywords,
        filters=SearchFilters(
            date_from=date_from,
            date_to=date_to,
            correspondent_id=correspondent_id,
            document_type_id=document_type_id,
            tag_ids=(),
        ),
        rationale="prior spec",
    )


class _CapturingClient:
    """Captures the messages of the single planner call and returns *response*."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.captured_messages: list[dict[str, str]] = []
        self.calls = 0

    def route(self, *, model: str, messages: list[dict[str, str]], **_: Any) -> Any:
        self.calls += 1
        self.captured_messages = messages
        return make_chat_completion(self._response)


def _build_replanner(settings: MagicMock, client: _CapturingClient) -> QueryPlanner:
    planner = QueryPlanner(settings)
    planner._create_completion = client.route  # type: ignore[method-assign]
    return planner


class TestReplanUserMessage:
    """The re-plan user message carries the hint, the prior specs, and findings."""

    def test_message_contains_hint_prior_specs_and_findings(self) -> None:
        client = _CapturingClient(planner_response_json())
        planner = _build_replanner(make_search_settings(), client)

        planner.replan(
            "what boiler do I have?",
            hint="need the April 2025 payslip",
            prior_specs=(
                _prior_spec(semantic="boiler details"),
                _prior_spec(mode="keyword", semantic=None, keywords=("Worcester",)),
            ),
            prior_findings=("Boiler Manual", "Heating Guide"),
        )

        user = next(
            m["content"] for m in client.captured_messages if m["role"] == "user"
        )
        # The gap hint must be in the message.
        assert "need the April 2025 payslip" in user
        # The prior specs must be rendered (their query text appears).
        assert "boiler details" in user
        assert "Worcester" in user
        # The prior findings (titles) must appear.
        assert "Boiler Manual" in user
        assert "Heating Guide" in user

    def test_reuses_byte_stable_system_prompt(self) -> None:
        client = _CapturingClient(planner_response_json())
        planner = _build_replanner(make_search_settings(), client)

        planner.replan(
            "q",
            hint="h",
            prior_specs=(_prior_spec(),),
            prior_findings=(),
        )

        system = next(
            m["content"] for m in client.captured_messages if m["role"] == "system"
        )
        assert system.startswith("You are a search-query planning engine.")

    def test_no_findings_renders_none(self) -> None:
        client = _CapturingClient(planner_response_json())
        planner = _build_replanner(make_search_settings(), client)

        planner.replan(
            "q",
            hint="h",
            prior_specs=(_prior_spec(),),
            prior_findings=(),
        )

        user = next(
            m["content"] for m in client.captured_messages if m["role"] == "user"
        )
        assert "none" in user.lower()


class TestReplanParsing:
    """A scripted re-plan response is parsed into a RetrievalPlan."""

    def test_scripted_response_becomes_retrieval_plan(self) -> None:
        payload = planner_response_json(
            specs=[
                _make_spec(
                    mode="semantic",
                    semantic="april 2025 payslip",
                    date_from="2025-04-01",
                    date_to="2025-04-30",
                    rationale="date-scoped re-plan",
                )
            ]
        )
        client = _CapturingClient(payload)
        planner = _build_replanner(make_search_settings(), client)

        plan = planner.replan(
            "salary in april",
            hint="need the April 2025 payslip",
            prior_specs=(_prior_spec(),),
            prior_findings=(),
        )

        assert isinstance(plan, RetrievalPlan)
        assert len(plan.specs) == 1
        assert plan.specs[0].semantic == "april 2025 payslip"
        assert plan.specs[0].filter_guess.date_from == "2025-04-01"

    def test_clarify_response_returns_clarify_needed(self) -> None:
        import json

        payload = json.dumps({"specs": [], "clarify": {"reason": "too vague"}})
        client = _CapturingClient(payload)
        planner = _build_replanner(
            make_search_settings(SEARCH_GATE_ADEQUACY=True), client
        )

        outcome = planner.replan(
            "q",
            hint="h",
            prior_specs=(_prior_spec(),),
            prior_findings=(),
        )

        assert isinstance(outcome, ClarifyNeeded)
        assert outcome.reason == "too vague"


class TestReplanDegraded:
    """Every model failing degrades the re-plan to the safe fallback plan."""

    def test_all_models_fail_returns_fallback_plan(self) -> None:
        import openai

        planner = QueryPlanner(make_search_settings())
        planner._create_completion = MagicMock(  # type: ignore[method-assign]
            side_effect=openai.APIError(message="boom", request=MagicMock(), body=None)
        )

        plan = planner.replan(
            "salary in april",
            hint="need the April 2025 payslip",
            prior_specs=(_prior_spec(),),
            prior_findings=(),
        )

        assert isinstance(plan, RetrievalPlan)
        assert len(plan.specs) == 1
        spec = plan.specs[0]
        assert spec.mode == "semantic"
        assert spec.semantic == "salary in april"
        assert "fallback" in spec.rationale
