"""Tests for search.deps — the FastAPI auth dependencies.

Exercises the dependencies through a tiny FastAPI app and TestClient so the
cookie/header plumbing is real. Covers: get_current_user resolves a session
cookie and a legacy bearer; 401 when neither is valid; require_role allows a
sufficient role and 403s an insufficient one; require_admin gates on admin;
a suspended user's cookie is rejected.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from appdb.users import update as update_user
from search.appstate import AppState, attach_app_state
from search.auth import SESSION_COOKIE_NAME
from search.deps import get_current_user, require_admin, require_role
from search.sessions import CurrentUser, begin_session
from search.setup import SetupState

_LEGACY_KEY = "legacy-search-key"


def _build_app(conn) -> FastAPI:
    """A tiny app exposing one route per dependency under test."""
    app = FastAPI()
    attach_app_state(
        app.state,
        AppState(app_db=conn, setup_state=SetupState(), legacy_api_key=_LEGACY_KEY),
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
def conn(tmp_path):
    """A migrated app.db connection."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def _client(conn) -> TestClient:
    return TestClient(
        _build_app(conn),
        raise_server_exceptions=False,
        base_url="https://testserver",
    )


def _login(conn, *, role: str, username: str = "u") -> str:
    """Create a user of *role* and return a live session token."""
    user = create_user(conn, username=username, password_hash="h", role=role)
    return begin_session(conn, user_id=user.id, ttl_seconds=3600).token


def test_get_current_user_resolves_a_session_cookie(conn) -> None:
    token = _login(conn, role="member", username="alice")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    response = client.get("/me")
    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role": "member"}


def test_get_current_user_resolves_a_legacy_bearer(conn) -> None:
    client = _client(conn)
    response = client.get("/me", headers={"Authorization": f"Bearer {_LEGACY_KEY}"})
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_get_current_user_401_when_no_credentials(conn) -> None:
    response = _client(conn).get("/me")
    assert response.status_code == 401


def test_get_current_user_401_for_a_garbage_cookie(conn) -> None:
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, "not-a-real-token")
    assert client.get("/me").status_code == 401


def test_get_current_user_401_for_a_wrong_bearer(conn) -> None:
    client = _client(conn)
    response = client.get("/me", headers={"Authorization": "Bearer wrong-key"})
    assert response.status_code == 401


def test_get_current_user_401_for_a_suspended_user(conn) -> None:
    user = create_user(conn, username="susie", password_hash="h", role="member")
    token = begin_session(conn, user_id=user.id, ttl_seconds=3600).token
    update_user(conn, user.id, status="suspended")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/me").status_code == 401


def test_require_role_allows_a_sufficient_role(conn) -> None:
    token = _login(conn, role="member")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/member-area").status_code == 200


def test_require_role_allows_a_higher_role(conn) -> None:
    token = _login(conn, role="admin")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/member-area").status_code == 200


def test_require_role_403s_an_insufficient_role(conn) -> None:
    token = _login(conn, role="readonly")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/member-area").status_code == 403


def test_require_role_401s_when_unauthenticated(conn) -> None:
    assert _client(conn).get("/member-area").status_code == 401


def test_require_admin_allows_an_admin(conn) -> None:
    token = _login(conn, role="admin")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/admin-area").status_code == 200


def test_require_admin_403s_a_member(conn) -> None:
    token = _login(conn, role="member")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/admin-area").status_code == 403


def test_require_admin_allows_a_legacy_bearer(conn) -> None:
    """The legacy key resolves to a synthetic admin, so it passes admin gates."""
    client = _client(conn)
    response = client.get(
        "/admin-area", headers={"Authorization": f"Bearer {_LEGACY_KEY}"}
    )
    assert response.status_code == 200
