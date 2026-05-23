"""Tests for search.deps — the post-Wave-3 auth and scope dependencies.

Exercised through a tiny FastAPI app and TestClient so the cookie/header
plumbing is real. Covers: a session cookie and an API key both resolve;
401 when neither is valid; require_role gates on role; the scope
dependencies gate an API key on its scopes; a cookie caller is never
scope-limited; require_admin needs both an admin role and the Admin scope.

The app holds the ``app.db`` *path*, not a live connection — each request
opens its own connection via ``get_app_db``. The test seeds users and keys
through the fixture's separate connection to the same ``tmp_path/app.db``
file; WAL mode means the per-request connections see the seeded rows.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from appdb.api_keys import create as create_key
from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from appdb.users import update as update_user
from search.api_keys import generate_raw_key, hash_key, key_display_prefix
from search.appstate import AppState, attach_app_state
from search.auth import SESSION_COOKIE_NAME
from search.deps import (
    get_current_user,
    require_admin,
    require_api_scope,
    require_api_scope_member,
    require_mcp_scope,
    require_role,
)
from search.sessions import CurrentUser, begin_session
from search.setup import SetupState


def _db_path(conn: sqlite3.Connection) -> str:
    """Return the filesystem path of *conn*'s ``main`` database.

    The app holds the ``app.db`` path and opens its own per-request
    connection via ``get_app_db``; the test fixture owns a separate
    connection to the same file. This bridges the fixture's connection back
    to the path the app needs.
    """
    rows = conn.execute("PRAGMA database_list").fetchall()
    return next(row[2] for row in rows if row[1] == "main")


def _build_app(conn) -> FastAPI:
    """A tiny app exposing one route per dependency under test."""
    app = FastAPI()
    attach_app_state(
        app.state,
        AppState(app_db_path=_db_path(conn), setup_state=SetupState()),
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
    def admin_area(user: CurrentUser = Depends(require_admin)) -> dict:
        return {"ok": True}

    @app.get("/api-area")
    def api_area(user: CurrentUser = Depends(require_api_scope)) -> dict:
        return {"ok": True}

    @app.get("/api-member-area")
    def api_member_area(
        user: CurrentUser = Depends(require_api_scope_member),
    ) -> dict:
        return {"ok": True}

    @app.get("/mcp-area")
    def mcp_area(user: CurrentUser = Depends(require_mcp_scope)) -> dict:
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


def _cookie_login(conn, *, role: str, username: str = "u") -> str:
    """Create a user of *role* and return a live session token."""
    user = create_user(conn, username=username, password_hash="h", role=role)
    return begin_session(conn, user_id=user.id, ttl_seconds=3600).token


def _mint_key(conn, *, role: str, scopes: str, username: str) -> str:
    """Create a user of *role* and an API key with *scopes*; return the key."""
    user = create_user(conn, username=username, password_hash="h", role=role)
    raw = generate_raw_key()
    create_key(
        conn,
        key_hash=hash_key(raw),
        key_prefix=key_display_prefix(raw),
        name="k",
        owner_user_id=user.id,
        scopes=scopes,
    )
    return raw


def _bearer(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


# --- get_current_user --------------------------------------------------


def test_get_current_user_resolves_a_session_cookie(conn) -> None:
    token = _cookie_login(conn, role="member", username="alice")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    response = client.get("/me")
    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role": "member"}


def test_get_current_user_resolves_an_api_key(conn) -> None:
    raw = _mint_key(conn, role="admin", scopes="api", username="svc")
    response = _client(conn).get("/me", headers=_bearer(raw))
    assert response.status_code == 200
    assert response.json() == {"username": "svc", "role": "admin"}


def test_get_current_user_401_when_no_credentials(conn) -> None:
    assert _client(conn).get("/me").status_code == 401


def test_get_current_user_401_for_a_garbage_cookie(conn) -> None:
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, "not-a-real-token")
    assert client.get("/me").status_code == 401


def test_get_current_user_401_for_an_unknown_bearer(conn) -> None:
    response = _client(conn).get("/me", headers=_bearer("sk-pls-nope"))
    assert response.status_code == 401


def test_get_current_user_401_for_a_suspended_user(conn) -> None:
    user = create_user(conn, username="susie", password_hash="h", role="member")
    token = begin_session(conn, user_id=user.id, ttl_seconds=3600).token
    update_user(conn, user.id, status="suspended")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/me").status_code == 401


# --- require_role ------------------------------------------------------


def test_require_role_allows_a_sufficient_role(conn) -> None:
    token = _cookie_login(conn, role="member")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/member-area").status_code == 200


def test_require_role_403s_an_insufficient_role(conn) -> None:
    token = _cookie_login(conn, role="readonly")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/member-area").status_code == 403


def test_require_role_401s_when_unauthenticated(conn) -> None:
    assert _client(conn).get("/member-area").status_code == 401


# --- require_admin -----------------------------------------------------


def test_require_admin_allows_an_admin_cookie(conn) -> None:
    token = _cookie_login(conn, role="admin")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/admin-area").status_code == 200


def test_require_admin_403s_a_member_cookie(conn) -> None:
    token = _cookie_login(conn, role="member")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/admin-area").status_code == 403


def test_require_admin_allows_an_admin_key_with_admin_scope(conn) -> None:
    raw = _mint_key(conn, role="admin", scopes="admin", username="adminkey")
    assert _client(conn).get("/admin-area", headers=_bearer(raw)).status_code == 200


def test_require_admin_403s_an_admin_key_without_admin_scope(conn) -> None:
    """An admin owner is not enough — the key itself needs the Admin scope."""
    raw = _mint_key(conn, role="admin", scopes="api", username="apikey")
    assert _client(conn).get("/admin-area", headers=_bearer(raw)).status_code == 403


def test_require_admin_403s_an_admin_scope_key_owned_by_a_member(conn) -> None:
    """A key never exceeds its owner's role, scope or no scope."""
    raw = _mint_key(conn, role="member", scopes="admin", username="memberkey")
    assert _client(conn).get("/admin-area", headers=_bearer(raw)).status_code == 403


# --- require_api_scope -------------------------------------------------


def test_api_scope_allows_a_cookie_user_without_any_scope(conn) -> None:
    """A logged-in human is never scope-limited."""
    token = _cookie_login(conn, role="readonly")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/api-area").status_code == 200


def test_api_scope_allows_a_key_with_the_api_scope(conn) -> None:
    raw = _mint_key(conn, role="member", scopes="api", username="k1")
    assert _client(conn).get("/api-area", headers=_bearer(raw)).status_code == 200


def test_api_scope_403s_a_key_without_the_api_scope(conn) -> None:
    raw = _mint_key(conn, role="member", scopes="mcp", username="k2")
    assert _client(conn).get("/api-area", headers=_bearer(raw)).status_code == 403


# --- require_api_scope_member -----------------------------------------


def test_api_member_scope_403s_a_readonly_cookie(conn) -> None:
    token = _cookie_login(conn, role="readonly")
    client = _client(conn)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/api-member-area").status_code == 403


def test_api_member_scope_allows_a_member_key_with_api_scope(conn) -> None:
    raw = _mint_key(conn, role="member", scopes="api", username="k3")
    assert (
        _client(conn).get("/api-member-area", headers=_bearer(raw)).status_code == 200
    )


# --- require_mcp_scope -------------------------------------------------


def test_mcp_scope_allows_a_key_with_the_mcp_scope(conn) -> None:
    raw = _mint_key(conn, role="readonly", scopes="mcp", username="k4")
    assert _client(conn).get("/mcp-area", headers=_bearer(raw)).status_code == 200


def test_mcp_scope_403s_a_key_without_the_mcp_scope(conn) -> None:
    raw = _mint_key(conn, role="readonly", scopes="api", username="k5")
    assert _client(conn).get("/mcp-area", headers=_bearer(raw)).status_code == 403
