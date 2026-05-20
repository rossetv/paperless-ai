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
    return openai.InternalServerError(
        message="boom", response=response, body=None
    )


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

    Args:
        content: The assistant message content, or ``None`` to model an empty
            completion.
    """
    choice = MagicMock()
    choice.message.content = content
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def planner_response_json(
    *,
    semantic_queries: list[str] | None = None,
    keyword_terms: list[str] | None = None,
    correspondent: str | None = None,
    document_type: str | None = None,
    tags: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sub_questions: list[str] | None = None,
) -> str:
    """Return a well-formed planner JSON response string.

    Every argument defaults to an empty / null value, so a test spells out only
    the part of the plan it cares about.
    """
    return json.dumps(
        {
            "semantic_queries": semantic_queries or ["boiler warranty"],
            "keyword_terms": keyword_terms or [],
            "filter_candidates": {
                "correspondent": correspondent,
                "document_type": document_type,
                "tags": tags or [],
                "date_from": date_from,
                "date_to": date_to,
            },
            "sub_questions": sub_questions or [],
        }
    )


def answered_response_json(answer: str, citations: list[int]) -> str:
    """Return a well-formed ``Answered`` synthesiser JSON response."""
    return json.dumps(
        {"outcome": "answered", "answer": answer, "citations": citations}
    )


def needs_more_response_json(adjustment: str) -> str:
    """Return a well-formed ``NeedsMore`` synthesiser JSON response."""
    return json.dumps({"outcome": "needs_more", "adjustment": adjustment})


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
        planner_response: Raw JSON string the planner call returns.
        synthesiser_responses: Ordered raw JSON strings; the *n*-th synthesiser
            call returns the *n*-th entry.  When exhausted the last entry is
            reused, so an over-eager loop stays observable rather than crashing.
    """

    def __init__(
        self,
        planner_response: str,
        synthesiser_responses: list[str],
    ) -> None:
        self._planner_response = planner_response
        self._synthesiser_responses = synthesiser_responses
        self.planner_calls = 0
        self.synthesiser_calls = 0

    @property
    def total_calls(self) -> int:
        """Total LLM chat calls made — planner plus synthesiser."""
        return self.planner_calls + self.synthesiser_calls

    def route(
        self, *, model: str, messages: list[dict[str, str]], **_: Any
    ) -> Any:
        """Stand-in for ``OpenAIChatMixin._create_completion``.

        Accepts the same ``model=`` / ``messages=`` keyword arguments the mixin
        passes through, routes by the system prompt, and returns an
        OpenAI-shaped completion.
        """
        system = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        if "search-query planning engine" in system:
            self.planner_calls += 1
            return make_chat_completion(self._planner_response)

        # Anything else is a synthesiser call.
        self.synthesiser_calls += 1
        index = min(
            self.synthesiser_calls - 1, len(self._synthesiser_responses) - 1
        )
        return make_chat_completion(self._synthesiser_responses[index])
