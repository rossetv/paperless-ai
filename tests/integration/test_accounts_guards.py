"""Integration tests for the self / last-admin guards (web-redesign §4.8).

Exercises the real FastAPI app through ``TestClient`` against a real
``tmp_path`` ``app.db``. The guard predicates are unit-tested in
``tests/unit/search/test_accounts.py``; these tests prove they are wired into
the PATCH/DELETE handlers and surface as 409 over HTTP.

Coverage:
- An admin cannot delete / suspend / demote themselves (409).
- The sole admin cannot be deleted / suspended / demoted (409) — over HTTP
  the sole admin is necessarily the actor, so this is the self path; the
  pure last-admin branch (a different admin acting) is unreachable through
  the API and is covered by the test_accounts.py unit tests.
- With two admins, deleting / demoting one of them succeeds.
- A self display-name edit (touching neither role nor status) is allowed.
"""

from __future__ import annotations

from pathlib import Path

from store.reader import StoreReader

from tests.integration.accounts_helpers import (
    build_account_client,
    login,
    make_settings,
    open_app_db,
    seed_admin,
    seed_store,
)


def _admin_client(settings, app_db, store_reader, *, username, password):
    """Build a client and log it in as the given admin; return the client."""
    client = build_account_client(settings, app_db, store_reader)
    assert (
        login(client, username=username, password=password).status_code
        == 200
    )
    return client


def test_admin_cannot_delete_themselves(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        # Two admins, so the guard hit is "yourself", not "last admin".
        boss = seed_admin(app_db, username="boss", password="boss-password")
        seed_admin(app_db, username="deputy", password="deputy-password")
        client = _admin_client(
            settings, app_db, store_reader,
            username="boss", password="boss-password",
        )
        response = client.delete(f"/api/users/{boss.id}")
        assert response.status_code == 409
        assert "yourself" in response.json()["detail"].lower()
    finally:
        store_reader.close()
        app_db.close()


def test_admin_cannot_suspend_themselves(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        boss = seed_admin(app_db, username="boss", password="boss-password")
        seed_admin(app_db, username="deputy", password="deputy-password")
        client = _admin_client(
            settings, app_db, store_reader,
            username="boss", password="boss-password",
        )
        response = client.patch(
            f"/api/users/{boss.id}", json={"status": "suspended"}
        )
        assert response.status_code == 409
        assert "yourself" in response.json()["detail"].lower()
    finally:
        store_reader.close()
        app_db.close()


def test_admin_cannot_demote_themselves(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        boss = seed_admin(app_db, username="boss", password="boss-password")
        seed_admin(app_db, username="deputy", password="deputy-password")
        client = _admin_client(
            settings, app_db, store_reader,
            username="boss", password="boss-password",
        )
        response = client.patch(
            f"/api/users/{boss.id}", json={"role": "member"}
        )
        assert response.status_code == 409
    finally:
        store_reader.close()
        app_db.close()


def test_sole_admin_cannot_be_deleted(tmp_path: Path) -> None:
    """The only admin cannot be deleted through DELETE /api/users/{id}.

    With exactly one admin, that admin is both the last admin and — because
    only an admin can reach the route — necessarily the actor. The handler's
    guard rejects the deletion 409. (The pure last-admin-only branch, where a
    *different* admin acts, is unreachable over HTTP: any other actor able to
    pass the admin gate is themselves an admin, making two admins. That
    branch is covered by the unit tests in test_accounts.py.)
    """
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        boss = seed_admin(app_db, username="boss", password="boss-password")
        client = _admin_client(
            settings, app_db, store_reader,
            username="boss", password="boss-password",
        )
        response = client.delete(f"/api/users/{boss.id}")
        assert response.status_code == 409, response.text
    finally:
        store_reader.close()
        app_db.close()


def test_sole_admin_cannot_be_suspended(tmp_path: Path) -> None:
    """The only admin cannot be suspended through PATCH /api/users/{id}.

    As with deletion, the sole admin cannot be suspended: the guard rejects
    it 409. The actor is necessarily that same admin (HTTP reachability).
    """
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        boss = seed_admin(app_db, username="boss", password="boss-password")
        client = _admin_client(
            settings, app_db, store_reader,
            username="boss", password="boss-password",
        )
        response = client.patch(
            f"/api/users/{boss.id}", json={"status": "suspended"}
        )
        assert response.status_code == 409, response.text
    finally:
        store_reader.close()
        app_db.close()


def test_sole_admin_cannot_be_demoted(tmp_path: Path) -> None:
    """The only admin cannot be demoted to member through PATCH -> 409."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        boss = seed_admin(app_db, username="boss", password="boss-password")
        client = _admin_client(
            settings, app_db, store_reader,
            username="boss", password="boss-password",
        )
        response = client.patch(
            f"/api/users/{boss.id}", json={"role": "member"}
        )
        assert response.status_code == 409, response.text
    finally:
        store_reader.close()
        app_db.close()


def test_a_non_last_admin_can_be_deleted(tmp_path: Path) -> None:
    """With two admins, one admin deleting the OTHER admin succeeds (204)."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_admin(app_db, username="boss", password="boss-password")
        deputy = seed_admin(
            app_db, username="deputy", password="deputy-password"
        )
        client = _admin_client(
            settings, app_db, store_reader,
            username="boss", password="boss-password",
        )
        # boss deletes deputy — two admins existed, so this is allowed.
        response = client.delete(f"/api/users/{deputy.id}")
        assert response.status_code == 204
    finally:
        store_reader.close()
        app_db.close()


def test_a_non_last_admin_can_be_demoted(tmp_path: Path) -> None:
    """With two admins, demoting one of them to member succeeds (200)."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_admin(app_db, username="boss", password="boss-password")
        deputy = seed_admin(
            app_db, username="deputy", password="deputy-password"
        )
        client = _admin_client(
            settings, app_db, store_reader,
            username="boss", password="boss-password",
        )
        response = client.patch(
            f"/api/users/{deputy.id}", json={"role": "member"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["user"]["role"] == "member"
    finally:
        store_reader.close()
        app_db.close()


def test_admin_can_edit_their_own_display_name(tmp_path: Path) -> None:
    """A self-edit that changes neither role nor status is allowed (200)."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        boss = seed_admin(app_db, username="boss", password="boss-password")
        client = _admin_client(
            settings, app_db, store_reader,
            username="boss", password="boss-password",
        )
        response = client.patch(
            f"/api/users/{boss.id}", json={"display_name": "The Boss"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["user"]["display_name"] == "The Boss"
    finally:
        store_reader.close()
        app_db.close()
