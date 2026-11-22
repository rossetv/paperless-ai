"""Integration tests for the login, session and logout journey against a real app.db."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from store.reader import StoreReader

from search.auth import SESSION_COOKIE_NAME
from tests.integration.accounts_helpers import (
    build_account_client,
    login,
    make_settings,
    open_app_db,
    seed_store,
    seed_user,
)


def _set_cookie_header(response) -> str:
    """Return the single ``set-cookie`` header value from *response*."""
    headers = [value for key, value in response.headers.raw if key == b"set-cookie"]
    assert len(headers) == 1, headers
    return headers[0].decode("latin-1")


def test_login_returns_the_user_and_sets_the_cookie(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="member")
        client = build_account_client(settings, app_db, store_reader)
        response = login(client, username="alice", password="alice-password")
        assert response.status_code == 200, response.text
        assert response.json()["user"]["username"] == "alice"
        assert response.json()["user"]["role"] == "member"
        assert SESSION_COOKIE_NAME in response.cookies
    finally:
        store_reader.close()
        app_db.close()


def test_session_cookie_authorises_a_protected_route(tmp_path: Path) -> None:
    """After login the cookie alone authorises POST /api/search."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="member")
        client = build_account_client(settings, app_db, store_reader)
        assert (
            login(client, username="alice", password="alice-password").status_code
            == 200
        )
        # No Authorization header — the cookie in the jar is the only credential.
        response = client.post("/api/search", json={"query": "gas bill"})
        assert response.status_code == 200, response.text
    finally:
        store_reader.close()
        app_db.close()


def test_auth_me_returns_the_logged_in_user(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="member")
        client = build_account_client(settings, app_db, store_reader)
        assert (
            login(client, username="alice", password="alice-password").status_code
            == 200
        )
        response = client.get("/api/auth/me")
        assert response.status_code == 200, response.text
        user = response.json()["user"]
        assert user["username"] == "alice"
        assert user["role"] == "member"
        # The hash must never cross the HTTP boundary.
        assert "password_hash" not in user
    finally:
        store_reader.close()
        app_db.close()


def test_auth_me_401_without_a_cookie(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password")
        client = build_account_client(settings, app_db, store_reader)
        # No login — no cookie.
        assert client.get("/api/auth/me").status_code == 401
    finally:
        store_reader.close()
        app_db.close()


def test_logout_destroys_the_session(tmp_path: Path) -> None:
    """After logout the previously valid cookie no longer authorises."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="member")
        client = build_account_client(settings, app_db, store_reader)
        assert (
            login(client, username="alice", password="alice-password").status_code
            == 200
        )
        logout = client.post("/api/auth/logout")
        assert logout.status_code == 204
        # The session row is gone — /api/auth/me is now unauthenticated even
        # if a stale cookie were replayed.
        assert client.get("/api/auth/me").status_code == 401
    finally:
        store_reader.close()
        app_db.close()


def test_logout_revokes_a_replayed_cookie(tmp_path: Path) -> None:
    """A token captured before logout cannot be replayed afterwards.

    ``client.post('/api/auth/logout')`` also clears the client's own cookie
    jar; this test re-sets the captured token by hand to prove the *server*
    revoked it, not merely the browser.
    """
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="member")
        client = build_account_client(settings, app_db, store_reader)
        assert (
            login(client, username="alice", password="alice-password").status_code
            == 200
        )
        captured = client.cookies.get(SESSION_COOKIE_NAME)
        assert captured is not None
        assert client.post("/api/auth/logout").status_code == 204
        # Replay the captured token explicitly.
        client.cookies.set(SESSION_COOKIE_NAME, captured)
        assert client.get("/api/auth/me").status_code == 401
    finally:
        store_reader.close()
        app_db.close()


def test_login_with_a_wrong_password_returns_401(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password")
        client = build_account_client(settings, app_db, store_reader)
        response = login(client, username="alice", password="the-wrong-password")
        assert response.status_code == 401
        assert SESSION_COOKIE_NAME not in response.cookies
    finally:
        store_reader.close()
        app_db.close()


def test_login_with_an_unknown_username_returns_401(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password")
        client = build_account_client(settings, app_db, store_reader)
        response = login(client, username="nobody", password="any-password")
        assert response.status_code == 401
    finally:
        store_reader.close()
        app_db.close()


def test_login_for_a_suspended_account_returns_403(tmp_path: Path) -> None:
    """A suspended user with the correct password is rejected 403, not 401."""
    from appdb.users import update as update_user

    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        user = seed_user(
            app_db, username="alice", password="alice-password", role="member"
        )
        update_user(app_db, user.id, status="suspended")
        client = build_account_client(settings, app_db, store_reader)
        response = login(client, username="alice", password="alice-password")
        assert response.status_code == 403
        assert SESSION_COOKIE_NAME not in response.cookies
    finally:
        store_reader.close()
        app_db.close()


def test_repeated_failures_lock_the_login_with_429(tmp_path: Path) -> None:
    """A burst of wrong passwords locks the (IP, username) with 429."""
    from search.login_throttle import _MAX_FAILURES_BEFORE_LOCKOUT

    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="member")
        client = build_account_client(settings, app_db, store_reader)

        # Exhaust the failure budget — each one is a plain 401.
        for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT):
            assert (
                login(client, username="alice", password="wrong-password").status_code
                == 401
            )

        # The next attempt is denied before the password is even checked.
        blocked = login(client, username="alice", password="wrong-password")
        assert blocked.status_code == 429
        assert SESSION_COOKIE_NAME not in blocked.cookies
        assert 1 <= int(blocked.headers["Retry-After"]) <= 900
    finally:
        store_reader.close()
        app_db.close()


def test_concurrent_wrong_passwords_beyond_the_limit_get_429(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Logins still being checked count, so only the limit's worth get a 401."""
    from search import account_routes
    from search.login_throttle import _MAX_FAILURES_BEFORE_LOCKOUT

    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    gate = threading.Event()
    # Released when a request reaches the password check or returns, so requests are sent one at a time.
    progress = threading.Semaphore(0)

    def held_authenticate(*_args: object) -> None:
        progress.release()
        gate.wait(timeout=10)

    monkeypatch.setattr(account_routes, "authenticate", held_authenticate)
    attempts = _MAX_FAILURES_BEFORE_LOCKOUT + 3
    try:
        client = build_account_client(settings, app_db, store_reader)
        with ThreadPoolExecutor(max_workers=attempts) as pool:
            futures = []
            for _ in range(attempts):
                future = pool.submit(
                    login, client, username="alice", password="wrong-password"
                )
                future.add_done_callback(lambda _f: progress.release())
                assert progress.acquire(timeout=10)
                futures.append(future)
            gate.set()
            codes = sorted(f.result().status_code for f in futures)
        assert codes == [401] * _MAX_FAILURES_BEFORE_LOCKOUT + [429] * 3
    finally:
        gate.set()
        store_reader.close()
        app_db.close()


def test_a_login_that_errors_does_not_count_toward_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server error while checking the password leaves the throttle untouched."""
    from search import account_routes
    from search.login_throttle import _MAX_FAILURES_BEFORE_LOCKOUT

    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="member")
        client = build_account_client(settings, app_db, store_reader)
        real_authenticate = account_routes.authenticate

        def failing_authenticate(*_args: object) -> None:
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(account_routes, "authenticate", failing_authenticate)
        for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT):
            assert (
                login(client, username="alice", password="alice-password").status_code
                == 500
            )

        monkeypatch.setattr(account_routes, "authenticate", real_authenticate)
        ok = login(client, username="alice", password="alice-password")
        assert ok.status_code == 200, ok.text
    finally:
        store_reader.close()
        app_db.close()


def test_a_correct_password_after_failures_is_not_throttled(tmp_path: Path) -> None:
    """Failures short of the lockout do not block a subsequent valid login."""
    from search.login_throttle import _MAX_FAILURES_BEFORE_LOCKOUT

    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="member")
        client = build_account_client(settings, app_db, store_reader)

        # One short of the lockout, then the right password.
        for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT - 1):
            assert (
                login(client, username="alice", password="wrong-password").status_code
                == 401
            )
        ok = login(client, username="alice", password="alice-password")
        assert ok.status_code == 200, ok.text
        assert SESSION_COOKIE_NAME in ok.cookies
    finally:
        store_reader.close()
        app_db.close()


def test_a_success_resets_the_failure_counter(tmp_path: Path) -> None:
    """A successful login clears the counter, so later typos start fresh."""
    from search.login_throttle import _MAX_FAILURES_BEFORE_LOCKOUT

    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password", role="member")
        client = build_account_client(settings, app_db, store_reader)

        for _ in range(_MAX_FAILURES_BEFORE_LOCKOUT - 1):
            assert (
                login(client, username="alice", password="wrong-password").status_code
                == 401
            )
        assert (
            login(client, username="alice", password="alice-password").status_code
            == 200
        )

        # After the reset a single further failure is still just a 401, not a
        # lockout — the earlier near-miss burst was cleared.
        assert (
            login(client, username="alice", password="wrong-password").status_code
            == 401
        )
    finally:
        store_reader.close()
        app_db.close()


def test_remember_login_honours_configured_session_ttl(tmp_path: Path) -> None:
    """remember=True -> Max-Age is the configured SEARCH_SESSION_TTL."""
    settings = make_settings(tmp_path, SEARCH_SESSION_TTL=4242)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password")
        client = build_account_client(settings, app_db, store_reader)
        response = login(
            client,
            username="alice",
            password="alice-password",
            remember=True,
        )
        assert response.status_code == 200, response.text
        assert "Max-Age=4242" in _set_cookie_header(response)
    finally:
        store_reader.close()
        app_db.close()


def test_non_remember_login_sets_an_eight_hour_cookie(tmp_path: Path) -> None:
    """remember=False -> Max-Age 28800 (8 hours)."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="alice-password")
        client = build_account_client(settings, app_db, store_reader)
        response = login(
            client,
            username="alice",
            password="alice-password",
            remember=False,
        )
        assert response.status_code == 200, response.text
        assert "Max-Age=28800" in _set_cookie_header(response)
    finally:
        store_reader.close()
        app_db.close()


def test_login_accepts_a_password_shorter_than_the_creation_minimum(
    tmp_path: Path,
) -> None:
    """An account made when the floor was lower can still sign in."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        seed_user(app_db, username="alice", password="ninechars", role="member")
        client = build_account_client(settings, app_db, store_reader)
        assert login(client, username="alice", password="ninechars").status_code == 200
        assert login(client, username="alice", password="").status_code == 422
        wrong = login(client, username="alice", password="wrongpw9c")
        assert wrong.status_code == 401
    finally:
        store_reader.close()
        app_db.close()
