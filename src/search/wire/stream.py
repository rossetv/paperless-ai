"""Pure NDJSON line builders for the search stream (spec §Streaming).

The ``POST /api/search/stream`` endpoint sends the live search as a sequence of
newline-delimited JSON objects (NDJSON): one ``phase_start`` then one
``phase_done`` per executed phase, a terminal ``result`` carrying the full
:class:`~search.wire.search.SearchResponse`, or a terminal ``error``. This
module owns the *serialisation* of those frames — pure functions from a value
to one JSON line — so the route in :mod:`search.routes` is left with only the
queue-bridge plumbing.

Each builder returns the JSON object followed by exactly one ``"\\n"`` so the
client can split the byte stream on newlines. ``seq`` is a per-stream monotonic
counter the route assigns, letting the client order and de-duplicate frames.

Allowed deps: stdlib (json), search.models, search.trace, search.wire.search.
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

import json

from search.models import Cost, PhaseRecord, TokenUsage
from search.trace import PhaseEvent, PhaseStart
from search.wire.search import SearchResponse


def _tokens_dict(tokens: TokenUsage | None) -> dict[str, int] | None:
    """Serialise a phase's token usage, or ``None`` for a non-LLM phase."""
    if tokens is None:
        return None
    return {
        "prompt": tokens.prompt,
        "completion": tokens.completion,
        "reasoning": tokens.reasoning,
        "total": tokens.total,
    }


def _cost_dict(cost: Cost | None) -> dict[str, object] | None:
    """Serialise a phase's cost, or ``None`` for a non-LLM phase."""
    if cost is None:
        return None
    return {"usd": cost.usd, "local": cost.local}


def event_line(event: PhaseEvent, seq: int) -> str:
    """Serialise a phase event to one NDJSON line.

    Dispatches on the event type: a :class:`~search.trace.PhaseStart` becomes a
    ``phase_start`` frame (just the phase identity, emitted before the work
    runs); a :class:`~search.models.PhaseRecord` becomes a ``phase_done`` frame
    carrying the detail, token usage, cost, and elapsed milliseconds.

    Args:
        event: The phase event to serialise — a start marker or a done record.
        seq: The per-stream monotonic sequence number for this frame.

    Returns:
        A JSON object string terminated by a single newline.
    """
    if isinstance(event, PhaseStart):
        payload: dict[str, object] = {
            "type": "phase_start",
            "seq": seq,
            "phase": event.phase,
            "label": event.label,
        }
    else:
        record: PhaseRecord = event
        payload = {
            "type": "phase_done",
            "seq": seq,
            "phase": record.phase,
            "label": record.label,
            "detail": record.detail,
            "tokens": _tokens_dict(record.tokens),
            "cost": _cost_dict(record.cost),
            "ms": record.ms,
        }
    return json.dumps(payload) + "\n"


def result_line(resp: SearchResponse, seq: int) -> str:
    """Serialise the final :class:`SearchResponse` to a ``result`` NDJSON line.

    The full response body — the same shape ``POST /api/search`` returns — is
    nested under ``result`` so the client can hand it straight to the existing
    results renderer.

    Args:
        resp: The completed search response.
        seq: The per-stream monotonic sequence number for this frame.

    Returns:
        A JSON object string terminated by a single newline.
    """
    payload = {"type": "result", "seq": seq, "result": resp.model_dump()}
    return json.dumps(payload) + "\n"


def error_line(kind: str, message: str, seq: int) -> str:
    """Serialise a terminal error to an ``error`` NDJSON line.

    A streamed search cannot fail with an HTTP status once the body has begun,
    so a pipeline failure is surfaced as this frame instead. ``kind`` is a
    machine-readable category (e.g. ``"budget"``, ``"internal"``); ``message``
    is a short human-readable summary safe to show.

    Args:
        kind: The machine-readable error category.
        message: A short, client-safe description of the failure.
        seq: The per-stream monotonic sequence number for this frame.

    Returns:
        A JSON object string terminated by a single newline.
    """
    payload = {"type": "error", "seq": seq, "kind": kind, "message": message}
    return json.dumps(payload) + "\n"
