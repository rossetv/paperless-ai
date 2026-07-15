"""Domain exception hierarchy for the search pipeline.

The search subsystem owns its exceptions here, in the package that raises them
(``CODE_GUIDELINES.md`` §6.1).  A bare ``RuntimeError`` from production search
code is a bug — the caller cannot meaningfully react to it; a typed
``SearchError`` subclass is a designed signal between the stage that detects a
failure and the interface (the HTTP API, the MCP server) that turns it into a
response.

Depends on: nothing (standard library only).
"""

from __future__ import annotations


class SearchError(Exception):
    """Base exception for all search-pipeline failures.

    The search interfaces (``search/api.py``, ``search/mcp_server.py``) catch
    this type to turn a pipeline failure into a structured response.  Specific
    failure modes are subclasses with a docstring naming the failure.
    """


class AppStateNotAttachedError(SearchError):
    """The request reached a handler before the account wiring was attached.

    :func:`search.appstate.get_app_state` raises this when no
    :class:`~search.appstate.AppState` is on ``app.state`` — the app was built
    without :func:`~search.appstate.attach_app_state`. It is a programmer
    error surfaced loudly (``CODE_GUIDELINES.md`` §1.11) rather than a generic
    ``RuntimeError`` (§6.1) or a confusing ``AttributeError`` deep in a
    handler.
    """


class RowVanishedError(SearchError):
    """A row confirmed to exist returned ``None`` from its own write.

    Raised after an ``UPDATE`` whose target was checked to exist on the same
    connection moments before: the write's re-read should always return the
    row, so a ``None`` means the row vanished mid-transaction — a data-integrity
    fault that must fail loud (``CODE_GUIDELINES.md`` §1.11). It replaces a bare
    ``assert`` (§17.2), which ``python -O`` strips, turning the fault into a
    later ``AttributeError`` far from its cause.
    """


class LlmBudgetExceededError(SearchError):
    """The pipeline attempted more LLM chat calls than the per-query budget allows.

    The per-query budget is ``(2 + j) * (1 + SEARCH_MAX_REFINEMENTS)`` (spec
    §6.3, ``CODE_GUIDELINES.md`` §14.3), where ``j`` is 1 when
    ``SEARCH_GATE_JUDGE`` is on: one planner call, one optional judge call,
    and one synthesise per pass — the base pass plus each refinement pass
    (see :func:`search.core._max_llm_calls`).  ``SearchCore``'s own loop
    logic cannot breach that bound; this error is the defensive guard
    (``CODE_GUIDELINES.md`` §1.11) — it is raised only if a future regression
    introduces an extra call, so the cost overrun fails loud rather than
    silently billing the operator.
    """
