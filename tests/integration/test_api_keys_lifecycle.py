"""Integration test: the full API-key lifecycle (web-redesign §5).

Drives the real search FastAPI app over a real ``tmp_path`` ``app.db`` and a
real seeded ``index.db``: an admin signs in, mints a key via
``POST /api/api-keys``, the raw key authenticates a ``/api/*`` request, the
key is edited via ``PATCH /api/api-keys/{id}``, listed, then revoked via
``DELETE /api/api-keys/{id}``, and the same key is afterwards rejected with
401. Also asserts the full raw key is returned exactly once and never
re-exposed by the list or edit endpoints.
"""

from __future__ import annotations

import pytest

from store.reader import StoreReader
from tests.integration.accounts_helpers import (
    build_account_client,
    login,
    make_settings,
    open_app_db,
    seed_admin,
    seed_store,
)


@pytest.fixture()
def setup(tmp_path):
    """Build the app with a seeded store and one admin past first-run setup.

    Returns the TestClient and the open app.db connection.
    """
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    seed_admin(app_db, username="admin", password="admin-password")
    store_reader = StoreReader(settings)
    client = build_account_client(settings, app_db, store_reader)
    try:
        yield client, app_db
    finally:
        store_reader.close()
        app_db.close()


def _as_admin(client):
    """Sign the client in as the seeded admin; return nothing."""
    response = login(client, username="admin", password="admin-password")
    assert response.status_code == 200, response.text


def test_create_key_returns_the_full_key_once(setup) -> None:
    client, _ = setup
    _as_admin(client)
    response = client.post("/api/api-keys", json={"name": "CI", "scopes": ["api"]})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["secret"].startswith("sk-pls-")
    assert body["api_key"]["name"] == "CI"
    assert body["api_key"]["scopes"] == ["api"]
    assert body["api_key"]["revoked_at"] is None
    # The metadata must not echo the raw key or a hash.
    assert "key_hash" not in body["api_key"]


def test_list_never_re_exposes_the_raw_key(setup) -> None:
    client, _ = setup
    _as_admin(client)
    created = client.post(
        "/api/api-keys", json={"name": "CI", "scopes": ["api"]}
    ).json()
    raw_key = created["secret"]

    listing = client.get("/api/api-keys")
    assert listing.status_code == 200
    # The raw key appears nowhere in the list response.
    assert raw_key not in listing.text
    keys = listing.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["key_prefix"] == raw_key[:12]


def test_a_minted_key_authenticates_an_api_request(setup) -> None:
    client, _ = setup
    _as_admin(client)
    raw_key = client.post(
        "/api/api-keys", json={"name": "CI", "scopes": ["api"]}
    ).json()["secret"]

    # Drop the session cookie so only the bearer key can authenticate.
    client.cookies.clear()
    assert client.get("/api/stats").status_code == 401  # no cookie, no key

    response = client.get("/api/stats", headers={"Authorization": f"Bearer {raw_key}"})
    assert response.status_code == 200, response.text


def test_revoked_key_is_rejected(setup) -> None:
    client, _ = setup
    _as_admin(client)
    created = client.post(
        "/api/api-keys", json={"name": "CI", "scopes": ["api"]}
    ).json()
    raw_key = created["secret"]
    key_id = created["api_key"]["id"]

    # Drop the session cookie so only the bearer key can authenticate — this
    # ensures the revocation check is actually exercised rather than the
    # session cookie silently masking the revoked credential.
    client.cookies.clear()

    # The key works before revocation.
    before = client.get("/api/stats", headers={"Authorization": f"Bearer {raw_key}"})
    assert before.status_code == 200

    # Revoke it (re-authenticate via the key itself, then immediately drop auth
    # and verify rejection; but the revoke endpoint requires key-management
    # scope — use a fresh admin login instead).
    login_resp = login(client, username="admin", password="admin-password")
    assert login_resp.status_code == 200
    deleted = client.delete(f"/api/api-keys/{key_id}")
    assert deleted.status_code == 204
    # Drop the session cookie again so only the bearer key is presented.
    client.cookies.clear()

    # The same key is now rejected.
    after = client.get("/api/stats", headers={"Authorization": f"Bearer {raw_key}"})
    assert after.status_code == 401


def test_revoke_marks_the_key_revoked_in_the_listing(setup) -> None:
    client, _ = setup
    _as_admin(client)
    created = client.post(
        "/api/api-keys", json={"name": "CI", "scopes": ["api"]}
    ).json()
    key_id = created["api_key"]["id"]
    client.delete(f"/api/api-keys/{key_id}")

    keys = client.get("/api/api-keys").json()["keys"]
    assert len(keys) == 1
    assert keys[0]["id"] == key_id
    assert keys[0]["revoked_at"] is not None


def test_edit_a_key_changes_name_and_scopes(setup) -> None:
    client, _ = setup
    _as_admin(client)
    created = client.post(
        "/api/api-keys", json={"name": "CI", "scopes": ["api"]}
    ).json()
    key_id = created["api_key"]["id"]

    response = client.patch(
        f"/api/api-keys/{key_id}",
        json={"name": "CI renamed", "scopes": ["api", "mcp"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["api_key"]["name"] == "CI renamed"
    assert body["api_key"]["scopes"] == ["api", "mcp"]
    # The edit response must never carry a secret.
    assert "secret" not in body
    assert "key_hash" not in body["api_key"]


def test_edit_can_set_and_clear_the_expiry(setup) -> None:
    client, _ = setup
    _as_admin(client)
    key_id = client.post(
        "/api/api-keys", json={"name": "CI", "scopes": ["api"]}
    ).json()["api_key"]["id"]

    # Set an expiry.
    set_resp = client.patch(
        f"/api/api-keys/{key_id}",
        json={"expires_at": "2027-01-01T00:00:00+00:00"},
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["api_key"]["expires_at"] == "2027-01-01T00:00:00+00:00"

    # Clear it again — an explicit null means "never expires".
    clear_resp = client.patch(f"/api/api-keys/{key_id}", json={"expires_at": None})
    assert clear_resp.status_code == 200
    assert clear_resp.json()["api_key"]["expires_at"] is None


def test_edit_is_reflected_in_the_listing(setup) -> None:
    client, _ = setup
    _as_admin(client)
    key_id = client.post(
        "/api/api-keys", json={"name": "CI", "scopes": ["api"]}
    ).json()["api_key"]["id"]
    client.patch(f"/api/api-keys/{key_id}", json={"name": "CI renamed"})

    keys = client.get("/api/api-keys").json()["keys"]
    assert keys[0]["id"] == key_id
    assert keys[0]["name"] == "CI renamed"


def test_edit_an_unknown_key_is_404(setup) -> None:
    client, _ = setup
    _as_admin(client)
    response = client.patch("/api/api-keys/999999", json={"name": "ghost"})
    assert response.status_code == 404


def test_edit_rejects_an_unknown_scope(setup) -> None:
    client, _ = setup
    _as_admin(client)
    key_id = client.post(
        "/api/api-keys", json={"name": "CI", "scopes": ["api"]}
    ).json()["api_key"]["id"]
    response = client.patch(
        f"/api/api-keys/{key_id}", json={"scopes": ["api", "superuser"]}
    )
    # Pydantic validation at the boundary -> 422.
    assert response.status_code == 422


def test_delete_an_unknown_key_is_404(setup) -> None:
    client, _ = setup
    _as_admin(client)
    assert client.delete("/api/api-keys/999999").status_code == 404


def test_create_rejects_an_unknown_scope(setup) -> None:
    client, _ = setup
    _as_admin(client)
    response = client.post(
        "/api/api-keys",
        json={"name": "CI", "scopes": ["api", "superuser"]},
    )
    # Pydantic validation at the boundary -> 422.
    assert response.status_code == 422


def test_create_rejects_an_empty_scope_list(setup) -> None:
    client, _ = setup
    _as_admin(client)
    response = client.post("/api/api-keys", json={"name": "CI", "scopes": []})
    assert response.status_code == 422


def test_api_key_management_requires_authentication(setup) -> None:
    client, _ = setup
    # No sign-in, no key — the management endpoints reject with 401.
    assert client.get("/api/api-keys").status_code == 401
    assert (
        client.post("/api/api-keys", json={"name": "x", "scopes": ["api"]}).status_code
        == 401
    )
    assert client.patch("/api/api-keys/1", json={"name": "x"}).status_code == 401
    assert client.delete("/api/api-keys/1").status_code == 401
