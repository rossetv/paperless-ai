"""Wire models for the Index dashboard endpoints under ``/api/index``."""

from __future__ import annotations

from pydantic import BaseModel


class DaemonStatusResponse(BaseModel):
    """One daemon's tile in the Index dashboard.

    Attributes:
        name: ``ocr``, ``classifier``, ``indexer`` or ``search``.
        state: ``running``, ``idle`` or ``stopped``.
        processed_count: A monotonic throughput counter.
        last_heartbeat: ISO-8601 UTC; a long-past value for a daemon that
            never ran.
    """

    name: str
    state: str
    detail: str
    processed_count: int
    last_heartbeat: str


class IndexStatusResponse(BaseModel):
    """Body of ``GET /api/index/status``.

    ``health`` is ``ok``, ``degraded`` or ``down``; ``daemons`` always has one
    entry per known daemon.
    """

    health: str
    daemons: list[DaemonStatusResponse]


class ReconcileCycleResponse(BaseModel):
    """One reconcile/sweep cycle in the Index dashboard's activity list.

    Attributes:
        id: Also the cycles' chronological order.
        kind: ``sync`` or ``sweep``.
        ok: Whether the cycle completed without aborting or erroring.
        summary: The SyncReport/SweepReport counts.
    """

    id: int
    kind: str
    started_at: str
    finished_at: str
    ok: bool
    summary: dict[str, int]
    detail: str


class IndexActivityResponse(BaseModel):
    """Body of ``GET /api/index/activity``: recent reconcile cycles."""

    cycles: list[ReconcileCycleResponse]


class FailedDocumentResponse(BaseModel):
    """One document the indexer has failed to index.

    ``title`` is ``None`` when the document has no indexed row;
    ``failure_count`` counts consecutive failed cycles.
    """

    document_id: int
    title: str | None
    failure_count: int


class IndexFailedResponse(BaseModel):
    """Body of ``GET /api/index/failed``."""

    documents: list[FailedDocumentResponse]


class RebuildResponse(BaseModel):
    """Body of ``POST /api/index/rebuild``."""

    accepted: bool
    detail: str
