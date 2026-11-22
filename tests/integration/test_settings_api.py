"""Integration tests for GET and PUT /api/settings over a real app.db.

Role gates and test-connection are covered in test_settings_api_rbac.py.
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
    """Yield ``(client, app_db)`` for a logged-in admin."""
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
    """PUT responds with the whole re-read settings list, change included."""
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


def test_put_settings_changing_a_reindex_key_forces_a_rebuild(
    admin_client, tmp_path
) -> None:
    """Saving a re-index key (CHUNK_SIZE) forces a full rebuild.

    New chunking makes the existing vectors stale, so the save drops the
    rebuild.request and reconcile.request sentinels and flags reindex_triggered.
    """
    client, _ = admin_client
    response = client.put("/api/settings", json={"changes": {"CHUNK_SIZE": "1000"}})
    assert response.status_code == 200
    assert response.json()["reindex_triggered"] is True
    # The sentinels land beside index.db — make_settings puts it at tmp_path.
    assert (tmp_path / "rebuild.request").exists()
    assert (tmp_path / "reconcile.request").exists()


def test_put_settings_changing_the_embedding_model_forces_a_rebuild(
    admin_client, tmp_path
) -> None:
    """Switching EMBEDDING_MODEL forces a rebuild so old and new vectors never mix."""
    client, _ = admin_client
    response = client.put(
        "/api/settings",
        json={"changes": {"EMBEDDING_MODEL": "text-embedding-3-large"}},
    )
    assert response.status_code == 200
    assert response.json()["reindex_triggered"] is True
    assert (tmp_path / "rebuild.request").exists()


def test_put_settings_refuses_when_rebuild_sentinel_write_fails(
    admin_client, tmp_path
) -> None:
    """A re-index save whose rebuild cannot be scheduled does not persist.

    The sentinel is written before the config commits; otherwise a new
    EMBEDDING_MODEL could hot-load over old-width vectors and every search 500.
    """
    from unittest.mock import patch

    client, app_db = admin_client
    before_version = config_store.get_config_version(app_db)

    with patch(
        "search.settings_routes.request_index_rebuild",
        side_effect=OSError("data dir is read-only"),
    ):
        response = client.put(
            "/api/settings",
            json={"changes": {"EMBEDDING_MODEL": "text-embedding-3-large"}},
        )

    # The save is refused with a 5xx — nothing persisted.
    assert response.status_code >= 500
    # The new model was not written: a present-but-unwiped index of the old
    # width would otherwise make every vector search raise.
    assert config_store.get(app_db, "EMBEDDING_MODEL") is None
    # config_version did not move, so no process hot-loads a half-applied change.
    assert config_store.get_config_version(app_db) == before_version
    # No sentinel was left behind on the failing path.
    assert not (tmp_path / "rebuild.request").exists()


def test_put_settings_changing_an_ordinary_key_does_not_rebuild(
    admin_client, tmp_path
) -> None:
    """An ordinary key (OCR_DPI) hot-loads with no rebuild: no flag, no sentinel."""
    client, _ = admin_client
    response = client.put("/api/settings", json={"changes": {"OCR_DPI": "200"}})
    assert response.status_code == 200
    assert response.json()["reindex_triggered"] is False
    assert not (tmp_path / "rebuild.request").exists()


def test_put_settings_no_change_does_not_rebuild(admin_client, tmp_path) -> None:
    """An empty change set triggers no rebuild — nothing changed."""
    client, _ = admin_client
    response = client.put("/api/settings", json={"changes": {}})
    assert response.status_code == 200
    assert response.json()["reindex_triggered"] is False
    assert not (tmp_path / "rebuild.request").exists()


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


def test_put_settings_rejects_out_of_order_relevance_tiers(admin_client) -> None:
    """A partial cut-point above the good cut-point breaks the badge ordering
    invariant: 400, the message names the constraint, and nothing is persisted."""
    client, app_db = admin_client
    response = client.put(
        "/api/settings",
        json={"changes": {"SEARCH_RELEVANCE_TIER_PARTIAL": "0.95"}},
    )
    assert response.status_code == 400
    assert "Relevance tiers must be ordered" in response.json()["detail"]
    assert config_store.get(app_db, "SEARCH_RELEVANCE_TIER_PARTIAL") is None


def test_put_settings_persists_a_valid_relevance_tier(admin_client) -> None:
    """A valid tier change writes through and hot-loads like any config key."""
    client, app_db = admin_client
    response = client.put(
        "/api/settings",
        json={"changes": {"SEARCH_RELEVANCE_TIER_STRONG": "0.8"}},
    )
    assert response.status_code == 200
    assert config_store.get(app_db, "SEARCH_RELEVANCE_TIER_STRONG") == "0.8"


def test_put_settings_with_no_changes_is_a_clean_noop(admin_client) -> None:
    """An empty change set returns 200 and the list without bumping config_version."""
    client, app_db = admin_client
    before = config_store.get_config_version(app_db)
    response = client.put("/api/settings", json={"changes": {}})
    assert response.status_code == 200
    from common.config import CONFIG_KEYS

    assert {i["key"] for i in response.json()["settings"]} == set(CONFIG_KEYS)
    assert config_store.get_config_version(app_db) == before


def test_put_settings_rejects_the_masked_placeholder_as_a_secret_value(
    admin_client,
) -> None:
    """The mask must never round-trip as a real secret.

    The frontend omits an unchanged secret, but a buggy or hostile client could
    send the placeholder and persist it as the actual token.
    """
    client, app_db = admin_client
    # Pre-seed a real token so the assertion that nothing is overwritten is
    # against a known starting state.
    config_store.set_value(app_db, "PAPERLESS_TOKEN", "real-token")
    response = client.put(
        "/api/settings", json={"changes": {"PAPERLESS_TOKEN": "********"}}
    )
    assert response.status_code == 400
    assert config_store.get(app_db, "PAPERLESS_TOKEN") == "real-token"


def test_put_settings_rejects_an_empty_secret_value(admin_client) -> None:
    """An admin saving `PAPERLESS_TOKEN=""` must fail validation.

    An empty required secret would make every daemon authenticate with "".
    """
    client, app_db = admin_client
    config_store.set_value(app_db, "PAPERLESS_TOKEN", "real-token")
    response = client.put("/api/settings", json={"changes": {"PAPERLESS_TOKEN": ""}})
    assert response.status_code == 400
    assert config_store.get(app_db, "PAPERLESS_TOKEN") == "real-token"


def test_put_settings_rejects_a_changes_mapping_above_the_size_cap(
    admin_client,
) -> None:
    """A change set with more keys than the cap is rejected 422 (DoS guard)."""
    client, _ = admin_client
    # 101 keys; the cap is 100.
    response = client.put(
        "/api/settings",
        json={"changes": {f"BOGUS_{i}": "x" for i in range(101)}},
    )
    assert response.status_code == 422


def test_put_settings_rejects_an_oversize_value(admin_client) -> None:
    """A single value above the 8K cap is rejected before it reaches SQLite."""
    client, _ = admin_client
    response = client.put(
        "/api/settings",
        json={"changes": {"OCR_DPI": "x" * 9000}},
    )
    assert response.status_code == 422


def test_get_settings_audit_logs_a_successful_reveal(admin_client) -> None:
    """`?reveal=true` logs a `search.settings_revealed` event with actor and keys.

    The values are never logged; the trail attributes a later leak to one admin.
    """
    from unittest.mock import patch

    client, app_db = admin_client
    config_store.set_value(app_db, "OPENAI_API_KEY", "sk-real-secret")

    # caplog does not reliably capture structlog, so spy on the module logger.
    with patch("search.settings_routes.log") as mock_log:
        response = client.get("/api/settings", params={"reveal": "true"})
        assert response.status_code == 200

    # Exactly one search.settings_revealed event, carrying the admin's
    # username and the *keys* (not values) of the revealed secrets.
    warning_calls = [
        call
        for call in mock_log.warning.call_args_list
        if call.args and call.args[0] == "search.settings_revealed"
    ]
    assert warning_calls, (
        "a successful ?reveal=true call must emit a search.settings_revealed "
        "audit event"
    )
    kwargs = warning_calls[0].kwargs
    assert kwargs.get("username") == "admin"
    assert "OPENAI_API_KEY" in kwargs.get("keys", [])
    # The value itself is never logged — only the key list.
    for call in warning_calls:
        assert "sk-real-secret" not in repr(call)


def test_get_settings_without_reveal_does_not_audit(admin_client) -> None:
    """A normal (masked) GET emits no reveal audit event."""
    from unittest.mock import patch

    client, app_db = admin_client
    config_store.set_value(app_db, "OPENAI_API_KEY", "sk-real-secret")

    with patch("search.settings_routes.log") as mock_log:
        response = client.get("/api/settings")
        assert response.status_code == 200

    assert not any(
        call.args and call.args[0] == "search.settings_revealed"
        for call in mock_log.warning.call_args_list
    )


def test_get_settings_carries_coded_default_for_default_sourced_key(
    admin_client,
) -> None:
    """A key on its coded default reports that default in ``default_value``.

    The Settings screen shows it instead of an empty value.
    """
    client, _ = admin_client
    response = client.get("/api/settings")
    assert response.status_code == 200
    items = {i["key"]: i for i in response.json()["settings"]}
    # OCR_DPI is not set anywhere — it sits on the coded default of 300.
    dpi = items["OCR_DPI"]
    assert dpi["source"] == "default"
    assert dpi["value"] is None
    assert dpi["default_value"] == "300"
    # CHUNK_SIZE coded default is 2000.
    cs = items["CHUNK_SIZE"]
    assert cs["default_value"] == "2000"


def test_get_settings_secret_keys_have_null_default_value(admin_client) -> None:
    """Secret keys never expose a default_value — it must be null."""
    client, _ = admin_client
    response = client.get("/api/settings")
    items = {i["key"]: i for i in response.json()["settings"]}
    assert items["OPENAI_API_KEY"]["default_value"] is None
    assert items["PAPERLESS_TOKEN"]["default_value"] is None


def test_put_settings_rejects_a_session_lifetime_above_ten_years(admin_client) -> None:
    client, app_db = admin_client
    response = client.put(
        "/api/settings", json={"changes": {"SEARCH_SESSION_TTL": "315360001"}}
    )
    assert response.status_code == 400
    assert config_store.get(app_db, "SEARCH_SESSION_TTL") is None
