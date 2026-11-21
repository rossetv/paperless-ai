"""NDJSON line builders for ``POST /api/search/stream``.

A stream is a ``phase_start`` and a ``phase_done`` per phase, then a terminal
``result`` or ``error``. Each line ends in exactly one newline; ``seq`` is a
per-stream counter the client uses to order and de-duplicate frames.
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
    """Serialise a phase start or done record to a ``phase_*`` NDJSON line."""
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

    The body has the same shape ``POST /api/search`` returns.
    """
    payload = {"type": "result", "seq": seq, "result": resp.model_dump()}
    return json.dumps(payload) + "\n"


def error_line(kind: str, message: str, seq: int) -> str:
    """Serialise a terminal error to an ``error`` NDJSON line.

    Once the body has begun, a failure can no longer be an HTTP status.
    ``kind`` is a category such as ``"budget"``; ``message`` is safe to show.
    """
    payload = {"type": "error", "seq": seq, "kind": kind, "message": message}
    return json.dumps(payload) + "\n"
