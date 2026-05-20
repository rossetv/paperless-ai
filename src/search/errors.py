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


class LlmBudgetExceededError(SearchError):
    """The pipeline attempted more LLM chat calls than the hard ceiling allows.

    The agentic pipeline guarantees at most three LLM calls per query (spec
    §6.3, ``CODE_GUIDELINES.md`` §14.3): one planner call plus at most two
    synthesiser calls.  ``SearchCore``'s own loop logic cannot breach that
    bound; this error is the defensive guard (``CODE_GUIDELINES.md`` §1.11) —
    it is raised only if a future regression introduces a fourth call, so the
    cost overrun fails loud rather than silently billing the operator.
    """
