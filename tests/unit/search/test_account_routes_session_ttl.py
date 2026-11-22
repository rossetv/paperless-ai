"""The login route applies a saved SEARCH_SESSION_TTL without a restart."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from appdb import config as config_store
from appdb.connection import connect
from appdb.passwords import hash_password
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from common.config import _SETTINGS_CACHE
from search.account_routes import build_account_router
from search.appstate import AppState, attach_app_state
from search.setup import SetupState


def test_remember_login_cookie_uses_the_ttl_saved_after_startup(tmp_path) -> None:
    app_db = str(tmp_path / "app.db")
    conn = connect(app_db)
    ensure_schema(conn)
    create_user(
        conn, username="amy", password_hash=hash_password("pw-123456"), role="admin"
    )
    env = {
        "APP_DB_PATH": app_db,
        "INDEX_DB_PATH": str(tmp_path / "index.db"),
        "PAPERLESS_TOKEN": "t",
        "OPENAI_API_KEY": "k",
    }
    app = FastAPI()
    attach_app_state(app.state, AppState(app_db, SetupState()))
    startup = MagicMock()
    startup.SEARCH_SESSION_TTL = 604800
    app.include_router(build_account_router(startup, MagicMock()))

    with patch.dict(os.environ, env, clear=True):
        _SETTINGS_CACHE.pop(app_db, None)
        config_store.set_value(conn, "SEARCH_SESSION_TTL", "1234")
        conn.close()
        response = TestClient(app).post(
            "/api/auth/login",
            json={"username": "amy", "password": "pw-123456", "remember": True},
        )

    assert response.status_code == 200
    assert "Max-Age=1234" in response.headers["set-cookie"]
