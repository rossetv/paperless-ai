"""Exceptions raised by the search pipeline."""

from __future__ import annotations


class SearchError(Exception):
    """Base for search-pipeline failures.

    The HTTP API and the MCP server catch this to turn a pipeline failure into a
    structured response.
    """


class AppStateNotAttachedError(SearchError):
    """A request reached a handler before ``attach_app_state`` ran.

    Raised by :func:`search.appstate.get_app_state` instead of letting a
    confusing ``AttributeError`` surface deep in a handler.
    """


class RowVanishedError(SearchError):
    """A row confirmed to exist came back ``None`` from its own ``UPDATE``.

    The row vanished mid-transaction, a data-integrity fault. This is an
    exception rather than an ``assert`` because ``python -O`` strips asserts.
    """


class LlmBudgetExceededError(SearchError):
    """The pipeline attempted more LLM chat calls than the per-query budget.

    The budget is ``(2 + j) * (1 + SEARCH_MAX_REFINEMENTS)``, where ``j`` is 1
    when ``SEARCH_GATE_JUDGE`` is on (see :func:`search.core._max_llm_calls`).
    ``SearchCore``'s loop cannot breach it; this is a guard so a regression that
    adds a call fails loudly instead of silently billing the operator.
    """
