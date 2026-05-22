"""Integration tests for legacy-bearer auth and the SPA catch-all (§4.8).

Two concerns, both exercised through the real FastAPI app:

- The legacy ``Authorization: Bearer <SEARCH_API_KEY>`` credential still
  authorises ``/api/*`` as an admin-equivalent caller (Waves 1-2).
- The SPA deep-link catch-all serves ``index.html`` for client-router paths
  such as ``/login`` and ``/setup`` so a hard refresh resolves.

``search.api`` resolves ``FRONTEND_DIST`` at *import* time, so the SPA tests
set the env var, build the app in a child process-free way by reloading the
module, and restore the environment afterwards.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

from fastapi.testclient import TestClient
from store.reader import StoreReader

from tests.integration.accounts_helpers import (
    LEGACY_API_KEY,
    build_account_client,
    make_mock_core,
    make_settings,
    open_app_db,
    seed_store,
)


def _bearer() -> dict[str, str]:
    """The legacy SEARCH_API_KEY presented as a Bearer header."""
    return {"Authorization": f"Bearer {LEGACY_API_KEY}"}


# ---------------------------------------------------------------------------
# Legacy bearer — admin-equivalent through Waves 1-2
# ---------------------------------------------------------------------------


def test_legacy_bearer_authorises_search(tmp_path: Path) -> None:
    """A request carrying the legacy key as a Bearer reaches POST /api/search."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        response = client.post(
            "/api/search", json={"query": "gas bill"}, headers=_bearer()
        )
        assert response.status_code == 200, response.text
    finally:
        store_reader.close()
        app_db.close()


def test_legacy_bearer_authorises_an_admin_route(tmp_path: Path) -> None:
    """The legacy key is admin-equivalent — it reaches GET /api/users."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        response = client.get("/api/users", headers=_bearer())
        assert response.status_code == 200, response.text
    finally:
        store_reader.close()
        app_db.close()


def test_legacy_bearer_authorises_reconcile(tmp_path: Path) -> None:
    """The legacy key reaches the Member-gated POST /api/reconcile."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        response = client.post("/api/reconcile", headers=_bearer())
        assert response.status_code == 202
    finally:
        store_reader.close()
        app_db.close()


def test_legacy_bearer_works_in_setup_mode(tmp_path: Path) -> None:
    """With no users yet, the legacy bearer still authorises a protected route.

    The legacy path does not depend on a user row, so it works even before
    the first admin is created.
    """
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)  # no users -> setup mode
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        assert client.get("/api/setup/status").json() == {"needed": True}
        response = client.post(
            "/api/search", json={"query": "anything"}, headers=_bearer()
        )
        assert response.status_code == 200, response.text
    finally:
        store_reader.close()
        app_db.close()


def test_auth_me_reports_the_legacy_identity(tmp_path: Path) -> None:
    """GET /api/auth/me on the legacy bearer returns the synthetic admin."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        response = client.get("/api/auth/me", headers=_bearer())
        assert response.status_code == 200, response.text
        user = response.json()["user"]
        assert user["role"] == "admin"
        assert user["id"] == 0
    finally:
        store_reader.close()
        app_db.close()


def test_a_wrong_bearer_is_rejected_401(tmp_path: Path) -> None:
    """A Bearer token that is not the legacy key does not authorise."""
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    try:
        client = build_account_client(settings, app_db, store_reader)
        response = client.post(
            "/api/search",
            json={"query": "gas"},
            headers={"Authorization": "Bearer not-the-real-key"},
        )
        assert response.status_code == 401
    finally:
        store_reader.close()
        app_db.close()


# ---------------------------------------------------------------------------
# SPA deep-link catch-all
# ---------------------------------------------------------------------------


def _build_spa_client(tmp_path: Path) -> TestClient:
    """Build the real app with a populated ``web/dist`` set via FRONTEND_DIST.

    ``search.api`` reads ``FRONTEND_DIST`` at import time, so the env var is
    set and the module reloaded before ``create_app`` is called. The caller
    restores the environment in a ``finally`` block.
    """
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<!doctype html><html><body><div id=root></div></body></html>"
    )
    assets = dist / "assets"
    assets.mkdir()
    (assets / "app-abcd1234.js").write_text("console.log('paperless-ai');")

    os.environ["FRONTEND_DIST"] = str(dist)
    import search.api as search_api

    importlib.reload(search_api)

    settings = make_settings(tmp_path)
    seed_store(settings)
    # Migrate the app.db at settings.APP_DB_PATH so the app starts cleanly; the
    # connection is closed at once — the app opens its own per request, and the
    # SPA tests do not inspect app.db directly.
    open_app_db(tmp_path).close()
    store_reader = StoreReader(settings)
    app = search_api.create_app(
        settings,
        core=make_mock_core(),
        store_reader=store_reader,
    )
    return TestClient(app, raise_server_exceptions=False)


def _restore_frontend_dist() -> None:
    """Unset FRONTEND_DIST and reload ``search.api`` to its default state."""
    os.environ.pop("FRONTEND_DIST", None)
    import search.api as search_api

    importlib.reload(search_api)


def test_spa_serves_index_at_root(tmp_path: Path) -> None:
    try:
        client = _build_spa_client(tmp_path)
        response = client.get("/")
        assert response.status_code == 200
        assert "id=root" in response.text
    finally:
        _restore_frontend_dist()


def test_spa_serves_index_for_a_login_deep_link(tmp_path: Path) -> None:
    """A hard refresh of /login serves index.html so React Router resolves it."""
    try:
        client = _build_spa_client(tmp_path)
        response = client.get("/login")
        assert response.status_code == 200
        assert "id=root" in response.text
    finally:
        _restore_frontend_dist()


def test_spa_serves_index_for_a_setup_deep_link(tmp_path: Path) -> None:
    """A hard refresh of /setup serves index.html."""
    try:
        client = _build_spa_client(tmp_path)
        response = client.get("/setup")
        assert response.status_code == 200
        assert "id=root" in response.text
    finally:
        _restore_frontend_dist()


def test_spa_serves_a_real_asset_as_itself(tmp_path: Path) -> None:
    """A real built asset is served as itself, not replaced by index.html."""
    try:
        client = _build_spa_client(tmp_path)
        response = client.get("/assets/app-abcd1234.js")
        assert response.status_code == 200
        assert "console.log" in response.text
    finally:
        _restore_frontend_dist()


def test_spa_does_not_swallow_an_api_route(tmp_path: Path) -> None:
    """An /api route still resolves to its handler, not to index.html."""
    try:
        client = _build_spa_client(tmp_path)
        # The public setup-status route resolves to JSON, not the SPA shell.
        response = client.get("/api/setup/status")
        assert response.status_code == 200
        assert "id=root" not in response.text
        assert response.json() == {"needed": True}
    finally:
        _restore_frontend_dist()


def test_spa_does_not_mask_an_unknown_api_path(tmp_path: Path) -> None:
    """An unknown /api path 404s — it must not fall through to the SPA shell."""
    try:
        client = _build_spa_client(tmp_path)
        response = client.get("/api/does-not-exist")
        assert response.status_code == 404
        assert "id=root" not in response.text
    finally:
        _restore_frontend_dist()
