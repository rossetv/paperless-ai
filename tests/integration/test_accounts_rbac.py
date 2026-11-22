"""Integration tests for role gates and session revocation on suspend, delete or
password reset."""

from __future__ import annotations

from pathlib import Path

from store.reader import StoreReader

from search.auth import SESSION_COOKIE_NAME
from tests.integration.accounts_helpers import (
    build_account_client,
    login,
    make_settings,
    open_app_db,
    seed_admin,
    seed_store,
    seed_user,
)


def test_suspending_a_user_kills_their_live_session(tmp_path: Path) -> None:
    """An admin suspends a logged-in member; the member's cookie stops working."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        admin = seed_admin(app_db, username="boss", password="boss-password")
        victim = seed_user(
            app_db,
            username="mallory",
            password="mallory-password",
            role="member",
        )

        # The victim logs in on their own client and confirms access.
        victim_client = build_account_client(settings, app_db, store_reader)
        assert (
            login(
                victim_client,
                username="mallory",
                password="mallory-password",
            ).status_code
            == 200
        )
        assert victim_client.get("/api/auth/me").status_code == 200

        # The admin, on a separate client, suspends the victim.
        admin_client = build_account_client(settings, app_db, store_reader)
        assert (
            login(admin_client, username="boss", password="boss-password").status_code
            == 200
        )
        patched = admin_client.patch(
            f"/api/users/{victim.id}", json={"status": "suspended"}
        )
        assert patched.status_code == 200, patched.text

        # The victim's previously valid cookie is now dead.
        assert victim_client.get("/api/auth/me").status_code == 401
        sessions_left = app_db.execute(
            "SELECT user_id FROM sessions WHERE user_id IN (?, ?)",
            (admin.id, victim.id),
        ).fetchall()
        assert [row[0] for row in sessions_left] == [admin.id]
        assert admin_client.get("/api/auth/me").status_code == 200
    finally:
        store_reader.close()
        app_db.close()


def test_deleting_a_user_kills_their_live_session(tmp_path: Path) -> None:
    """Deleting a user revokes their session via the ON DELETE CASCADE."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_admin(app_db, username="boss", password="boss-password")
        victim = seed_user(
            app_db,
            username="mallory",
            password="mallory-password",
            role="member",
        )

        victim_client = build_account_client(settings, app_db, store_reader)
        assert (
            login(
                victim_client,
                username="mallory",
                password="mallory-password",
            ).status_code
            == 200
        )

        admin_client = build_account_client(settings, app_db, store_reader)
        assert (
            login(admin_client, username="boss", password="boss-password").status_code
            == 200
        )
        deleted = admin_client.delete(f"/api/users/{victim.id}")
        assert deleted.status_code == 204

        assert victim_client.get("/api/auth/me").status_code == 401
    finally:
        store_reader.close()
        app_db.close()


def test_resetting_a_password_kills_the_users_live_sessions(tmp_path: Path) -> None:
    """An admin resets a logged-in member's password; the old cookie stops working."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_admin(app_db, username="boss", password="boss-password")
        member = seed_user(
            app_db, username="alice", password="alice-password", role="member"
        )

        member_client = build_account_client(settings, app_db, store_reader)
        assert (
            login(member_client, username="alice", password="alice-password")
        ).status_code == 200
        admin_client = build_account_client(settings, app_db, store_reader)
        assert (
            login(admin_client, username="boss", password="boss-password")
        ).status_code == 200

        patched = admin_client.patch(
            f"/api/users/{member.id}", json={"password": "a-brand-new-password"}
        )
        assert patched.status_code == 200, patched.text

        assert member_client.get("/api/auth/me").status_code == 401
        assert admin_client.get("/api/auth/me").status_code == 200
    finally:
        store_reader.close()
        app_db.close()


def test_resetting_your_own_password_keeps_only_the_current_session(
    tmp_path: Path,
) -> None:
    """An admin resets their own password: this session lives, their others end."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        boss = seed_admin(app_db, username="boss", password="boss-password")

        current = build_account_client(settings, app_db, store_reader)
        assert (
            login(current, username="boss", password="boss-password")
        ).status_code == 200
        elsewhere = build_account_client(settings, app_db, store_reader)
        assert (
            login(elsewhere, username="boss", password="boss-password")
        ).status_code == 200

        patched = current.patch(
            f"/api/users/{boss.id}", json={"password": "a-brand-new-password"}
        )
        assert patched.status_code == 200, patched.text

        assert current.get("/api/auth/me").status_code == 200
        assert elsewhere.get("/api/auth/me").status_code == 401
    finally:
        store_reader.close()
        app_db.close()


def test_member_is_denied_an_admin_route(tmp_path: Path) -> None:
    """A Member calling the admin-only GET /api/users gets 403, not 401."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(
            app_db,
            username="member",
            password="member-password",
            role="member",
        )
        client = build_account_client(settings, app_db, store_reader)
        assert (
            login(client, username="member", password="member-password").status_code
            == 200
        )
        response = client.get("/api/users")
        assert response.status_code == 403
    finally:
        store_reader.close()
        app_db.close()


def test_readonly_is_denied_the_reconcile_route(tmp_path: Path) -> None:
    """A Read-only user calling Member-gated POST /api/reconcile gets 403."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(
            app_db,
            username="viewer",
            password="viewer-password",
            role="readonly",
        )
        client = build_account_client(settings, app_db, store_reader)
        assert (
            login(client, username="viewer", password="viewer-password").status_code
            == 200
        )
        response = client.post("/api/reconcile")
        assert response.status_code == 403
    finally:
        store_reader.close()
        app_db.close()


def test_readonly_can_reach_the_readonly_routes(tmp_path: Path) -> None:
    """search/facets/stats require readonly+ — a Read-only user reaches them."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(
            app_db,
            username="viewer",
            password="viewer-password",
            role="readonly",
        )
        client = build_account_client(settings, app_db, store_reader)
        assert (
            login(client, username="viewer", password="viewer-password").status_code
            == 200
        )
        assert client.post("/api/search", json={"query": "gas"}).status_code == 200
        assert client.get("/api/facets").status_code == 200
        assert client.get("/api/stats").status_code == 200
    finally:
        store_reader.close()
        app_db.close()


def test_member_can_reach_the_reconcile_route(tmp_path: Path) -> None:
    """reconcile requires member+ — a Member reaches it (202 Accepted)."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(
            app_db,
            username="member",
            password="member-password",
            role="member",
        )
        client = build_account_client(settings, app_db, store_reader)
        assert (
            login(client, username="member", password="member-password").status_code
            == 200
        )
        assert client.post("/api/reconcile").status_code == 202
    finally:
        store_reader.close()
        app_db.close()


def test_admin_reaches_every_route(tmp_path: Path) -> None:
    """An admin passes the readonly, member and admin gates alike."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_admin(app_db, username="boss", password="boss-password")
        client = build_account_client(settings, app_db, store_reader)
        assert (
            login(client, username="boss", password="boss-password").status_code == 200
        )
        assert client.post("/api/search", json={"query": "gas"}).status_code == 200
        assert client.post("/api/reconcile").status_code == 202
        assert client.get("/api/users").status_code == 200
    finally:
        store_reader.close()
        app_db.close()


def test_an_unauthenticated_request_to_users_is_401(tmp_path: Path) -> None:
    """No credential at all on an admin route is 401, distinct from the 403."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_admin(app_db, username="boss", password="boss-password")
        client = build_account_client(settings, app_db, store_reader)
        # No login.
        assert SESSION_COOKIE_NAME not in client.cookies
        assert client.get("/api/users").status_code == 401
    finally:
        store_reader.close()
        app_db.close()
