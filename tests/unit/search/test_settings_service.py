"""Tests for search.settings_service — read/diff/re-index-impact logic.

Covers: effective-value resolution with the correct source label; secret
flagging; validate_change_set rejects unknown keys and values that break
Settings; reindex_required is true exactly when a re-index key changed; an
empty change set needs no re-index.
"""

from __future__ import annotations

import pytest

from search.settings_service import (
    SettingView,
    reindex_required,
    validate_change_set,
    view_settings,
)


def test_view_reports_a_database_value_as_database_sourced() -> None:
    views = view_settings(
        config_table={"OCR_DPI": "175"}, environ={"OCR_DPI": "150"}
    )
    by_key = {v.key: v for v in views}
    assert by_key["OCR_DPI"].effective_value == "175"
    assert by_key["OCR_DPI"].source == "database"


def test_view_reports_an_environment_value_when_not_in_the_table() -> None:
    views = view_settings(config_table={}, environ={"OCR_DPI": "150"})
    by_key = {v.key: v for v in views}
    assert by_key["OCR_DPI"].effective_value == "150"
    assert by_key["OCR_DPI"].source == "environment"


def test_view_reports_a_default_when_neither_set() -> None:
    views = view_settings(config_table={}, environ={})
    by_key = {v.key: v for v in views}
    # OCR_DPI is not set anywhere — it falls to the coded default.
    assert by_key["OCR_DPI"].source == "default"


def test_view_flags_secret_keys() -> None:
    views = view_settings(config_table={}, environ={})
    by_key = {v.key: v for v in views}
    assert by_key["OPENAI_API_KEY"].is_secret is True
    assert by_key["PAPERLESS_TOKEN"].is_secret is True
    assert by_key["OCR_DPI"].is_secret is False


def test_view_covers_every_config_key() -> None:
    """view_settings returns one SettingView per config key, no more."""
    from common.config import CONFIG_KEYS

    views = view_settings(config_table={}, environ={})
    assert {v.key for v in views} == set(CONFIG_KEYS)
    assert all(isinstance(v, SettingView) for v in views)


def test_validate_rejects_an_unknown_key() -> None:
    with pytest.raises(ValueError, match="unknown configuration key"):
        validate_change_set(
            changes={"NOT_A_REAL_KEY": "x"},
            config_table={},
            environ={
                "PAPERLESS_TOKEN": "t", "OPENAI_API_KEY": "k",
            },
        )


def test_validate_rejects_a_value_that_breaks_settings() -> None:
    """A change that makes Settings invalid is rejected before it is written."""
    with pytest.raises(ValueError, match="CHUNK_SIZE"):
        validate_change_set(
            changes={"CHUNK_SIZE": "not-an-int"},
            config_table={},
            environ={"PAPERLESS_TOKEN": "t", "OPENAI_API_KEY": "k"},
        )


def test_validate_accepts_a_good_change_set() -> None:
    """A valid change set passes and returns the keys that actually changed."""
    changed = validate_change_set(
        changes={"OCR_DPI": "200", "CHUNK_SIZE": "3000"},
        config_table={"OCR_DPI": "200"},  # OCR_DPI is unchanged
        environ={"PAPERLESS_TOKEN": "t", "OPENAI_API_KEY": "k"},
    )
    # OCR_DPI was already 200 in the table — only CHUNK_SIZE changed.
    assert changed == {"CHUNK_SIZE"}


def test_reindex_required_is_true_when_a_reindex_key_changed() -> None:
    # CHUNK_SIZE is a re-index key.
    assert reindex_required({"CHUNK_SIZE", "OCR_DPI"}) is True


def test_reindex_required_is_false_when_no_reindex_key_changed() -> None:
    # OCR_DPI and LOG_LEVEL hot-load with no re-index.
    assert reindex_required({"OCR_DPI", "LOG_LEVEL"}) is False


def test_reindex_required_of_an_empty_set_is_false() -> None:
    assert reindex_required(set()) is False
