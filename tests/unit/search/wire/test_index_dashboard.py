"""Tests for the Index API wire models in search.wire.

Covers: each Index model carries its fields; IndexStatusResponse wraps a list
of daemon tiles; ReconcileCycleResponse's summary is a string-to-int map;
FailedDocumentResponse accepts a null title; RebuildResponse carries the
accepted flag and detail.
"""

from __future__ import annotations

from search.wire import (
    DaemonStatusResponse,
    FailedDocumentResponse,
    IndexActivityResponse,
    IndexFailedResponse,
    IndexStatusResponse,
    RebuildResponse,
    ReconcileCycleResponse,
)


def test_daemon_status_response_carries_its_fields() -> None:
    tile = DaemonStatusResponse(
        name="ocr",
        state="running",
        detail="processing 2 documents",
        processed_count=14,
        last_heartbeat="2026-05-22T12:00:00+00:00",
    )
    assert tile.name == "ocr"
    assert tile.state == "running"
    assert tile.processed_count == 14


def test_index_status_response_wraps_health_and_tiles() -> None:
    response = IndexStatusResponse(
        health="degraded",
        daemons=[
            DaemonStatusResponse(
                name="ocr",
                state="stopped",
                detail="no heartbeat recorded",
                processed_count=0,
                last_heartbeat="1970-01-01T00:00:00+00:00",
            )
        ],
    )
    assert response.health == "degraded"
    assert len(response.daemons) == 1


def test_reconcile_cycle_response_summary_is_a_count_map() -> None:
    cycle = ReconcileCycleResponse(
        id=3,
        kind="sync",
        started_at="2026-05-22T12:00:00+00:00",
        finished_at="2026-05-22T12:00:05+00:00",
        ok=True,
        summary={"indexed": 4, "failed": 0},
        detail="indexed 4 documents",
    )
    assert cycle.summary["indexed"] == 4
    assert cycle.ok is True


def test_index_activity_response_wraps_a_list() -> None:
    response = IndexActivityResponse(
        cycles=[
            ReconcileCycleResponse(
                id=1,
                kind="sweep",
                started_at="2026-05-22T12:00:00+00:00",
                finished_at="2026-05-22T12:00:01+00:00",
                ok=True,
                summary={"pruned": 0},
                detail="pruned 0 deleted documents",
            )
        ]
    )
    assert len(response.cycles) == 1


def test_failed_document_response_accepts_a_null_title() -> None:
    doc = FailedDocumentResponse(document_id=42, title=None, failure_count=3)
    assert doc.document_id == 42
    assert doc.title is None


def test_index_failed_response_wraps_a_list() -> None:
    response = IndexFailedResponse(
        documents=[
            FailedDocumentResponse(document_id=7, title="Invoice", failure_count=2)
        ]
    )
    assert response.documents[0].title == "Invoice"


def test_rebuild_response_carries_accepted_and_detail() -> None:
    response = RebuildResponse(
        accepted=True, detail="Index rebuild has been triggered."
    )
    assert response.accepted is True
    assert "rebuild" in response.detail.lower()
