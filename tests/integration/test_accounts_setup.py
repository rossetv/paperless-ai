"""Integration tests for the first-run setup flow (web-redesign §4.8).

Exercises the real FastAPI app through ``TestClient`` against a real
``tmp_path`` ``app.db`` with no users — the server is in setup mode.

Coverage:
- GET /api/setup/status reports needed=true on a fresh database.
- POST /api/setup with the correct token creates the first admin (201) and
  that user has the admin role and active status.
- POST /api/setup a second time returns 409 — setup is over.
- GET /api/setup/status flips to needed=false once the admin exists.
- POST /api/setup with a wrong token returns 403 and creates nothing.
- The created admin can then log in.
"""

from __future__ import annotations

from pathlib import Path

from store.reader import StoreReader

from tests.integration.accounts_helpers import (
    build_account_client,
    login,
    make_settings,
    open_app_db,
    seed_store,
)


def _setup_token(client) -> str:
    """Return the in-memory setup token the app generated at build time.

    ``create_app`` attaches an ``AppState`` to ``app.state``; its
    ``setup_state.token`` is the one-off token logged to the container in
    production. In a test there are no container logs to scrape, so it is
    read straight off the live app object.
    """
    token = client.app.state.app_state.setup_state.token
    assert token is not None, "expected the app to be in setup mode"
    return token


def test_setup_status_is_needed_on_a_fresh_database(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        response = client.get("/api/setup/status")
        assert response.status_code == 200
        assert response.json() == {"needed": True}
    finally:
        store_reader.close()
        app_db.close()


def test_setup_creates_the_first_admin(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        response = client.post(
            "/api/setup",
            json={
                "token": _setup_token(client),
                "username": "founder",
                "password": "founder-password",
            },
        )
        assert response.status_code == 201, response.text
        user = response.json()["user"]
        assert user["username"] == "founder"
        assert user["role"] == "admin"
        assert user["status"] == "active"
    finally:
        store_reader.close()
        app_db.close()


def test_setup_status_flips_after_setup(tmp_path: Path) -> None:
    """status -> setup -> status: the needed flag flips true then false."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        assert client.get("/api/setup/status").json() == {"needed": True}
        created = client.post(
            "/api/setup",
            json={
                "token": _setup_token(client),
                "username": "founder",
                "password": "founder-password",
            },
        )
        assert created.status_code == 201, created.text
        assert client.get("/api/setup/status").json() == {"needed": False}
    finally:
        store_reader.close()
        app_db.close()


def test_second_setup_call_returns_409(tmp_path: Path) -> None:
    """Once an admin exists, a further POST /api/setup is rejected 409."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        token = _setup_token(client)
        first = client.post(
            "/api/setup",
            json={
                "token": token,
                "username": "founder",
                "password": "founder-password",
            },
        )
        assert first.status_code == 201, first.text
        # The token is single-use; the second call is rejected because a user
        # now exists, regardless of the token value supplied.
        second = client.post(
            "/api/setup",
            json={
                "token": token,
                "username": "intruder",
                "password": "intruder-password",
            },
        )
        assert second.status_code == 409
    finally:
        store_reader.close()
        app_db.close()


def test_setup_with_a_wrong_token_returns_403(tmp_path: Path) -> None:
    """A bad setup token is rejected 403 and no user is created."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        response = client.post(
            "/api/setup",
            json={
                "token": "definitely-not-the-real-token",
                "username": "founder",
                "password": "founder-password",
            },
        )
        assert response.status_code == 403
        # Setup is still needed — nothing was created.
        assert client.get("/api/setup/status").json() == {"needed": True}
    finally:
        store_reader.close()
        app_db.close()


def test_created_admin_can_log_in(tmp_path: Path) -> None:
    """The admin created by setup can immediately authenticate."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        created = client.post(
            "/api/setup",
            json={
                "token": _setup_token(client),
                "username": "founder",
                "password": "founder-password",
            },
        )
        assert created.status_code == 201, created.text
        response = login(client, username="founder", password="founder-password")
        assert response.status_code == 200, response.text
        assert response.json()["user"]["username"] == "founder"
    finally:
        store_reader.close()
        app_db.close()


def test_concurrent_setup_requests_produce_exactly_one_admin(
    tmp_path: Path,
) -> None:
    """Two concurrent POST /api/setup calls must not create two admin accounts.

    ``user_store.create_initial_admin`` uses a single
    ``INSERT … SELECT … WHERE NOT EXISTS`` statement that SQLite evaluates
    atomically under its write lock: the second concurrent caller sees a
    non-empty table inside the same statement and inserts zero rows, causing
    ``_setup`` to return 409. This test simulates the race with threads —
    one must succeed (201) and the other must fail (409); exactly one user
    row must exist afterwards.
    """
    import threading

    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        token = _setup_token(client)
        results: list[int] = []
        lock = threading.Lock()

        def attempt(username: str) -> None:
            # Password must be at least 8 characters (_PASSWORD_MIN in
            # search.validation); the plan used "pw" which is too short and
            # would yield 422 before reaching any race-condition logic.
            r = client.post(
                "/api/setup",
                json={
                    "token": token,
                    "username": username,
                    "password": "password-ok",
                },
            )
            with lock:
                results.append(r.status_code)

        t1 = threading.Thread(target=attempt, args=("admin-a",))
        t2 = threading.Thread(target=attempt, args=("admin-b",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert sorted(results) == [201, 409], (
            f"expected one 201 and one 409, got {results}"
        )
        # Exactly one user row was created.
        (count,) = app_db.execute("SELECT COUNT(*) FROM users").fetchone()
        assert count == 1
    finally:
        store_reader.close()
        app_db.close()
