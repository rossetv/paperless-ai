"""Tests for search.deps — the FastAPI auth dependencies.

Exercises the dependencies through a tiny FastAPI app and TestClient so the
cookie/header plumbing is real. Covers: get_app_db yields a fresh connection
per request; get_current_user resolves a session cookie and a legacy bearer;
401 when neither is valid; require_role allows a sufficient role and 403s an
insufficient one; require_admin gates on admin; a suspended user's cookie is
rejected.

The app holds the ``app.db`` *path* — each request opens its own connection
via ``get_app_db`` — so the test seeds users through a separate connection to
the same ``tmp_path/app.db`` file; WAL mode means the per-request connections
see the seeded rows.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from appdb.users import update as update_user
from search.appstate import AppState, attach_app_state
from search.auth import SESSION_COOKIE_NAME
from search.deps import get_app_db, get_current_user, require_admin, require_role
from search.sessions import CurrentUser, begin_session
from search.setup import SetupState

_LEGACY_KEY = "legacy-search-key"


def _build_app(app_db_path: str) -> FastAPI:
    """A tiny app exposing one route per dependency under test."""
    app = FastAPI()
    attach_app_state(
        app.state,
        AppState(
            app_db_path=app_db_path,
            setup_state=SetupState(),
            legacy_api_key=_LEGACY_KEY,
        ),
    )

    @app.get("/me")
    def me(user: CurrentUser = Depends(get_current_user)) -> dict:
        return {"username": user.username, "role": user.role}

    @app.get("/member-area")
    def member_area(
        user: CurrentUser = Depends(require_role("member")),
    ) -> dict:
        return {"ok": True}

    @app.get("/admin-area")
    def admin_area(
        user: CurrentUser = Depends(require_admin),
    ) -> dict:
        return {"ok": True}

    return app


@pytest.fixture()
def app_db_path(tmp_path) -> str:
    """The path to a migrated, empty app.db file under tmp_path."""
    path = str(tmp_path / "app.db")
    conn = connect(path)
    ensure_schema(conn)
    conn.close()
    return path


@pytest.fixture()
def conn(app_db_path) -> Iterator[sqlite3.Connection]:
    """A connection to the migrated app.db, for seeding users in a test."""
    c = connect(app_db_path)
    yield c
    c.close()


def _client(app_db_path: str) -> TestClient:
    return TestClient(
        _build_app(app_db_path),
        raise_server_exceptions=False,
        base_url="https://testserver",
    )


def _login(conn, *, role: str, username: str = "u") -> str:
    """Create a user of *role* and return a live session token."""
    user = create_user(conn, username=username, password_hash="h", role=role)
    return begin_session(conn, user_id=user.id, ttl_seconds=3600).token


def test_get_app_db_yields_a_fresh_connection_each_request(app_db_path) -> None:
    """get_app_db opens a distinct sqlite3.Connection per request.

    A shared connection across request threads is the BLOCKER fixed in this
    wave: ``sqlite3.Connection`` is not safe for concurrent use. This proves
    each request's ``get_app_db`` resolution yields its own connection object —
    and that connections from two requests are never the same instance.
    """
    app = FastAPI()
    attach_app_state(
        app.state,
        AppState(
            app_db_path=app_db_path,
            setup_state=SetupState(),
            legacy_api_key=_LEGACY_KEY,
        ),
    )
    seen: list[int] = []

    @app.get("/probe")
    def probe(app_db: sqlite3.Connection = Depends(get_app_db)) -> dict:
        # The connection is a real, usable sqlite3 connection scoped to this
        # request; record its identity so the test can assert per-request
        # distinctness across calls.
        assert isinstance(app_db, sqlite3.Connection)
        seen.append(id(app_db))
        return {"id": id(app_db)}

    client = TestClient(app, raise_server_exceptions=False)
    first = client.get("/probe").json()["id"]
    second = client.get("/probe").json()["id"]
    assert first != second, "each request must get its own app.db connection"
    assert seen == [first, second]


def test_get_current_user_resolves_a_session_cookie(app_db_path, conn) -> None:
    token = _login(conn, role="member", username="alice")
    client = _client(app_db_path)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    response = client.get("/me")
    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role": "member"}


def test_get_current_user_resolves_a_legacy_bearer(app_db_path) -> None:
    client = _client(app_db_path)
    response = client.get("/me", headers={"Authorization": f"Bearer {_LEGACY_KEY}"})
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_get_current_user_401_when_no_credentials(app_db_path) -> None:
    response = _client(app_db_path).get("/me")
    assert response.status_code == 401


def test_get_current_user_401_for_a_garbage_cookie(app_db_path) -> None:
    client = _client(app_db_path)
    client.cookies.set(SESSION_COOKIE_NAME, "not-a-real-token")
    assert client.get("/me").status_code == 401


def test_get_current_user_401_for_a_wrong_bearer(app_db_path) -> None:
    client = _client(app_db_path)
    response = client.get("/me", headers={"Authorization": "Bearer wrong-key"})
    assert response.status_code == 401


def test_get_current_user_401_for_a_suspended_user(app_db_path, conn) -> None:
    user = create_user(conn, username="susie", password_hash="h", role="member")
    token = begin_session(conn, user_id=user.id, ttl_seconds=3600).token
    update_user(conn, user.id, status="suspended")
    client = _client(app_db_path)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/me").status_code == 401


def test_require_role_allows_a_sufficient_role(app_db_path, conn) -> None:
    token = _login(conn, role="member")
    client = _client(app_db_path)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/member-area").status_code == 200


def test_require_role_allows_a_higher_role(app_db_path, conn) -> None:
    token = _login(conn, role="admin")
    client = _client(app_db_path)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/member-area").status_code == 200


def test_require_role_403s_an_insufficient_role(app_db_path, conn) -> None:
    token = _login(conn, role="readonly")
    client = _client(app_db_path)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/member-area").status_code == 403


def test_require_role_401s_when_unauthenticated(app_db_path) -> None:
    assert _client(app_db_path).get("/member-area").status_code == 401


def test_require_admin_allows_an_admin(app_db_path, conn) -> None:
    token = _login(conn, role="admin")
    client = _client(app_db_path)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/admin-area").status_code == 200


def test_require_admin_403s_a_member(app_db_path, conn) -> None:
    token = _login(conn, role="member")
    client = _client(app_db_path)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/admin-area").status_code == 403


def test_require_admin_allows_a_legacy_bearer(app_db_path) -> None:
    """The legacy key resolves to a synthetic admin, so it passes admin gates."""
    client = _client(app_db_path)
    response = client.get(
        "/admin-area", headers={"Authorization": f"Bearer {_LEGACY_KEY}"}
    )
    assert response.status_code == 200
