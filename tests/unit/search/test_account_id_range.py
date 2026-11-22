"""User and API-key ids beyond the index id range are rejected, not a server error."""

from __future__ import annotations

from pathlib import Path

import pytest

from appdb.connection import connect
from appdb.users import create as create_user
from search.auth import SESSION_COOKIE_NAME
from search.sessions import begin_session
from tests.helpers.factories import make_search_settings
from tests.unit.search.conftest import build_test_client


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PATCH", "/api/users/{id}"),
        ("DELETE", "/api/users/{id}"),
        ("PATCH", "/api/api-keys/{id}"),
        ("DELETE", "/api/api-keys/{id}"),
    ],
)
def test_an_id_beyond_the_index_id_range_is_rejected(
    tmp_path: Path, method: str, path: str
) -> None:
    settings = make_search_settings(INDEX_DB_PATH=str(tmp_path / "index.db"))
    client = build_test_client(settings)
    conn = connect(settings.APP_DB_PATH)
    try:
        user = create_user(conn, username="admin", password_hash="h", role="admin")
        token = begin_session(conn, user_id=user.id, ttl_seconds=3600).token
    finally:
        conn.close()
    client.cookies.set(SESSION_COOKIE_NAME, token)
    response = client.request(method, path.format(id=2**63), json={"name": "n"})
    assert response.status_code == 422
