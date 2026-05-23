"""Integration test: API-key scope enforcement and RBAC (§5, §4.3).

Drives the real search app over a real ``app.db``/``index.db``. Proves:

- scopes gate the surface — an API-only key cannot reach /mcp, an
  MCP-only key cannot reach /api/* data routes;
- a key never exceeds its owner's role;
- key management follows §4.3 — a Read-only user cannot manage keys, a
  Member manages only their own, an Admin lists and revokes every key;
- editing is owner-only — even an Admin cannot edit another user's key
  (the deliberate asymmetry against revoke).
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
    seed_user,
)


@pytest.fixture()
def env(tmp_path):
    """Build the app; seed an admin, a member and a read-only user.

    Returns (client, app_db, ids) where ids maps role -> user id.
    """
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    admin = seed_admin(app_db, username="admin", password="admin-pw")
    member = seed_user(
        app_db, username="member", password="member-pw", role="member"
    )
    readonly = seed_user(
        app_db, username="reader", password="ro-password", role="readonly"
    )
    store_reader = StoreReader(settings)
    client = build_account_client(settings, app_db, store_reader)
    ids = {"admin": admin.id, "member": member.id, "readonly": readonly.id}
    try:
        yield client, app_db, ids
    finally:
        store_reader.close()
        app_db.close()


def _mint(app_db, *, owner_user_id, scopes):
    """Create a key directly in app_db; return the raw key."""
    from appdb.api_keys import create as create_key
    from search.api_keys import (
        generate_raw_key,
        hash_key,
        key_display_prefix,
    )

    raw = generate_raw_key()
    create_key(
        app_db,
        key_hash=hash_key(raw),
        key_prefix=key_display_prefix(raw),
        name="k",
        owner_user_id=owner_user_id,
        scopes=scopes,
    )
    return raw


def _bearer(raw):
    return {"Authorization": f"Bearer {raw}"}


# --- scope enforcement on the data routes ------------------------------

def test_api_scoped_key_reaches_the_data_routes(env) -> None:
    client, app_db, ids = env
    raw = _mint(app_db, owner_user_id=ids["member"], scopes="api")
    assert client.get("/api/stats", headers=_bearer(raw)).status_code == 200


def test_mcp_only_key_cannot_reach_the_data_routes(env) -> None:
    client, app_db, ids = env
    raw = _mint(app_db, owner_user_id=ids["member"], scopes="mcp")
    # The MCP scope does not grant /api/* — expect 403.
    assert client.get("/api/stats", headers=_bearer(raw)).status_code == 403


def test_api_only_key_cannot_reach_the_mcp_surface(env) -> None:
    client, app_db, ids = env
    raw = _mint(app_db, owner_user_id=ids["member"], scopes="api")
    # /mcp/ is gated by the MCP scope; an API-only key is rejected (401 from
    # the MCP middleware, which does not distinguish 401/403). Note: the mount
    # matches paths with a trailing slash; /mcp (no slash) falls to the SPA
    # catch-all which refuses mcp paths with its own 404 guard.
    response = client.get("/mcp/", headers=_bearer(raw))
    assert response.status_code == 401


def test_mcp_scoped_key_passes_the_mcp_auth_gate(env) -> None:
    client, app_db, ids = env
    raw = _mint(app_db, owner_user_id=ids["member"], scopes="mcp")
    # A GET to /mcp/ with a valid MCP key passes the auth middleware; the MCP
    # transport itself may then answer non-2xx for a non-MCP-protocol GET,
    # but it must NOT be the 401 the middleware returns on auth failure.
    response = client.get("/mcp/", headers=_bearer(raw))
    assert response.status_code != 401


# --- key management RBAC (spec §4.3) -----------------------------------

def test_readonly_user_cannot_list_keys(env) -> None:
    client, _, _ = env
    assert login(client, username="reader", password="ro-password").status_code == 200
    assert client.get("/api/api-keys").status_code == 403


def test_readonly_user_cannot_create_a_key(env) -> None:
    client, _, _ = env
    login(client, username="reader", password="ro-password")
    response = client.post(
        "/api/api-keys", json={"name": "x", "scopes": ["api"]}
    )
    assert response.status_code == 403


def test_readonly_user_cannot_edit_a_key(env) -> None:
    client, app_db, ids = env
    # A member-owned key the read-only user will try to edit.
    raw = _mint(app_db, owner_user_id=ids["member"], scopes="api")
    from appdb.api_keys import get_by_hash
    from search.api_keys import hash_key

    member_key = get_by_hash(app_db, hash_key(raw))
    assert member_key is not None

    login(client, username="reader", password="ro-password")
    response = client.patch(
        f"/api/api-keys/{member_key.id}", json={"name": "x"}
    )
    # A read-only user is blocked at the management gate (403) regardless of
    # ownership — it never reaches the owner-only check.
    assert response.status_code == 403


def test_member_creates_and_lists_only_their_own_keys(env) -> None:
    client, app_db, ids = env
    # An admin-owned key already exists.
    _mint(app_db, owner_user_id=ids["admin"], scopes="api")

    login(client, username="member", password="member-pw")
    created = client.post(
        "/api/api-keys", json={"name": "mine", "scopes": ["api"]}
    )
    assert created.status_code == 201
    listing = client.get("/api/api-keys").json()["keys"]
    # The member sees ONLY their own key, not the admin's.
    assert len(listing) == 1
    assert listing[0]["owner_id"] == ids["member"]
    assert listing[0]["name"] == "mine"


def test_admin_lists_every_key(env) -> None:
    client, app_db, ids = env
    _mint(app_db, owner_user_id=ids["member"], scopes="api")
    _mint(app_db, owner_user_id=ids["admin"], scopes="mcp")

    login(client, username="admin", password="admin-pw")
    listing = client.get("/api/api-keys").json()["keys"]
    owners = {k["owner_id"] for k in listing}
    assert owners == {ids["member"], ids["admin"]}


def test_member_cannot_revoke_another_users_key(env) -> None:
    client, app_db, ids = env
    # An admin-owned key.
    raw = _mint(app_db, owner_user_id=ids["admin"], scopes="api")
    from appdb.api_keys import get_by_hash
    from search.api_keys import hash_key

    admin_key = get_by_hash(app_db, hash_key(raw))
    assert admin_key is not None

    login(client, username="member", password="member-pw")
    response = client.delete(f"/api/api-keys/{admin_key.id}")
    # A member may not revoke a key they do not own — 404 rather than 403
    # so the existence of the key is not revealed (MINOR-1).
    assert response.status_code == 404


def test_member_can_revoke_their_own_key(env) -> None:
    client, app_db, ids = env
    login(client, username="member", password="member-pw")
    created = client.post(
        "/api/api-keys", json={"name": "mine", "scopes": ["api"]}
    ).json()
    response = client.delete(f"/api/api-keys/{created['api_key']['id']}")
    assert response.status_code == 204


def test_admin_can_revoke_any_users_key(env) -> None:
    client, app_db, ids = env
    raw = _mint(app_db, owner_user_id=ids["member"], scopes="api")
    from appdb.api_keys import get_by_hash
    from search.api_keys import hash_key

    member_key = get_by_hash(app_db, hash_key(raw))
    assert member_key is not None

    login(client, username="admin", password="admin-pw")
    response = client.delete(f"/api/api-keys/{member_key.id}")
    # An admin manages every key.
    assert response.status_code == 204


# --- key editing is owner-only (stricter than revoke) ------------------

def test_member_can_edit_their_own_key(env) -> None:
    client, app_db, ids = env
    login(client, username="member", password="member-pw")
    created = client.post(
        "/api/api-keys", json={"name": "mine", "scopes": ["api"]}
    ).json()
    response = client.patch(
        f"/api/api-keys/{created['api_key']['id']}",
        json={"name": "mine renamed"},
    )
    assert response.status_code == 200
    assert response.json()["api_key"]["name"] == "mine renamed"


def test_member_cannot_edit_another_users_key(env) -> None:
    client, app_db, ids = env
    raw = _mint(app_db, owner_user_id=ids["admin"], scopes="api")
    from appdb.api_keys import get_by_hash
    from search.api_keys import hash_key

    admin_key = get_by_hash(app_db, hash_key(raw))
    assert admin_key is not None

    login(client, username="member", password="member-pw")
    response = client.patch(
        f"/api/api-keys/{admin_key.id}", json={"name": "hijacked"}
    )
    # A member may not edit a key they do not own — 404 rather than 403
    # so the existence of the key is not revealed (MINOR-1).
    assert response.status_code == 404


def test_admin_cannot_edit_another_users_key(env) -> None:
    """The deliberate asymmetry: an admin can *revoke* any key but may NOT
    *edit* one they do not own — re-scoping a credential is the owner's
    call. Contrast test_admin_can_revoke_any_users_key."""
    client, app_db, ids = env
    raw = _mint(app_db, owner_user_id=ids["member"], scopes="api")
    from appdb.api_keys import get_by_hash
    from search.api_keys import hash_key

    member_key = get_by_hash(app_db, hash_key(raw))
    assert member_key is not None

    login(client, username="admin", password="admin-pw")
    response = client.patch(
        f"/api/api-keys/{member_key.id}",
        json={"scopes": ["api", "mcp", "admin"]},
    )
    # Even an admin cannot edit someone else's key — owner-only. Returns 404
    # rather than 403 so that key existence is not revealed (MINOR-1).
    assert response.status_code == 404


def test_admin_scope_key_owned_by_a_member_cannot_manage_keys(env) -> None:
    """A key never exceeds its owner's role — even with the Admin scope, a
    member-owned key only manages the member's own keys, and (since the
    member role passes the management gate) it can at least list its own.
    But it must not see every key the way a true admin does."""
    client, app_db, ids = env
    # An Admin-scoped key owned by the MEMBER user.
    member_admin_key = _mint(
        app_db, owner_user_id=ids["member"], scopes="admin"
    )
    # Another user's key exists.
    _mint(app_db, owner_user_id=ids["admin"], scopes="api")

    listing = client.get(
        "/api/api-keys", headers=_bearer(member_admin_key)
    )
    assert listing.status_code == 200
    keys = listing.json()["keys"]
    # The member-owned key lists only the member's keys (the Admin scope
    # does not promote the member to admin) — it does not see the admin's.
    assert all(k["owner_id"] == ids["member"] for k in keys)
