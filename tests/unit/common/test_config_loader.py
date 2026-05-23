"""Tests for common.config.load_settings — the DB-backed Settings loader.

Covers the precedence rule (config table beats environment beats default),
first-run env seeding (an empty config table is populated from the
environment), bootstrap variables staying env-only, and that the loaded
Settings is fully validated exactly as from_environment would have built it.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from appdb import config as config_store
from appdb.connection import connect
from appdb.schema import ensure_schema
from common.config import load_settings

_MINIMAL_ENV = {
    "PAPERLESS_TOKEN": "env-token",
    "OPENAI_API_KEY": "env-api-key",
}


@pytest.fixture()
def app_db_path(tmp_path):
    """A migrated app.db file path."""
    path = str(tmp_path / "app.db")
    conn = connect(path)
    ensure_schema(conn)
    conn.close()
    return path


def test_load_seeds_an_empty_table_from_the_environment(app_db_path) -> None:
    """First run: an empty config table is seeded from os.environ."""
    with patch.dict(os.environ, _MINIMAL_ENV, clear=True):
        load_settings(app_db_path)
    conn = connect(app_db_path)
    try:
        stored = config_store.get_all(conn)
    finally:
        conn.close()
    assert stored["PAPERLESS_TOKEN"] == "env-token"
    assert stored["OPENAI_API_KEY"] == "env-api-key"


def test_load_does_not_seed_bootstrap_keys(app_db_path) -> None:
    """APP_DB_PATH / INDEX_DB_PATH are never written to the config table."""
    env = {**_MINIMAL_ENV, "INDEX_DB_PATH": "/data/index.db"}
    with patch.dict(os.environ, env, clear=True):
        load_settings(app_db_path)
    conn = connect(app_db_path)
    try:
        stored = config_store.get_all(conn)
    finally:
        conn.close()
    assert "INDEX_DB_PATH" not in stored
    assert "APP_DB_PATH" not in stored


def test_config_table_value_beats_the_environment(app_db_path) -> None:
    """A value in the config table wins over the same env var."""
    conn = connect(app_db_path)
    try:
        config_store.set_value(conn, "CHUNK_SIZE", "8000")
    finally:
        conn.close()
    env = {**_MINIMAL_ENV, "CHUNK_SIZE": "2000"}
    with patch.dict(os.environ, env, clear=True):
        settings = load_settings(app_db_path)
    assert settings.CHUNK_SIZE == 8000


def test_environment_beats_the_coded_default(app_db_path) -> None:
    """With no config-table row, the env var beats the coded default."""
    env = {**_MINIMAL_ENV, "OCR_DPI": "150"}
    with patch.dict(os.environ, env, clear=True):
        settings = load_settings(app_db_path)
    assert settings.OCR_DPI == 150


def test_coded_default_applies_when_neither_db_nor_env_set(app_db_path) -> None:
    """A key absent from both the table and the env falls to the default."""
    with patch.dict(os.environ, _MINIMAL_ENV, clear=True):
        settings = load_settings(app_db_path)
    assert settings.OCR_DPI == 300  # the coded default


def test_bootstrap_path_comes_from_the_environment(app_db_path) -> None:
    """INDEX_DB_PATH is read from the environment, not the config table."""
    env = {**_MINIMAL_ENV, "INDEX_DB_PATH": "/custom/index.db"}
    with patch.dict(os.environ, env, clear=True):
        settings = load_settings(app_db_path)
    assert settings.INDEX_DB_PATH == "/custom/index.db"
    assert settings.APP_DB_PATH == app_db_path


def test_load_validates_a_bad_config_value(app_db_path) -> None:
    """A non-integer in the config table raises ValueError, naming the key."""
    conn = connect(app_db_path)
    try:
        config_store.set_value(conn, "CHUNK_SIZE", "not-a-number")
    finally:
        conn.close()
    with patch.dict(os.environ, _MINIMAL_ENV, clear=True):
        with pytest.raises(ValueError, match="CHUNK_SIZE"):
            load_settings(app_db_path)


def test_a_seeded_deployment_loads_unchanged_on_second_start(app_db_path) -> None:
    """Two consecutive loads of the same env give the same Settings — seeding
    is idempotent and the second load reads back the seeded table."""
    with patch.dict(os.environ, {**_MINIMAL_ENV, "OCR_DPI": "200"}, clear=True):
        first = load_settings(app_db_path)
    # Second start: the env is gone, but the table keeps the seeded values.
    with patch.dict(os.environ, _MINIMAL_ENV, clear=True):
        second = load_settings(app_db_path)
    assert second.OCR_DPI == first.OCR_DPI == 200


def test_current_settings_rebuilds_when_config_version_changes(app_db_path) -> None:
    """current_settings serves a cached Settings until config_version moves,
    then rebuilds — the hot-load path, no restart."""
    from common.config import current_settings

    conn = connect(app_db_path)
    try:
        config_store.set_value(conn, "OCR_DPI", "150")
    finally:
        conn.close()
    with patch.dict(os.environ, _MINIMAL_ENV, clear=True):
        first = current_settings(app_db_path)
        assert first.OCR_DPI == 150
        # A second call with no config change returns the cached object.
        assert current_settings(app_db_path) is first
        # A config write bumps config_version; the next call rebuilds.
        conn = connect(app_db_path)
        try:
            config_store.set_value(conn, "OCR_DPI", "275")
        finally:
            conn.close()
        rebuilt = current_settings(app_db_path)
    assert rebuilt is not first
    assert rebuilt.OCR_DPI == 275


def test_current_settings_is_cached_across_calls(app_db_path) -> None:
    """With no config change between calls, current_settings does not rebuild."""
    from common.config import current_settings

    with patch.dict(os.environ, _MINIMAL_ENV, clear=True):
        a = current_settings(app_db_path)
        b = current_settings(app_db_path)
    assert a is b
