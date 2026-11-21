"""LLM-mocking helpers for the search-pipeline tests.

The LLM stages are tested by patching each instance's ``_create_completion``
with :meth:`ScriptedLLMClient.route`, which returns canned JSON payloads.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import openai


def make_api_error(message: str = "server error") -> openai.APIError:
    """Return a bare ``openai.APIError``, the base of the openai error tree."""
    return openai.APIError(message=message, request=MagicMock(), body=None)


def make_internal_server_error() -> openai.InternalServerError:
    """Return a retryable 5xx ``openai.InternalServerError`` for tests."""
    response = MagicMock()
    response.status_code = 500
    response.headers = {}
    return openai.InternalServerError(message="boom", response=response, body=None)


def make_authentication_error() -> openai.AuthenticationError:
    """Return a non-retryable 401 ``openai.AuthenticationError`` (a bad API key)."""
    response = MagicMock()
    response.status_code = 401
    response.headers = {}
    return openai.AuthenticationError(
        message="Incorrect API key provided", response=response, body=None
    )


def make_chat_completion(content: str | None) -> MagicMock:
    """Wrap *content* in an OpenAI-shaped chat-completion object.

    ``usage`` is ``None`` so token telemetry records zeros instead of summing
    auto-created MagicMocks; a test that needs token counts sets it itself.
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
    """Build one planner spec dict for :func:`planner_response_json`."""
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
    """Return a well-formed planner JSON response string.

    *specs* defaults to one broad semantic spec. Pass ``specs=[]`` with a
    *clarify_reason* to model a clarify-only response.
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
    """Return a well-formed relevance-judge JSON response.

    Pass *verdicts* to emit verdict dicts verbatim (omit ``score`` to exercise
    the judge's missing-score default). Otherwise each id in
    *relevant_document_ids* becomes a kept verdict scored *kept_score* and each
    id in *dropped_document_ids* an explicit drop scored *dropped_score*.
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
    """A scripted ``_create_completion`` shared by every LLM stage.

    :meth:`route` tells the stages apart by their system prompt (a re-plan by
    the ``"This is a RE-PLAN."`` marker in its user message) and counts calls
    per stage so a test can assert the exact LLM-call budget.

    The *n*-th synthesiser call returns the *n*-th response; once they run out
    the last one is reused, so an over-eager loop shows up in the counts rather
    than crashing. A re-plan reuses *planner_response* unless *replan_response*
    is given.
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
        """Stand-in for ``OpenAIChatMixin._create_completion``."""
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
