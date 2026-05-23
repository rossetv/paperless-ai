"""Integration tests for the Index dashboard API (web-redesign §5, Wave 6).

Drives the four /api/index/* endpoints through the real search FastAPI app
over a real tmp_path app.db, reusing the Wave 1 account helpers. Covers the
status payload (overall health + four daemon tiles), the activity payload,
the failed-documents payload, the rebuild sentinel write, and the RBAC gates
— Read-only can view, a non-admin cannot rebuild (403), an unauthenticated
caller is rejected (401).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from appdb import daemon_status, reconcile_activity
from tests.integration.accounts_helpers import (
    build_account_client,
    login,
    make_settings,
    open_app_db,
    seed_admin,
    seed_store,
    seed_user,
)


@pytest.fixture()
def index_env(tmp_path):
    """A search app over a real app.db, with both an admin and a Read-only
    user seeded. Yields (settings, app_db, store_reader) so a test can build
    whichever client it needs and inspect the database directly.
    """
    from store.reader import StoreReader

    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    seed_admin(app_db, username="admin", password="admin-password")
    seed_user(
        app_db,
        username="viewer",
        password="viewer-password",
        role="readonly",
    )
    store_reader = StoreReader(settings)
    try:
        yield settings, app_db, store_reader
    finally:
        store_reader.close()
        app_db.close()


def _admin_client(index_env):
    """A TestClient logged in as the seeded admin."""
    settings, app_db, store_reader = index_env
    client = build_account_client(settings, app_db, store_reader)
    assert login(client, username="admin", password="admin-password").status_code == 200
    return client


def _viewer_client(index_env):
    """A TestClient logged in as the seeded Read-only user."""
    settings, app_db, store_reader = index_env
    client = build_account_client(settings, app_db, store_reader)
    assert (
        login(client, username="viewer", password="viewer-password").status_code == 200
    )
    return client


# --- GET /api/index/status -------------------------------------------------


def test_status_returns_four_daemon_tiles(index_env) -> None:
    """Even with no heartbeats, the dashboard shows all four daemons."""
    client = _admin_client(index_env)
    response = client.get("/api/index/status")
    assert response.status_code == 200
    body = response.json()
    names = {d["name"] for d in body["daemons"]}
    assert names == {"ocr", "classifier", "indexer", "search"}


def test_status_reports_down_when_no_daemon_has_run(index_env) -> None:
    """No heartbeats at all → every daemon stopped → overall 'down'."""
    client = _admin_client(index_env)
    body = client.get("/api/index/status").json()
    assert body["health"] == "down"
    assert all(d["state"] == "stopped" for d in body["daemons"])


def test_status_reflects_a_recorded_heartbeat(index_env) -> None:
    """A fresh heartbeat shows the daemon running; the rest stay stopped."""
    _settings, app_db, _reader = index_env
    daemon_status.record_heartbeat(
        app_db, name="ocr", detail="processing 1 document", processed_count=4
    )
    client = _admin_client(index_env)
    body = client.get("/api/index/status").json()
    tiles = {d["name"]: d for d in body["daemons"]}
    assert tiles["ocr"]["state"] == "running"
    assert tiles["ocr"]["processed_count"] == 4
    assert tiles["indexer"]["state"] == "stopped"
    # One running, three stopped → degraded.
    assert body["health"] == "degraded"


# --- GET /api/index/activity ----------------------------------------------


def test_activity_is_empty_before_any_cycle(index_env) -> None:
    client = _admin_client(index_env)
    response = client.get("/api/index/activity")
    assert response.status_code == 200
    assert response.json()["cycles"] == []


def test_activity_returns_recorded_cycles_newest_first(index_env) -> None:
    _settings, app_db, _reader = index_env
    reconcile_activity.record_cycle(
        app_db,
        kind="sync",
        started_at="2026-05-22T12:00:00+00:00",
        finished_at="2026-05-22T12:00:05+00:00",
        ok=True,
        summary={"indexed": 2},
        detail="indexed 2 documents",
    )
    reconcile_activity.record_cycle(
        app_db,
        kind="sweep",
        started_at="2026-05-22T12:01:00+00:00",
        finished_at="2026-05-22T12:01:02+00:00",
        ok=True,
        summary={"pruned": 1},
        detail="pruned 1 deleted document",
    )
    client = _admin_client(index_env)
    cycles = client.get("/api/index/activity").json()["cycles"]
    assert [c["kind"] for c in cycles] == ["sweep", "sync"]
    assert cycles[0]["summary"] == {"pruned": 1}


# --- GET /api/index/failed -------------------------------------------------


def test_failed_is_empty_for_a_clean_index(index_env) -> None:
    client = _admin_client(index_env)
    response = client.get("/api/index/failed")
    assert response.status_code == 200
    assert response.json()["documents"] == []


# --- POST /api/index/rebuild ----------------------------------------------


def test_rebuild_writes_the_sentinel(index_env) -> None:
    """An admin's rebuild request writes the rebuild.request sentinel."""
    settings, _app_db, _reader = index_env
    client = _admin_client(index_env)
    response = client.post("/api/index/rebuild")
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    sentinel = Path(settings.INDEX_DB_PATH).parent / "rebuild.request"
    assert sentinel.exists()


# --- RBAC ------------------------------------------------------------------


def test_readonly_user_can_view_the_status(index_env) -> None:
    """A Read-only user may view operational state."""
    client = _viewer_client(index_env)
    assert client.get("/api/index/status").status_code == 200
    assert client.get("/api/index/activity").status_code == 200
    assert client.get("/api/index/failed").status_code == 200


def test_readonly_user_cannot_rebuild(index_env) -> None:
    """The destructive rebuild is admin-only — a Read-only user is 403."""
    settings, _app_db, _reader = index_env
    client = _viewer_client(index_env)
    response = client.post("/api/index/rebuild")
    assert response.status_code == 403
    # The 403 short-circuits before the handler — no sentinel was written.
    sentinel = Path(settings.INDEX_DB_PATH).parent / "rebuild.request"
    assert not sentinel.exists()


def test_member_user_cannot_rebuild(index_env) -> None:
    """A Member is also denied the rebuild — only admin may."""
    _settings, app_db, _reader = index_env
    seed_user(app_db, username="member", password="member-password", role="member")
    settings, _app_db, store_reader = index_env
    client = build_account_client(settings, app_db, store_reader)
    assert (
        login(client, username="member", password="member-password").status_code == 200
    )
    assert client.post("/api/index/rebuild").status_code == 403


def test_unauthenticated_caller_is_rejected(index_env) -> None:
    """No session, no key → 401 on every Index endpoint."""
    settings, app_db, store_reader = index_env
    client = build_account_client(settings, app_db, store_reader)
    assert client.get("/api/index/status").status_code == 401
    assert client.get("/api/index/activity").status_code == 401
    assert client.get("/api/index/failed").status_code == 401
    assert client.post("/api/index/rebuild").status_code == 401
