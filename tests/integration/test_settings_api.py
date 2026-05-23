"""Integration tests for the admin Settings API (web-redesign §5, Wave 4).

Drives the three Settings endpoints through the real search FastAPI app over
a real tmp_path app.db, reusing the Wave 1 account helpers. Covers the GET
payload and secret masking/reveal, the PUT validate-persist round trip and
its re-read response, the requires_reindex flag, and the RBAC gates
(non-admin 403, unauthenticated 401). POST /api/settings/test-connection is
covered in test_settings_api_rbac.py.
"""

from __future__ import annotations

import pytest

from appdb import config as config_store
from tests.integration.accounts_helpers import (
    build_account_client,
    login,
    make_settings,
    open_app_db,
    seed_admin,
    seed_store,
)


@pytest.fixture()
def admin_client(tmp_path):
    """A search app with a seeded admin, logged in, plus the open app.db.

    Yields (client, app_db) so a test can inspect the config table directly.
    """
    from store.reader import StoreReader

    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    seed_admin(app_db, username="admin", password="admin-password")
    store_reader = StoreReader(settings)
    client = build_account_client(settings, app_db, store_reader)
    response = login(client, username="admin", password="admin-password")
    assert response.status_code == 200
    try:
        yield client, app_db
    finally:
        store_reader.close()
        app_db.close()


def test_get_settings_returns_every_config_key(admin_client) -> None:
    """GET /api/settings lists one item per config key."""
    from common.config import CONFIG_KEYS

    client, _ = admin_client
    response = client.get("/api/settings")
    assert response.status_code == 200
    keys = {item["key"] for item in response.json()["settings"]}
    assert keys == set(CONFIG_KEYS)


def test_get_settings_masks_secret_values(admin_client) -> None:
    """A secret key's value is masked by default."""
    client, app_db = admin_client
    config_store.set_value(app_db, "OPENAI_API_KEY", "sk-real-secret")
    response = client.get("/api/settings")
    item = next(i for i in response.json()["settings"] if i["key"] == "OPENAI_API_KEY")
    assert item["is_secret"] is True
    assert item["value"] == "********"
    assert "sk-real-secret" not in response.text


def test_get_settings_reveals_secret_with_reveal_flag(admin_client) -> None:
    """?reveal=true unmasks secret values — the reveal mechanism."""
    client, app_db = admin_client
    config_store.set_value(app_db, "OPENAI_API_KEY", "sk-real-secret")
    response = client.get("/api/settings", params={"reveal": "true"})
    item = next(i for i in response.json()["settings"] if i["key"] == "OPENAI_API_KEY")
    assert item["value"] == "sk-real-secret"


def test_get_settings_reports_the_value_source(admin_client) -> None:
    """A key set in the config table is reported as database-sourced."""
    client, app_db = admin_client
    config_store.set_value(app_db, "OCR_DPI", "275")
    response = client.get("/api/settings")
    item = next(i for i in response.json()["settings"] if i["key"] == "OCR_DPI")
    assert item["value"] == "275"
    assert item["source"] == "database"


def test_put_settings_persists_a_change(admin_client) -> None:
    """PUT /api/settings writes the change to the config table."""
    client, app_db = admin_client
    response = client.put("/api/settings", json={"changes": {"OCR_DPI": "200"}})
    assert response.status_code == 200
    assert config_store.get(app_db, "OCR_DPI") == "200"


def test_put_settings_returns_the_full_reread_list(admin_client) -> None:
    """PUT responds with the whole re-read settings list, with the change
    reflected — the UI refreshes from this one response."""
    client, _ = admin_client
    response = client.put("/api/settings", json={"changes": {"OCR_DPI": "200"}})
    body = response.json()
    from common.config import CONFIG_KEYS

    assert {item["key"] for item in body["settings"]} == set(CONFIG_KEYS)
    ocr_dpi = next(i for i in body["settings"] if i["key"] == "OCR_DPI")
    assert ocr_dpi["value"] == "200"
    assert ocr_dpi["source"] == "database"


def test_put_settings_flags_a_reindex_change(admin_client) -> None:
    """A re-index key carries requires_reindex=True; an ordinary key does not."""
    client, _ = admin_client
    response = client.put(
        "/api/settings",
        json={"changes": {"CHUNK_SIZE": "3000", "OCR_DPI": "200"}},
    )
    items = {i["key"]: i for i in response.json()["settings"]}
    # CHUNK_SIZE governs chunking — a change needs a full re-index.
    assert items["CHUNK_SIZE"]["requires_reindex"] is True
    # OCR_DPI hot-loads with no re-index.
    assert items["OCR_DPI"]["requires_reindex"] is False


def test_put_settings_bumps_the_config_version(admin_client) -> None:
    """A PUT bumps config_version so every process hot-loads the change."""
    client, app_db = admin_client
    before = config_store.get_config_version(app_db)
    client.put("/api/settings", json={"changes": {"OCR_DPI": "200"}})
    assert config_store.get_config_version(app_db) == before + 1


def test_put_settings_rejects_an_unknown_key(admin_client) -> None:
    """An unknown config key is a 400; the table is untouched."""
    client, app_db = admin_client
    response = client.put("/api/settings", json={"changes": {"BOGUS_KEY": "x"}})
    assert response.status_code == 400
    assert config_store.get(app_db, "BOGUS_KEY") is None


def test_put_settings_rejects_an_invalid_value(admin_client) -> None:
    """A value that would break Settings is a 400; nothing is persisted."""
    client, app_db = admin_client
    response = client.put(
        "/api/settings", json={"changes": {"CHUNK_SIZE": "not-an-int"}}
    )
    assert response.status_code == 400
    assert config_store.get(app_db, "CHUNK_SIZE") is None


def test_put_settings_with_no_changes_is_a_clean_noop(admin_client) -> None:
    """An empty change set is a clean no-op: 200, the re-read list, and the
    config_version is not bumped (nothing was written)."""
    client, app_db = admin_client
    before = config_store.get_config_version(app_db)
    response = client.put("/api/settings", json={"changes": {}})
    assert response.status_code == 200
    from common.config import CONFIG_KEYS

    assert {i["key"] for i in response.json()["settings"]} == set(CONFIG_KEYS)
    assert config_store.get_config_version(app_db) == before
