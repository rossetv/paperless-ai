"""Tests for the search server's per-request config hot-reload (web-redesign §5)."""

from __future__ import annotations

import os
from unittest.mock import patch


def test_search_core_is_rebuilt_when_config_version_moves(tmp_path) -> None:
    """The per-request accessor rebuilds the search core on a config change,
    and serves the cached core when config_version is unchanged."""
    from appdb import config as config_store
    from appdb.connection import connect
    from appdb.schema import ensure_schema
    from common.config import _SETTINGS_CACHE
    from search.api import _reset_core_cache_for_test, _resolve_search_core

    app_db = str(tmp_path / "app.db")
    conn = connect(app_db)
    ensure_schema(conn)
    conn.close()
    env = {
        "APP_DB_PATH": app_db,
        "INDEX_DB_PATH": str(tmp_path / "index.db"),
        "PAPERLESS_TOKEN": "t",
        "OPENAI_API_KEY": "k",
    }

    # The component graph is expensive to build for real (a StoreReader opens
    # a sqlite-vec extension; an EmbeddingClient needs the OpenAI singleton).
    # We patch _resolve_components to a cheap fake and assert it is called
    # exactly once per config change — the contract under test is "rebuild
    # only on a config_version change".
    fake_cores = ["core_v1", "core_v2"]
    call_count = {"n": 0}

    def fake_resolve_components(settings, core, store_reader):
        del settings, core, store_reader
        index = call_count["n"]
        call_count["n"] += 1
        return fake_cores[index], "store_reader"

    with (
        patch.dict(os.environ, env, clear=True),
        patch("search.api._resolve_components", side_effect=fake_resolve_components),
    ):
        # Clear both the hot-load cache and the search-core cache so this
        # test sees the temp app.db fresh, untainted by earlier tests.
        _SETTINGS_CACHE.pop(app_db, None)
        _reset_core_cache_for_test()

        first = _resolve_search_core(app_db)
        # No config change — the same core is served.
        assert _resolve_search_core(app_db) is first
        assert call_count["n"] == 1

        # A config write bumps config_version; the next resolve rebuilds.
        c = connect(app_db)
        config_store.set_value(c, "SEARCH_TOP_K", "25")
        c.close()
        rebuilt = _resolve_search_core(app_db)
        assert rebuilt is not first
        assert call_count["n"] == 2
