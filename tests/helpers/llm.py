"""Shared LLM-mocking helpers for the search-pipeline tests.

The planner and synthesiser subclass ``OpenAIChatMixin``; their tests patch the
instance's ``_create_completion`` with a fake rather than injecting a client
(mirroring ``tests/unit/classifier``).  Several search test files need the same
three things — an OpenAI-shaped completion object, a driver that routes a
``_create_completion`` call to the planner or the next synthesiser response,
and the canned JSON payloads — so they live here once instead of being
re-hand-rolled per file (CODE_GUIDELINES §11.5).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import openai


def make_api_error(message: str = "server error") -> openai.APIError:
    """Return a bare ``openai.APIError`` — the base of the openai error tree.

    The planner and synthesiser are documented to catch the whole
    ``openai.APIError`` family; constructing one here is fixture-building for
    that contract, not a production OpenAI call.
    """
    return openai.APIError(message=message, request=MagicMock(), body=None)


def make_internal_server_error() -> openai.InternalServerError:
    """Return a retryable 5xx ``openai.InternalServerError`` for tests."""
    response = MagicMock()
    response.status_code = 500
    response.headers = {}
    return openai.InternalServerError(message="boom", response=response, body=None)


def make_authentication_error() -> openai.AuthenticationError:
    """Return a non-retryable 401 ``openai.AuthenticationError`` for tests.

    Models a wrong or expired ``OPENAI_API_KEY``.
    """
    response = MagicMock()
    response.status_code = 401
    response.headers = {}
    return openai.AuthenticationError(
        message="Incorrect API key provided", response=response, body=None
    )


def make_chat_completion(content: str | None) -> MagicMock:
    """Wrap a raw content string in an OpenAI-shaped chat-completion object.

    The shape ``OpenAIChatMixin._create_completion`` returns:
    ``completion.choices[0].message.content``.

    ``usage`` is pinned to ``None`` so the ``usage_sink`` capture path in
    ``_complete_with_model_fallback`` records honest zeros (the Ollama/older-
    provider case) rather than reading a truthy auto-``MagicMock`` for every
    token field — which would poison the telemetry's token sums and pricing
    arithmetic with mock objects. A test that needs real token counts sets
    ``completion.usage`` itself (see ``tests/unit/common/test_llm_usage_sink``).

    Args:
        content: The assistant message content, or ``None`` to model an empty
            completion.
    """
    choice = MagicMock()
    choice.message.content = content
    completion = MagicMock()
    completion.choices = [choice]
    completion.usage = None
    return completion


def _make_spec(
    *,
    mode: str = "semantic",
    semantic: str | None = "boiler warranty",
    keywords: list[str] | None = None,
    correspondent: str | None = None,
    document_type: str | None = None,
    tags: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    rationale: str = "test spec",
) -> dict[str, object]:
    """Build a single spec dict in the new planner JSON shape.

    Convenience helper so tests can construct individual specs with sensible
    defaults and pass them to :func:`planner_response_json`.

    Args:
        mode: ``"semantic"`` (default) or ``"keyword"``.
        semantic: Text to embed; null for keyword specs.
        keywords: Verbatim FTS terms; empty for semantic specs.
        correspondent: Free-text correspondent guess, or None.
        document_type: Free-text document-type guess, or None.
        tags: Tag label guesses.
        date_from: ISO date lower bound, or None.
        date_to: ISO date upper bound, or None.
        rationale: One-line explanation for this spec.
    """
    return {
        "mode": mode,
        "semantic": semantic,
        "keywords": keywords or [],
        "filter_guess": {
            "correspondent": correspondent,
            "document_type": document_type,
            "tags": tags or [],
            "date_from": date_from,
            "date_to": date_to,
        },
        "rationale": rationale,
    }


def planner_response_json(
    specs: list[dict[str, object]] | None = None,
    clarify_reason: str | None = None,
) -> str:
    """Return a well-formed planner JSON response string (multi-spec shape).

    When *specs* is None a single default semantic spec is used.  Pass
    ``specs=[]`` (with a *clarify_reason*) to model a clarify-only response.
    Each spec dict is typically built via :func:`_make_spec`.

    Args:
        specs: List of spec dicts in the new planner schema shape.  Defaults to
            one broad semantic spec so existing call-sites that pass no args keep
            working.
        clarify_reason: When set, ``clarify`` is ``{"reason": clarify_reason}``;
            otherwise ``clarify`` is null.
    """
    if specs is None:
        specs = [_make_spec()]
    clarify: dict[str, str] | None = (
        {"reason": clarify_reason} if clarify_reason is not None else None
    )
    return json.dumps({"specs": specs, "clarify": clarify})


def answered_response_json(answer: str, citations: list[int]) -> str:
    """Return a well-formed ``Answered`` synthesiser JSON response."""
    return json.dumps({"outcome": "answered", "answer": answer, "citations": citations})


def needs_more_response_json(adjustment: str) -> str:
    """Return a well-formed ``NeedsMore`` synthesiser JSON response."""
    return json.dumps({"outcome": "needs_more", "adjustment": adjustment})


def judge_response_json(
    relevant_document_ids: list[int] | None = None,
    dropped_document_ids: list[int] | None = None,
    *,
    verdicts: list[dict[str, object]] | None = None,
    kept_score: float = 0.9,
    dropped_score: float = 0.1,
) -> str:
    """Return a well-formed relevance-judge JSON response (per-document verdicts).

    Two shapes, kept backward-friendly:

    * **Explicit verdicts.** Pass ``verdicts=[{"document_id": .., "keep": ..,
      "reason": .., "score": ..}]`` for per-document control of every field.
      Each dict is emitted verbatim, so a test can omit ``score`` to exercise
      the judge's missing-score default.
    * **Id lists (the default).** Each id in *relevant_document_ids* produces a
      ``keep: true`` verdict scored *kept_score* (default ``0.9`` — above the
      default keep threshold). Each id in *dropped_document_ids* produces an
      explicit ``keep: false`` verdict scored *dropped_score* (default ``0.1``).
      Callers needing explicit drops (so the judge does not default-keep omitted
      ids) pass both lists.
    """
    if verdicts is not None:
        return json.dumps({"verdicts": verdicts})
    built = [
        {"document_id": doc_id, "keep": True, "reason": "", "score": kept_score}
        for doc_id in (relevant_document_ids or [])
    ]
    if dropped_document_ids:
        built += [
            {
                "document_id": doc_id,
                "keep": False,
                "reason": "not relevant",
                "score": dropped_score,
            }
            for doc_id in dropped_document_ids
        ]
    return json.dumps({"verdicts": built})


class ScriptedLLMClient:
    """A scripted driver for ``_create_completion`` across both LLM stages.

    The planner and the synthesiser call ``_create_completion`` with distinct
    system prompts.  :meth:`route` inspects the system message to route each
    call to the planner response or the next synthesiser response, and records
    per-stage call counts so a test can assert the exact LLM-call budget.

    Install :meth:`route` as each stage's ``_create_completion`` — the planner
    and the synthesiser then share one driver, and the test asserts how many
    calls of each kind were made.

    Args:
        planner_response: Raw JSON string the *initial* planner call returns.
        synthesiser_responses: Ordered raw JSON strings; the *n*-th synthesiser
            call returns the *n*-th entry.  When exhausted the last entry is
            reused, so an over-eager loop stays observable rather than crashing.
        judge_response: Raw JSON string the judge call returns (or None when no
            judge call is scripted).
        replan_response: Raw JSON string the planner's *re-plan* call returns.
            A re-plan call shares the planner system prompt; it is distinguished
            by the ``"This is a RE-PLAN."`` marker its user message carries.
            When None (the default) a re-plan reuses *planner_response*, so the
            re-plan resolves to the same specs as pass 1 — the no-op path.
    """

    def __init__(
        self,
        planner_response: str,
        synthesiser_responses: list[str],
        judge_response: str | None = None,
        replan_response: str | None = None,
    ) -> None:
        self._planner_response = planner_response
        self._synthesiser_responses = synthesiser_responses
        self._judge_response = judge_response
        self._replan_response = replan_response
        self.planner_calls = 0
        self.replan_calls = 0
        self.synthesiser_calls = 0
        self.judge_calls = 0

    @property
    def total_calls(self) -> int:
        """Total LLM chat calls — planner + re-plan + judge + synthesiser."""
        return (
            self.planner_calls
            + self.replan_calls
            + self.judge_calls
            + self.synthesiser_calls
        )

    def route(self, *, model: str, messages: list[dict[str, str]], **_: Any) -> Any:
        """Stand-in for ``OpenAIChatMixin._create_completion``.

        Accepts the same ``model=`` / ``messages=`` keyword arguments the mixin
        passes through, routes by the system prompt, and returns an
        OpenAI-shaped completion.
        """
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "search-query planning engine" in system:
            user = next((m["content"] for m in messages if m["role"] == "user"), "")
            if "This is a RE-PLAN." in user:
                self.replan_calls += 1
                return make_chat_completion(
                    self._replan_response
                    if self._replan_response is not None
                    else self._planner_response
                )
            self.planner_calls += 1
            return make_chat_completion(self._planner_response)

        if "document-relevance judge" in system:
            self.judge_calls += 1
            if self._judge_response is None:
                raise AssertionError(
                    "judge call made but no judge_response was scripted"
                )
            return make_chat_completion(self._judge_response)

        # Anything else is a synthesiser call.
        self.synthesiser_calls += 1
        index = min(self.synthesiser_calls - 1, len(self._synthesiser_responses) - 1)
        return make_chat_completion(self._synthesiser_responses[index])
