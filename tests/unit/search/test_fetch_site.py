"""Tests for refusing cookie-session changes marked as sent from another site."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from appdb.connection import connect
from appdb.users import create as create_user
from search.auth import SESSION_COOKIE_NAME
from search.sessions import begin_session
from tests.helpers.factories import make_search_settings
from tests.helpers.search import mint_api_key
from tests.unit.search.conftest import build_test_client


def _logged_in_client(tmp_path: Path) -> tuple[Any, str]:
    """Return a client holding an admin session cookie, and an API key for that admin."""
    settings = make_search_settings(INDEX_DB_PATH=str(tmp_path / "index.db"))
    client = build_test_client(settings)
    conn = connect(settings.APP_DB_PATH)
    try:
        user = create_user(conn, username="admin", password_hash="h", role="admin")
        token = begin_session(conn, user_id=user.id, ttl_seconds=3600).token
        raw_key = mint_api_key(conn, owner_user_id=user.id, scopes="api")
    finally:
        conn.close()
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return client, raw_key


@pytest.mark.parametrize("fetch_site", ["cross-site", "same-site"])
def test_a_cookie_session_post_marked_from_another_site_gets_403(
    tmp_path: Path, fetch_site: str
) -> None:
    client, _ = _logged_in_client(tmp_path)
    response = client.post("/api/reconcile", headers={"Sec-Fetch-Site": fetch_site})
    assert response.status_code == 403
    assert "detail" in response.json()
    assert response.headers["x-content-type-options"] == "nosniff"
    assert not (tmp_path / "reconcile.request").exists()


@pytest.mark.parametrize(
    "headers", [{"Sec-Fetch-Site": "same-origin"}, {"Sec-Fetch-Site": "none"}, {}]
)
def test_a_cookie_session_post_from_the_app_itself_is_accepted(
    tmp_path: Path, headers: dict[str, str]
) -> None:
    client, _ = _logged_in_client(tmp_path)
    assert client.post("/api/reconcile", headers=headers).status_code == 202


def test_a_cookie_session_get_marked_cross_site_is_unaffected(tmp_path: Path) -> None:
    client, _ = _logged_in_client(tmp_path)
    response = client.get("/api/auth/me", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 200


def test_an_api_key_post_marked_cross_site_is_accepted(tmp_path: Path) -> None:
    client, raw_key = _logged_in_client(tmp_path)
    response = client.post(
        "/api/reconcile",
        headers={"Sec-Fetch-Site": "cross-site", "Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 202


def test_a_post_without_a_session_cookie_marked_cross_site_reaches_auth() -> None:
    client = build_test_client(make_search_settings())
    response = client.post("/api/reconcile", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 401
