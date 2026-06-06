"""Tests for the Settings wire models in search.wire.

Covers: the SettingItemResponse shape including requires_reindex; SettingsResponse
wraps the item list (and is the PUT response too); UpdateSettingsRequest accepts
a changes mapping and rejects a non-string value; the test-connection models.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from search.wire import (
    SettingItemResponse,
    SettingsResponse,
    TestConnectionRequest,
    TestConnectionResponse,
    UpdateSettingsRequest,
)


def test_setting_item_response_carries_its_fields() -> None:
    item = SettingItemResponse(
        key="CHUNK_SIZE",
        value="2000",
        source="database",
        is_secret=False,
        requires_reindex=True,
    )
    assert item.key == "CHUNK_SIZE"
    assert item.requires_reindex is True


def test_setting_item_response_accepts_a_null_value() -> None:
    """A key on its coded default has a null value."""
    item = SettingItemResponse(
        key="OCR_DPI",
        value=None,
        source="default",
        is_secret=False,
        requires_reindex=False,
    )
    assert item.value is None


def test_setting_item_response_carries_default_value() -> None:
    """default_value surfaces the coded default for a key on its default."""
    item = SettingItemResponse(
        key="OCR_DPI",
        value=None,
        source="default",
        is_secret=False,
        requires_reindex=False,
        default_value="300",
    )
    assert item.default_value == "300"


def test_setting_item_response_default_value_is_none_when_absent() -> None:
    """default_value defaults to None when not supplied (secrets, env-only keys)."""
    item = SettingItemResponse(
        key="CHUNK_SIZE",
        value="2000",
        source="database",
        is_secret=False,
        requires_reindex=True,
    )
    assert item.default_value is None


def test_settings_response_wraps_a_list_of_items() -> None:
    response = SettingsResponse(
        settings=[
            SettingItemResponse(
                key="OCR_DPI",
                value="300",
                source="default",
                is_secret=False,
                requires_reindex=False,
            )
        ]
    )
    assert len(response.settings) == 1


def test_update_settings_request_accepts_a_changes_mapping() -> None:
    body = UpdateSettingsRequest(changes={"OCR_DPI": "200", "LOG_LEVEL": "DEBUG"})
    assert body.changes["OCR_DPI"] == "200"


def test_update_settings_request_accepts_an_empty_mapping() -> None:
    body = UpdateSettingsRequest(changes={})
    assert body.changes == {}


def test_update_settings_request_rejects_a_non_string_value() -> None:
    """Config values are always strings on the wire — an int is rejected."""
    with pytest.raises(ValidationError):
        UpdateSettingsRequest(changes={"OCR_DPI": 200})


def test_test_connection_request_carries_the_probe_credentials() -> None:
    body = TestConnectionRequest(
        paperless_url="http://paperless:8000", paperless_token="tok"
    )
    assert body.paperless_url == "http://paperless:8000"
    assert body.paperless_token == "tok"


def test_test_connection_request_accepts_an_empty_token() -> None:
    """An empty token means 'probe with the stored secret' — the masked-token
    path the Settings screen uses when the user has not replaced the token."""
    body = TestConnectionRequest(paperless_url="http://x", paperless_token="")
    assert body.paperless_token == ""


def test_test_connection_response_carries_outcome() -> None:
    ok = TestConnectionResponse(ok=True, document_count=14238, detail="Connected.")
    bad = TestConnectionResponse(ok=False, document_count=0, detail="401 Unauthorized")
    assert ok.ok is True
    assert ok.document_count == 14238
    assert bad.ok is False
