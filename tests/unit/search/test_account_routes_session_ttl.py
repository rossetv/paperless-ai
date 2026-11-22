"""The login route applies a saved SEARCH_SESSION_TTL without a restart."""

from __future__ import annotations

import os
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


def _remember_cookie(
    tmp_path, monkeypatch, saved_ttl: str | None, startup_ttl: int = 604800
) -> str:
    monkeypatch.setattr(
        os,
        "environ",
        {"PAPERLESS_TOKEN": "tok-123", "OPENAI_API_KEY": "sk-test"},
    )
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
    startup.SEARCH_SESSION_TTL = startup_ttl
    app.include_router(build_account_router(startup, MagicMock()))
    response = TestClient(app).post(
        "/api/auth/login",
        json={"username": "amy", "password": "pw-123456", "remember": True},
    )
    assert response.status_code == 200
    return response.headers["set-cookie"]


def test_remember_login_cookie_uses_the_ttl_saved_after_startup(
    tmp_path, monkeypatch
) -> None:
    assert "Max-Age=1234" in _remember_cookie(tmp_path, monkeypatch, "1234")


def test_remember_login_cookie_uses_the_startup_ttl_when_none_is_saved(
    tmp_path, monkeypatch
) -> None:
    assert "Max-Age=604800" in _remember_cookie(tmp_path, monkeypatch, None)


def test_remember_login_cookie_uses_the_default_when_the_saved_ttl_is_cleared(
    tmp_path, monkeypatch
) -> None:
    cookie = _remember_cookie(tmp_path, monkeypatch, "", startup_ttl=3600)
    assert "Max-Age=604800" in cookie


def test_remember_login_cookie_uses_the_longest_allowed_ttl(
    tmp_path, monkeypatch
) -> None:
    cookie = _remember_cookie(tmp_path, monkeypatch, "315360000")
    assert "Max-Age=315360000" in cookie
