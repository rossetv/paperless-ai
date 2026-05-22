"""Tests for the recent-search record hook on POST /api/search.

A successful search by a real session user must write a recent_searches
row; a failed search must not record; and a database error while recording
must not fail the search. These exercise the real search router over a
tmp_path app.db.

Adaptation note: the plan specified ``AppState(app_db=conn, ...)`` but
``AppState`` holds ``app_db_path: str``, not a live connection.  The
``_build_app`` helper below passes ``app_db_path`` (a file path) so that
``get_app_db`` opens per-request connections — consistent with the real app
and the per-request connection model (CODE_GUIDELINES §8.4).  The ``conn``
fixture still provides a direct inspection connection to the same file.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from appdb.connection import connect
from appdb.recent_searches import list_for_user
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from search.appstate import AppState, attach_app_state
from search.auth import SESSION_COOKIE_NAME
from search.deps import get_current_user, require_role
from search.routes import build_api_router
from search.sessions import begin_session
from search.setup import SetupState
from tests.helpers.factories import make_search_result, make_source_document

def _mock_core(*, fail: bool = False) -> MagicMock:
    """A stub SearchCore returning a fixed result, or raising when *fail*."""
    core = MagicMock()
    if fail:
        core.answer.side_effect = RuntimeError("search exploded")
    else:
        core.answer.return_value = make_search_result(
            answer="answer",
            sources=(
                make_source_document(
                    document_id=1,
                    title="Doc",
                    correspondent="C",
                    document_type="T",
                    created="2024-01-01T00:00:00Z",
                    snippet="snip",
                    score=0.9,
                ),
            ),
        )
    return core


def _build_app(tmp_path, core: MagicMock) -> FastAPI:
    """A FastAPI app mounting only the search router over a tmp_path app.db.

    ``AppState`` holds ``app_db_path`` (a string path), not a live connection.
    Each request opens its own connection through ``get_app_db``, exactly as
    the production app does.
    """
    app_db_path = str(tmp_path / "app.db")
    app = FastAPI()
    attach_app_state(
        app.state,
        AppState(
            app_db_path=app_db_path,
            setup_state=SetupState(),
        ),
    )
    settings = MagicMock()
    settings.SEARCH_MAX_CONCURRENT = 4
    app.include_router(
        build_api_router(
            settings,
            core,
            MagicMock(),
            require_reader=require_role("readonly"),
            require_member=require_role("member"),
            get_current_user=get_current_user,
        )
    )
    return app


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection; the test's direct inspection handle."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def _client(tmp_path, core: MagicMock) -> TestClient:
    return TestClient(
        _build_app(tmp_path, core),
        raise_server_exceptions=False,
        base_url="https://testserver",
    )


def test_successful_search_records_a_recent_search(conn, tmp_path) -> None:
    """A signed-in user's successful search is written to recent_searches."""
    user = create_user(conn, username="alice", password_hash="h", role="readonly")
    token = begin_session(conn, user_id=user.id, ttl_seconds=3600).token
    client = _client(tmp_path, _mock_core())
    client.cookies.set(SESSION_COOKIE_NAME, token)

    response = client.post("/api/search", json={"query": "gas bill total"})
    assert response.status_code == 200

    history = list_for_user(conn, user.id)
    assert [r.query for r in history] == ["gas bill total"]


def test_failed_search_records_nothing(conn, tmp_path) -> None:
    """A search that raises does not write a recent_searches row."""
    user = create_user(conn, username="bob", password_hash="h", role="readonly")
    token = begin_session(conn, user_id=user.id, ttl_seconds=3600).token
    client = _client(tmp_path, _mock_core(fail=True))
    client.cookies.set(SESSION_COOKIE_NAME, token)

    response = client.post("/api/search", json={"query": "doomed query"})
    assert response.status_code == 500
    assert list_for_user(conn, user.id) == []


def test_record_failure_does_not_fail_the_search(conn, tmp_path, monkeypatch) -> None:
    """A database error while recording is swallowed — the search still 200s."""
    user = create_user(conn, username="carol", password_hash="h", role="readonly")
    token = begin_session(conn, user_id=user.id, ttl_seconds=3600).token

    def _boom(*args, **kwargs):
        raise RuntimeError("recent_searches write failed")

    monkeypatch.setattr("search.routes.recent_search_store.record", _boom)
    client = _client(tmp_path, _mock_core())
    client.cookies.set(SESSION_COOKIE_NAME, token)

    response = client.post("/api/search", json={"query": "resilient"})
    assert response.status_code == 200
