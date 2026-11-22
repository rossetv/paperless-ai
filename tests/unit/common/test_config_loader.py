"""Tests for common.config.load_settings, the DB-backed Settings loader.

Precedence: config table, then environment, then coded default.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from appdb import config as config_store
from appdb.connection import connect
from appdb.schema import ensure_schema
from common.config import app_db_path_from_env, load_settings
from common.config._loader import _resolve_app_db_path

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
    env = {**_MINIMAL_ENV, "OCR_DPI": "150"}
    with patch.dict(os.environ, env, clear=True):
        settings = load_settings(app_db_path)
    assert settings.OCR_DPI == 150


def test_coded_default_applies_when_neither_db_nor_env_set(app_db_path) -> None:
    with patch.dict(os.environ, _MINIMAL_ENV, clear=True):
        settings = load_settings(app_db_path)
    assert settings.OCR_DPI == 300


def test_bootstrap_path_comes_from_the_environment(app_db_path) -> None:
    env = {**_MINIMAL_ENV, "INDEX_DB_PATH": "/custom/index.db"}
    with patch.dict(os.environ, env, clear=True):
        settings = load_settings(app_db_path)
    assert settings.INDEX_DB_PATH == "/custom/index.db"
    assert settings.APP_DB_PATH == app_db_path


def test_load_validates_a_bad_config_value(app_db_path) -> None:
    conn = connect(app_db_path)
    try:
        config_store.set_value(conn, "CHUNK_SIZE", "not-a-number")
    finally:
        conn.close()
    with patch.dict(os.environ, _MINIMAL_ENV, clear=True):
        with pytest.raises(ValueError, match="CHUNK_SIZE"):
            load_settings(app_db_path)


def test_a_seeded_deployment_loads_unchanged_on_second_start(app_db_path) -> None:
    """Seeding is idempotent and the second load reads back the seeded table."""
    with patch.dict(os.environ, {**_MINIMAL_ENV, "OCR_DPI": "200"}, clear=True):
        first = load_settings(app_db_path)
    # Second start: the env is gone, but the table keeps the seeded values.
    with patch.dict(os.environ, _MINIMAL_ENV, clear=True):
        second = load_settings(app_db_path)
    assert second.OCR_DPI == first.OCR_DPI == 200


def test_current_settings_rebuilds_when_config_version_changes(app_db_path) -> None:
    """The hot-load path: a cached Settings is served until config_version moves."""
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
    from common.config import current_settings

    with patch.dict(os.environ, _MINIMAL_ENV, clear=True):
        a = current_settings(app_db_path)
        b = current_settings(app_db_path)
    assert a is b


def test_openai_defaults_produce_ocr_and_classify_model_lists() -> None:
    from common.config import Settings

    with patch.dict(os.environ, _MINIMAL_ENV, clear=True):
        s = Settings.from_environment()

    assert s.OCR_MODELS == ["gpt-5.6-luna", "gpt-5.6-terra"]
    assert s.CLASSIFY_MODELS == ["gpt-5.6-luna", "gpt-5.6-terra"]
    assert not hasattr(s, "AI_MODELS")


def test_explicit_ocr_and_classify_models_override_defaults() -> None:
    from common.config import Settings

    env = {
        **_MINIMAL_ENV,
        "OCR_MODELS": "gpt-5.4-mini,gpt-5.4",
        "CLASSIFY_MODELS": "gpt-5.5",
    }
    with patch.dict(os.environ, env, clear=True):
        s = Settings.from_environment()

    assert s.OCR_MODELS == ["gpt-5.4-mini", "gpt-5.4"]
    assert s.CLASSIFY_MODELS == ["gpt-5.5"]


def test_legacy_ai_models_populates_both_lists_when_new_keys_absent() -> None:
    from common.config import Settings

    env = {**_MINIMAL_ENV, "AI_MODELS": "legacy-a,legacy-b"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings.from_environment()

    assert s.OCR_MODELS == ["legacy-a", "legacy-b"]
    assert s.CLASSIFY_MODELS == ["legacy-a", "legacy-b"]


def test_explicit_ocr_models_wins_over_ai_models_legacy_fallback() -> None:
    """Precedence: explicit key, then legacy AI_MODELS, then provider default."""
    from common.config import Settings

    env = {**_MINIMAL_ENV, "AI_MODELS": "x", "OCR_MODELS": "y"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings.from_environment()

    assert s.OCR_MODELS == ["y"]
    # CLASSIFY_MODELS falls back to AI_MODELS because CLASSIFY_MODELS is absent.
    assert s.CLASSIFY_MODELS == ["x"]


def test_empty_ai_models_falls_to_provider_default() -> None:
    from common.config import Settings

    env = {**_MINIMAL_ENV, "AI_MODELS": ""}
    with patch.dict(os.environ, env, clear=True):
        s = Settings.from_environment()

    openai_defaults = ["gpt-5.6-luna", "gpt-5.6-terra"]
    assert s.OCR_MODELS == openai_defaults
    assert s.CLASSIFY_MODELS == openai_defaults


def test_ai_models_deprecation_warning_fires_once() -> None:
    """The one-shot flag keeps the hot-load loop from spamming the warning."""
    import common.config._settings as _settings_mod
    from common.config import Settings

    # Reset the one-shot flag so this test is independent of import order.
    _settings_mod._ai_models_deprecation_warned = False
    try:
        env = {**_MINIMAL_ENV, "AI_MODELS": "some-model"}
        with patch.dict(os.environ, env, clear=True):
            Settings.from_environment()
            assert _settings_mod._ai_models_deprecation_warned is True
            Settings.from_environment()
            assert _settings_mod._ai_models_deprecation_warned is True
    finally:
        _settings_mod._ai_models_deprecation_warned = False


def test_ai_models_deprecation_warning_silent_when_new_keys_set() -> None:
    import common.config._settings as _settings_mod
    from common.config import Settings

    _settings_mod._ai_models_deprecation_warned = False
    try:
        env = {
            **_MINIMAL_ENV,
            "AI_MODELS": "legacy-model",
            "OCR_MODELS": "explicit-ocr",
            "CLASSIFY_MODELS": "explicit-classify",
        }
        with patch.dict(os.environ, env, clear=True):
            Settings.from_environment()

        assert _settings_mod._ai_models_deprecation_warned is False
    finally:
        _settings_mod._ai_models_deprecation_warned = False


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_app_db_path_means_the_default_path(blank) -> None:
    with patch.dict(os.environ, {"APP_DB_PATH": blank}, clear=True):
        assert app_db_path_from_env() == "/data/app.db"
        assert _resolve_app_db_path(None) == "/data/app.db"


def test_app_db_path_from_the_environment_is_used_and_stripped() -> None:
    with patch.dict(os.environ, {"APP_DB_PATH": " /srv/app.db "}, clear=True):
        assert app_db_path_from_env() == "/srv/app.db"
