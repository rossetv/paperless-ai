"""Pydantic wire models for the Index dashboard API (web-redesign §5, Wave 6).

The response shapes for ``GET /api/index/status``, ``/api/index/activity``,
``/api/index/failed``, and ``POST /api/index/rebuild`` — daemon health tiles,
reconcile-cycle activity, the failed-document list, and the rebuild-trigger
outcome. A boundary module of the :mod:`search.wire` package
(``CODE_GUIDELINES.md`` §5.6).

Allowed deps: pydantic.
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

from pydantic import BaseModel


class DaemonStatusResponse(BaseModel):
    """One daemon's tile in the Index dashboard.

    Attributes:
        name: The daemon name — ocr / classifier / indexer / search.
        state: The derived state — running / idle / stopped.
        detail: A short human string describing what the daemon last did.
        processed_count: The daemon's monotonic throughput counter.
        last_heartbeat: ISO-8601 UTC timestamp of the daemon's last
            heartbeat — a long-past value for a daemon that never ran.
    """

    name: str
    state: str
    detail: str
    processed_count: int
    last_heartbeat: str


class IndexStatusResponse(BaseModel):
    """Body of ``GET /api/index/status`` — daemon health and per-daemon tiles.

    Attributes:
        health: The overall verdict — ok / degraded / down.
        daemons: One :class:`DaemonStatusResponse` per known daemon (always
            four).
    """

    health: str
    daemons: list[DaemonStatusResponse]


class ReconcileCycleResponse(BaseModel):
    """One reconcile/sweep cycle in the Index dashboard's activity list.

    Attributes:
        id: The cycle's id — also its chronological order.
        kind: ``sync`` or ``sweep``.
        started_at: ISO-8601 UTC timestamp the cycle began.
        finished_at: ISO-8601 UTC timestamp the cycle ended.
        ok: Whether the cycle completed without aborting or erroring.
        summary: The cycle's count map (the SyncReport/SweepReport fields).
        detail: A short human one-liner describing the outcome.
    """

    id: int
    kind: str
    started_at: str
    finished_at: str
    ok: bool
    summary: dict[str, int]
    detail: str


class IndexActivityResponse(BaseModel):
    """Body of ``GET /api/index/activity`` — recent reconcile cycles."""

    cycles: list[ReconcileCycleResponse]


class FailedDocumentResponse(BaseModel):
    """One document the indexer has failed to index.

    Attributes:
        document_id: The Paperless document id.
        title: The document's title, or ``None`` when it has no indexed row.
        failure_count: How many consecutive cycles it has failed.
    """

    document_id: int
    title: str | None
    failure_count: int


class IndexFailedResponse(BaseModel):
    """Body of ``GET /api/index/failed`` — the failed-document list."""

    documents: list[FailedDocumentResponse]


class RebuildResponse(BaseModel):
    """Body of ``POST /api/index/rebuild`` — the rebuild-trigger outcome.

    Attributes:
        accepted: Whether the rebuild request was accepted and triggered.
        detail: A human-readable note describing what happens next.
    """

    accepted: bool
    detail: str
