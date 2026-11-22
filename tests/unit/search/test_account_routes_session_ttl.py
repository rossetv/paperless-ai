"""The login route applies a saved SEARCH_SESSION_TTL without a restart."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from appdb import config as config_store
from appdb.connection import connect
from appdb.passwords import hash_password
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from search.account_routes import build_account_router
from search.appstate import AppState, attach_app_state
from search.setup import SetupState


def _remember_cookie(tmp_path, saved_ttl: str | None) -> str:
    app_db = str(tmp_path / "app.db")
    conn = connect(app_db)
    ensure_schema(conn)
    create_user(
        conn, username="amy", password_hash=hash_password("pw-123456"), role="admin"
    )
    if saved_ttl is not None:
        config_store.set_value(conn, "SEARCH_SESSION_TTL", saved_ttl)
    conn.close()
    app = FastAPI()
    attach_app_state(app.state, AppState(app_db, SetupState()))
    startup = MagicMock()
    startup.SEARCH_SESSION_TTL = 604800
    app.include_router(build_account_router(startup, MagicMock()))
    response = TestClient(app).post(
        "/api/auth/login",
        json={"username": "amy", "password": "pw-123456", "remember": True},
    )
    assert response.status_code == 200
    return response.headers["set-cookie"]


def test_remember_login_cookie_uses_the_ttl_saved_after_startup(tmp_path) -> None:
    assert "Max-Age=1234" in _remember_cookie(tmp_path, "1234")


def test_remember_login_cookie_uses_the_startup_ttl_when_none_is_saved(
    tmp_path,
) -> None:
    assert "Max-Age=604800" in _remember_cookie(tmp_path, None)
