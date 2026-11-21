"""Integration tests for the first-run setup flow against an empty app.db."""

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
    """Return the one-off setup token, which production only writes to the logs."""
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

    ``create_initial_admin`` is a single ``INSERT … WHERE NOT EXISTS`` that
    SQLite runs atomically, so one call gets 201 and the other 409.
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
            # A password under 12 characters would 422 before reaching the race.
            r = client.post(
                "/api/setup",
                json={
                    "token": token,
                    "username": username,
                    "password": "password-okay",
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
