"""Tests for the search server's per-request config hot-reload."""

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
        patch("search.api.setup_libraries"),
        patch("search.api.llm_limiter"),
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


def test_result_cache_is_dropped_when_config_version_moves(tmp_path) -> None:
    """A config change drops the result-cache singleton.

    The cache key changes with the corpus (index_version) but not with settings, so
    without this a repeat query could serve a pre-change answer until the TTL.
    """
    from appdb import config as config_store
    from appdb.connection import connect
    from appdb.schema import ensure_schema
    from common.config import _SETTINGS_CACHE
    from search import cache as result_cache
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

    def fake_resolve_components(settings, core, store_reader):
        del settings, core, store_reader
        return "core", "store_reader"

    with (
        patch.dict(os.environ, env, clear=True),
        patch("search.api._resolve_components", side_effect=fake_resolve_components),
        patch("search.api.setup_libraries"),
        patch("search.api.llm_limiter"),
    ):
        _SETTINGS_CACHE.pop(app_db, None)
        _reset_core_cache_for_test()
        result_cache.reset_search_result_cache()

        _resolve_search_core(app_db)
        # Materialise the result-cache singleton, as an answered query would.
        result_cache.get_search_result_cache(14400)
        assert result_cache._search_result_cache is not None

        # A settings edit bumps config_version; the rebuild must drop the cache.
        c = connect(app_db)
        config_store.set_value(c, "SEARCH_ANSWER_MODEL", "gpt-5.4")
        c.close()
        _resolve_search_core(app_db)
        assert result_cache._search_result_cache is None


def test_resolve_search_core_reinitialises_openai_client_on_config_change(
    tmp_path,
) -> None:
    """Hot-reload re-runs ``setup_libraries`` and ``llm_limiter.init``.

    The planner and synthesiser read the OpenAI client through ``_openai_holder``,
    so a saved ``OPENAI_API_KEY`` / ``LLM_PROVIDER`` / ``OLLAMA_BASE_URL`` /
    ``LLM_MAX_CONCURRENT`` change must rebuild them, or they keep the startup
    credentials until restart.
    """
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
        "OPENAI_API_KEY": "k-initial",
    }

    seen_api_keys: list[str] = []
    seen_limits: list[int] = []

    def spy_setup_libraries(settings):
        seen_api_keys.append(settings.OPENAI_API_KEY)

    fake_limiter = type(
        "FakeLimiter",
        (),
        {"init": lambda self, n: seen_limits.append(n)},
    )()

    with (
        patch.dict(os.environ, env, clear=True),
        patch("search.api._resolve_components", return_value=("core", "store")),
        patch("search.api.setup_libraries", side_effect=spy_setup_libraries),
        patch("search.api.llm_limiter", fake_limiter),
    ):
        _SETTINGS_CACHE.pop(app_db, None)
        _reset_core_cache_for_test()

        # First call: setup_libraries should see the startup OPENAI_API_KEY
        # (provided via the config table seeding from the env).
        _resolve_search_core(app_db)
        assert seen_api_keys == ["k-initial"]
        assert seen_limits == [4]  # LLM_MAX_CONCURRENT default

        # An admin saves a new OPENAI_API_KEY through the Settings API.
        c = connect(app_db)
        config_store.set_value(c, "OPENAI_API_KEY", "k-rotated")
        config_store.set_value(c, "LLM_MAX_CONCURRENT", "8")
        c.close()

        # The next request must re-run setup_libraries with the new key, so
        # the planner / synthesiser pick up the rotation on the very next
        # call rather than keeping the startup client.
        _resolve_search_core(app_db)
        assert seen_api_keys[-1] == "k-rotated"
        assert seen_limits[-1] == 8


def test_current_settings_cache_key_matches_get_all_snapshot(tmp_path) -> None:
    """``current_settings`` caches Settings under the version of the data it read.

    Version and data must come from one ``BEGIN DEFERRED`` snapshot: a writer
    landing between the data read and a later version read would stamp the newer
    version on older data, and that stale entry would be served indefinitely.
    """
    from appdb import config as config_store
    from appdb.connection import connect
    from appdb.schema import ensure_schema
    from common.config import _SETTINGS_CACHE, current_settings

    app_db = str(tmp_path / "app.db")
    conn = connect(app_db)
    ensure_schema(conn)
    # Pre-seed the table so current_settings does NOT take the seed branch.
    config_store.set_value(conn, "PAPERLESS_TOKEN", "t")
    config_store.set_value(conn, "OPENAI_API_KEY", "k")
    conn.close()

    env = {"APP_DB_PATH": app_db}
    with patch.dict(os.environ, env, clear=True):
        _SETTINGS_CACHE.pop(app_db, None)

        captured_versions: list[int] = []
        real_snapshot = config_store.snapshot_config_with_version

        def racing_snapshot(conn):
            version, table = real_snapshot(conn)
            captured_versions.append(version)
            # Simulate a concurrent writer bumping config_version on another
            # connection right after our snapshot.
            other = connect(app_db)
            try:
                config_store.set_value(other, "OCR_DPI", "275")
            finally:
                other.close()
            return version, table

        with patch.object(
            config_store, "snapshot_config_with_version", racing_snapshot
        ):
            current_settings(app_db)

        # The cache must be keyed to the version of the data Settings was built
        # from, not a post-load reread.
        cached_version, _settings = _SETTINGS_CACHE[app_db]
        assert cached_version == captured_versions[0], (
            "Settings cached under a version higher than the data they were "
            "built from — the race window is open."
        )


def test_document_routes_use_paperless_settings_saved_after_startup(
    tmp_path,
) -> None:
    """A saved Paperless URL or token reaches the document, Library and taxonomy
    routes on the next request, without a restart."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from appdb import config as config_store
    from appdb.connection import connect
    from appdb.schema import ensure_schema
    from appdb.users import create as create_user
    from common.config import _SETTINGS_CACHE
    from search.api import _reset_core_cache_for_test, create_app
    from store.models import DocumentPage, DocumentSummary
    from tests.helpers.factories import make_search_settings
    from tests.helpers.search import mint_api_key

    app_db = str(tmp_path / "app.db")
    conn = connect(app_db)
    ensure_schema(conn)
    user = create_user(conn, username="m", password_hash="h", role="member")
    raw_key = mint_api_key(conn, owner_user_id=user.id, scopes="api")
    conn.close()
    env = {
        "APP_DB_PATH": app_db,
        "INDEX_DB_PATH": str(tmp_path / "index.db"),
        "PAPERLESS_URL": "https://old.example",
        "PAPERLESS_TOKEN": "old-token",
        "OPENAI_API_KEY": "k",
    }
    startup_settings = make_search_settings(
        APP_DB_PATH=app_db, PAPERLESS_PUBLIC_URL="https://old.example"
    )
    summary = DocumentSummary(
        id=42,
        title="Invoice",
        correspondent=None,
        document_type=None,
        tags=(),
        created=None,
        page_count=None,
    )
    store_reader = MagicMock()
    store_reader.get_document_summary.return_value = summary
    store_reader.list_documents.return_value = DocumentPage(
        documents=(summary,), total=1, offset=0, limit=24
    )
    paperless_class = MagicMock()
    paperless_class.return_value.list_tags.return_value = []

    with (
        patch.dict(os.environ, env, clear=True),
        patch(
            "search.api._resolve_components",
            side_effect=lambda s, c, r: (c or SimpleNamespace(settings=s), r),
        ),
        patch("search.api.setup_libraries"),
        patch("search.api.llm_limiter"),
        patch("search.document_routes.PaperlessClient", paperless_class),
    ):
        _SETTINGS_CACHE.pop(app_db, None)
        _reset_core_cache_for_test()
        app = create_app(
            startup_settings,
            core=MagicMock(settings=startup_settings),
            store_reader=store_reader,
        )
        client = TestClient(app, base_url="https://testserver")
        client.headers["Authorization"] = f"Bearer {raw_key}"

        c = connect(app_db)
        config_store.set_value(c, "PAPERLESS_PUBLIC_URL", "https://new.example")
        config_store.set_value(c, "PAPERLESS_TOKEN", "new-token")
        c.close()

        document = client.get("/api/documents/42").json()
        library = client.get("/api/documents").json()
        assert client.get("/api/tags").status_code == 200

    assert document["paperless_url"].startswith("https://new.example/")
    assert library["documents"][0]["paperless_url"].startswith("https://new.example/")
    used_settings = paperless_class.call_args.args[0]
    assert used_settings.PAPERLESS_TOKEN == "new-token"
