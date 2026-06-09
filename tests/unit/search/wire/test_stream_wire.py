"""Tests for the NDJSON line builders in ``search.wire.stream`` (spec §Streaming).

Each builder must emit one valid JSON object terminated by a single newline:
``phase_start`` / ``phase_done`` for the two phase-event kinds, ``result`` for
the final response, and ``error`` for a terminal failure. Token/cost serialise
to nested dicts on an LLM phase and to ``null`` on a non-LLM phase.
"""

from __future__ import annotations

import json

from search.models import Cost, PhaseRecord, TokenUsage
from search.trace import PhaseStart
from search.wire.search import to_search_response
from search.wire.stream import error_line, event_line, result_line
from tests.helpers.factories import make_search_result


def test_phase_start_line() -> None:
    """A PhaseStart serialises to a phase_start frame and ends with a newline."""
    line = event_line(PhaseStart("plan", "Planning the query"), seq=1)
    assert line.endswith("\n")
    obj = json.loads(line)
    assert obj == {
        "type": "phase_start",
        "seq": 1,
        "phase": "plan",
        "label": "Planning the query",
    }


def test_phase_done_line_serialises_tokens_and_cost() -> None:
    """A PhaseRecord with usage serialises tokens + cost as nested dicts."""
    rec = PhaseRecord(
        phase="judge",
        label="Judging relevance",
        detail={"kept": 2},
        tokens=TokenUsage(prompt=1, completion=2, reasoning=0, total=3),
        cost=Cost(usd=0.01, local=False),
        ms=50,
    )
    obj = json.loads(event_line(rec, seq=4))
    assert obj["type"] == "phase_done"
    assert obj["seq"] == 4
    assert obj["phase"] == "judge"
    assert obj["label"] == "Judging relevance"
    assert obj["detail"] == {"kept": 2}
    assert obj["tokens"] == {
        "prompt": 1,
        "completion": 2,
        "reasoning": 0,
        "total": 3,
    }
    assert obj["cost"] == {"usd": 0.01, "local": False}
    assert obj["ms"] == 50


def test_phase_done_line_null_tokens_and_cost_for_non_llm_phase() -> None:
    """A non-LLM phase (no tokens/cost) serialises both as JSON null."""
    rec = PhaseRecord(
        phase="retrieve",
        label="Retrieving documents",
        detail={"chunk_count": 3},
        tokens=None,
        cost=None,
        ms=7,
    )
    obj = json.loads(event_line(rec, seq=2))
    assert obj["tokens"] is None
    assert obj["cost"] is None
    assert obj["detail"] == {"chunk_count": 3}


def test_result_line_nests_the_full_response() -> None:
    """The result frame nests the dumped SearchResponse under 'result'."""
    resp = to_search_response(make_search_result(answer="hello"))
    obj = json.loads(result_line(resp, seq=9))
    assert obj["type"] == "result"
    assert obj["seq"] == 9
    assert obj["result"]["answer"] == "hello"
    # The trace/cost added in Task 12 ride inside the nested result.
    assert "trace" in obj["result"]
    assert "cost" in obj["result"]


def test_error_line() -> None:
    """The error frame carries the kind and message verbatim."""
    line = error_line("budget", "limit breached", seq=9)
    assert line.endswith("\n")
    obj = json.loads(line)
    assert obj == {
        "type": "error",
        "seq": 9,
        "kind": "budget",
        "message": "limit breached",
    }
