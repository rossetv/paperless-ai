"""The DB-backed Settings loader and the version-keyed hot-load accessor.

Layers the ``config`` table in ``app.db`` over the process environment and
builds a :class:`~common.config._settings.Settings` from the merge — the
production configuration path (web-redesign spec §5). :func:`load_settings` is
the one-shot startup loader; :func:`current_settings` is the cheap hot-load
accessor a polling daemon or the search server calls at a safe boundary to pick
up saved configuration without a restart.

This module depends on :mod:`._settings` (the :class:`Settings` shape and
:func:`_build_settings`) and :mod:`._catalogue` (``CONFIG_KEYS``); the
dependency flows one way, parsing below loading, so there is no cycle.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping

from ._catalogue import CONFIG_KEYS
from ._settings import Settings, _build_settings


def load_settings(app_db_path: str) -> Settings:
    """Build a validated :class:`Settings` from ``app.db`` and the environment.

    The production configuration entry point (web-redesign spec §5). It layers
    the ``config`` table over the process environment so that, for every key,
    a value in the table wins, then an environment variable, then the coded
    default.

    On first run — when the ``config`` table is empty — it seeds the table
    from the current environment (:func:`appdb.config.seed_from_env`), so a
    deployment previously configured with environment variables keeps working
    with no change and its settings become editable in the Settings screen.

    The two bootstrap variables ``APP_DB_PATH`` and ``INDEX_DB_PATH`` are
    never read from the table — they tell the process where its databases
    live, so they stay environment-only.

    Args:
        app_db_path: Filesystem path to ``app.db``. Comes from the
            ``APP_DB_PATH`` bootstrap environment variable (resolved by the
            caller, normally :func:`common.bootstrap.bootstrap_process`).

    Returns:
        The validated :class:`Settings`.

    Raises:
        ValueError: A required key is missing from both the table and the
            environment, or a stored value fails validation. The message
            names the offending key.
        appdb.migrations.AppDbError: ``app.db`` was written by newer code.

    rationale: ``app.db`` is opened and closed within this function — the
    loader needs only a transient connection. The search server opens its own
    long-lived ``app.db`` connection for the Settings API; the daemons only
    ever read config once, at startup, so a per-call connection is correct
    and avoids leaking a handle a daemon would never use again.
    """
    # Deferred imports: common is the leaf package, and importing appdb at
    # module scope would run on every `import common.config`. A function-body
    # import keeps the dependency where it is actually used and matches the
    # relaxed import boundary (appdb is permitted; store is not).
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

    # Merge: the environment first, the config table layered on top — so a
    # config-table value overrides an environment value. The bootstrap
    # variables are environment-only, so they survive from os.environ; they
    # are never in `stored` because seed_from_env only seeds CONFIG_KEYS.
    merged: dict[str, str] = dict(os.environ)
    merged.update(stored)
    # The bootstrap variables are never in the config table, but app_db_path
    # is known explicitly here — inject it so _build_settings resolves
    # Settings.APP_DB_PATH to the path the caller actually used, regardless
    # of whether APP_DB_PATH is set in the environment.
    merged["APP_DB_PATH"] = app_db_path
    return _build_settings(merged)


# Process-local hot-load cache: app.db path -> (config_version, Settings).
# current_settings() rebuilds Settings only when the stored config_version
# has advanced, so a polling daemon pays one cheap SELECT per check.
_SETTINGS_CACHE: dict[str, tuple[int, Settings]] = {}


# Lock serialising rebuilds of ``_SETTINGS_CACHE``. The dict ops themselves are
# GIL-atomic, but two concurrent first-callers (or two callers landing on a
# fresh ``config_version``) would otherwise both build a Settings and both
# write — the loser's expensive build is wasted. The lock collapses that into
# one builder per version. The lookup path stays lock-free; only the rebuild
# is serialised.
_SETTINGS_CACHE_LOCK = threading.Lock()


def current_settings(app_db_path: str | None = None) -> Settings:
    """Return the up-to-date :class:`Settings`, rebuilding it on a config change.

    The hot-load accessor (web-redesign §5, Wave 4). Saving configuration does
    not restart any process; instead every process calls this at a safe
    boundary — a daemon at the top of its poll loop, the search server per
    request — and gets a :class:`Settings` that reflects the latest saved
    configuration.

    It takes no argument in normal use: *app_db_path* defaults to the
    ``APP_DB_PATH`` bootstrap environment variable (the same value
    :func:`common.bootstrap.bootstrap_process` resolves), so every process
    can simply ``from common.config import current_settings`` and call it.
    The explicit parameter exists for tests, which point it at a temp file.

    It is cheap to call repeatedly. It opens ``app.db`` and takes a single
    snapshot of ``(config_version, config_table)`` via
    :func:`appdb.config.snapshot_config_with_version` — one connection, one
    ``BEGIN DEFERRED`` transaction — so the version and the data it describes
    are always consistent. When that integer is unchanged since the last
    call for this *app_db_path*, it returns the **cached** :class:`Settings`
    untouched. Only when ``config_version`` has advanced (or on the first
    call) does it rebuild from the snapshot and re-cache under the very
    version the snapshot reported.

    The cache is process-local module state. Cross-process coordination is the
    shared ``config_version`` row alone — when one process writes config
    through the Settings API, every other process sees the bumped version on
    its next check and rebuilds. No signal, no IPC, no restart.

    Args:
        app_db_path: Filesystem path to ``app.db``. When ``None`` (the normal
            case) it is read from the ``APP_DB_PATH`` environment variable,
            with the same ``/data/app.db`` default the other entry points use.

    Returns:
        The current validated :class:`Settings`.

    Raises:
        ValueError: A stored value fails validation (same as
            :func:`load_settings`).
        appdb.migrations.AppDbError: ``app.db`` was written by newer code.
    """
    # Deferred import — see load_settings for the rationale.
    from appdb import config as config_store  # noqa: PLC0415
    from appdb.connection import connect  # noqa: PLC0415
    from appdb.schema import ensure_schema  # noqa: PLC0415

    resolved = (
        app_db_path
        if app_db_path is not None
        else os.environ.get("APP_DB_PATH", "/data/app.db")
    )

    # Fast path: read the version under a snapshot, take the cache value if
    # it matches. The snapshot also captures the config_table we will need
    # if the version has moved, so we never re-open the DB on the rebuild
    # path — the version and the data are consistent by construction.
    conn = connect(resolved)
    try:
        ensure_schema(conn)
        version, config_table = config_store.snapshot_config_with_version(conn)
    finally:
        conn.close()

    cached = _SETTINGS_CACHE.get(resolved)
    if cached is not None and cached[0] == version:
        return cached[1]

    # Slow path under a lock: re-check the cache (another caller may have
    # rebuilt while we waited), then build a Settings from the snapshot we
    # took above and cache it under the version that snapshot reported. If
    # the config table is empty we first seed it from the environment — that
    # bumps config_version, so we re-snapshot and rebuild from the seeded
    # data — and the cached pair is always (version, Settings-built-from-it).
    with _SETTINGS_CACHE_LOCK:
        cached = _SETTINGS_CACHE.get(resolved)
        if cached is not None and cached[0] == version:
            return cached[1]

        if not config_table:
            # First-run seed (web-redesign §5). The seed runs inside its own
            # ``BEGIN IMMEDIATE`` and bumps config_version; re-snapshot so the
            # cache key matches the post-seed version.
            #
            # Cross-process precondition (COMMON-04): on a fresh deployment
            # every process (the daemons, the search server) can boot at once,
            # all see an empty config table, and all call seed_from_env. That is
            # only safe because seed_from_env is idempotent — it no-ops once any
            # row exists and writes via INSERT ... ON CONFLICT, so a concurrent
            # double-seed converges on the same env-derived values rather than
            # corrupting the table. Do not relax that idempotency in appdb.
            conn = connect(resolved)
            try:
                config_store.seed_from_env(
                    conn, environ=os.environ, keys=set(CONFIG_KEYS)
                )
                version, config_table = config_store.snapshot_config_with_version(conn)
            finally:
                conn.close()

        settings = _build_settings(_merge_environment(config_table, resolved))
        _SETTINGS_CACHE[resolved] = (version, settings)
        return settings


def current_settings_with_version(
    app_db_path: str | None = None,
) -> tuple[int, Settings]:
    """Return ``(config_version, Settings)`` atomically, rebuilding on change.

    A thin companion to :func:`current_settings` for callers that need to key
    a downstream cache against the *exact* version the settings snapshot was
    built from. The version comes from the same ``BEGIN DEFERRED`` snapshot
    used to read the config table, so it is guaranteed to match the data in
    the returned :class:`Settings` — it cannot be a later version stamped onto
    an earlier dataset.

    The typical caller is :func:`search.api._resolve_search_core`: it caches a
    ``SearchCore`` built from the settings and must key that cache against the
    version the settings actually describe, so a concurrent admin write cannot
    produce a ``(newer_version, core_from_older_settings)`` pair that sticks
    until a *further* unrelated write bumps the counter again.

    All caching logic (including the rebuild-under-lock slow path) is delegated
    to :func:`current_settings`; after it returns the ``_SETTINGS_CACHE`` entry
    for *resolved* is guaranteed to be at the version the settings were built
    from (or a later one if another thread rebuilt first — which is fine, the
    returned version always matches the returned Settings).

    Args:
        app_db_path: Filesystem path to ``app.db``. When ``None`` (the normal
            case) it is read from the ``APP_DB_PATH`` environment variable.

    Returns:
        ``(config_version, Settings)`` where ``config_version`` is the
        version the settings snapshot was built from.
    """
    resolved = (
        app_db_path
        if app_db_path is not None
        else os.environ.get("APP_DB_PATH", "/data/app.db")
    )

    # Delegate to current_settings for all snapshot + cache logic. Every return
    # path inside it leaves _SETTINGS_CACHE[resolved] populated with the
    # (version, settings) pair it returned — the fast path returns an entry that
    # already existed, the slow path writes one before returning — so the read
    # below is always a hit. This is a GIL-atomic dict read, no lock needed.
    current_settings(resolved)
    version, settings = _SETTINGS_CACHE[resolved]
    return version, settings


def _merge_environment(
    config_table: Mapping[str, str], app_db_path: str
) -> dict[str, str]:
    """Layer *config_table* over ``os.environ`` for :func:`_build_settings`.

    Mirrors the merge :func:`load_settings` performs, factored out so the
    hot-load fast path can reuse it without re-opening ``app.db``: the table
    value wins over an environment value, the bootstrap variables stay
    environment-only, and ``APP_DB_PATH`` is forced to the *app_db_path* the
    caller resolved (it is never in the table).
    """
    merged: dict[str, str] = dict(os.environ)
    merged.update(config_table)
    merged["APP_DB_PATH"] = app_db_path
    return merged
