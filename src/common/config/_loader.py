"""The ``app.db``-backed Settings loader and the version-keyed hot-load accessor.

:func:`load_settings` is the one-shot startup loader; :func:`current_settings`
is called at a safe boundary to pick up saved configuration without a restart.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping

from ._catalogue import CONFIG_KEYS
from ._parsers import _get_str_env
from ._settings import _DEFAULT_APP_DB_PATH, Settings, _build_settings


def load_settings(app_db_path: str) -> Settings:
    """Build a validated :class:`Settings` from ``app.db`` and the environment.

    For each key a table value wins, then an environment variable, then the
    default. An empty table is first seeded from the environment, so an
    env-configured deployment keeps working and becomes editable in Settings.

    Raises:
        ValueError: A required key is missing or a value fails validation; the
            message names the key.
        appdb.migrations.AppDbError: ``app.db`` was written by newer code.
    """
    # Deferred so a plain `import common.config` does not import appdb.
    from appdb import config as config_store  # noqa: PLC0415
    from appdb.connection import connect  # noqa: PLC0415
    from appdb.schema import ensure_schema  # noqa: PLC0415

    conn = connect(app_db_path)
    try:
        ensure_schema(conn)
        config_store.seed_from_env(conn, environ=os.environ, keys=set(CONFIG_KEYS))
        stored = config_store.get_all(conn)
    finally:
        conn.close()

    merged: dict[str, str] = dict(os.environ)
    merged.update(stored)
    # Settings.APP_DB_PATH must be the path actually used, set in env or not.
    merged["APP_DB_PATH"] = app_db_path
    return _build_settings(merged)


# app.db path -> (config_version, Settings). Rebuilt only when the version
# moves, so a polling daemon pays one cheap SELECT per check.
_SETTINGS_CACHE: dict[str, tuple[int, Settings]] = {}


# Serialises rebuilds so concurrent callers on a new version build Settings once;
# the lookup path stays lock-free.
_SETTINGS_CACHE_LOCK = threading.Lock()


def app_db_path_from_env() -> str:
    """Return ``APP_DB_PATH`` from the environment; unset or blank is the default.

    A blank path would open a private temporary database, so every process
    would get its own empty config.
    """
    return _get_str_env(os.environ, "APP_DB_PATH", _DEFAULT_APP_DB_PATH)


def _resolve_app_db_path(app_db_path: str | None) -> str:
    """Resolve *app_db_path* to the path that will be used as the cache key."""
    return app_db_path if app_db_path is not None else app_db_path_from_env()


def _hot_load(resolved: str) -> tuple[int, Settings]:
    """Snapshot, check the cache, and rebuild under the lock if needed.

    Returns ``(version, settings)`` built from one ``BEGIN DEFERRED`` snapshot,
    so the two always match.
    """
    from appdb import config as config_store  # noqa: PLC0415
    from appdb.connection import connect  # noqa: PLC0415
    from appdb.schema import ensure_schema  # noqa: PLC0415

    # The snapshot also captures the data a rebuild needs, so the rebuild never
    # re-opens the DB and cannot pair a version with other data.
    conn = connect(resolved)
    try:
        ensure_schema(conn)
        version, config_table = config_store.snapshot_config_with_version(conn)
    finally:
        conn.close()

    cached = _SETTINGS_CACHE.get(resolved)
    if cached is not None and cached[0] == version:
        return cached

    # Re-check under the lock: another caller may have rebuilt while we waited.
    with _SETTINGS_CACHE_LOCK:
        cached = _SETTINGS_CACHE.get(resolved)
        if cached is not None and cached[0] == version:
            return cached

        if not config_table:
            # Seeding bumps config_version, so re-snapshot to key the cache on
            # the post-seed version. On a fresh deployment every process may
            # seed at once; that is only safe because seed_from_env is
            # idempotent (no-op once a row exists, upsert writes). Keep it so.
            conn = connect(resolved)
            try:
                config_store.seed_from_env(
                    conn, environ=os.environ, keys=set(CONFIG_KEYS)
                )
                version, config_table = config_store.snapshot_config_with_version(conn)
            finally:
                conn.close()

        settings = _build_settings(_merge_environment(config_table, resolved))
        pair: tuple[int, Settings] = (version, settings)
        _SETTINGS_CACHE[resolved] = pair
        return pair


def current_settings(app_db_path: str | None = None) -> Settings:
    """Return the up-to-date :class:`Settings`, rebuilding it on a config change.

    Called at a safe boundary (a daemon's poll loop, the search server per
    request). Cheap: one snapshot read, and the cached :class:`Settings` is
    returned unless ``config_version`` has moved. The shared ``config_version``
    row is the only cross-process signal. *app_db_path* defaults to
    ``APP_DB_PATH``; tests pass a temp file.

    Raises:
        ValueError: A stored value fails validation (same as
            :func:`load_settings`).
        appdb.migrations.AppDbError: ``app.db`` was written by newer code.
    """
    _, settings = _hot_load(_resolve_app_db_path(app_db_path))
    return settings


def current_settings_with_version(
    app_db_path: str | None = None,
) -> tuple[int, Settings]:
    """Return ``(config_version, Settings)`` atomically, rebuilding on change.

    For callers that key a downstream cache on the version (e.g.
    :func:`search.api._resolve_search_core`): the version is the one the
    settings were built from, so a concurrent write cannot leave a newer version
    stuck to a cache entry built from older settings.
    """
    return _hot_load(_resolve_app_db_path(app_db_path))


def _merge_environment(
    config_table: Mapping[str, str], app_db_path: str
) -> dict[str, str]:
    """Layer *config_table* over ``os.environ`` for :func:`_build_settings`.

    Same merge as :func:`load_settings`: the table wins over the environment
    and ``APP_DB_PATH`` is forced to *app_db_path*.
    """
    merged: dict[str, str] = dict(os.environ)
    merged.update(config_table)
    merged["APP_DB_PATH"] = app_db_path
    return merged
