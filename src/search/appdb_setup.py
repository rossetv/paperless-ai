"""Open and prepare the application database for the search server.

:func:`open_app_db` connects to ``app.db`` via :mod:`appdb.connection` and
runs the migrations (creating the ``users``/``sessions`` schema on a fresh
database). It is used at server startup for a single short-lived connection:
the caller migrates the database, detects whether first-run setup is needed,
and then closes the connection. Per-request work opens its own connection
through :func:`search.deps.get_app_db` — ``app.db`` connections are never
shared across requests.

Allowed deps: structlog, appdb (connection, schema). Forbidden: FastAPI.
"""

from __future__ import annotations

import sqlite3

import structlog

from appdb.connection import connect
from appdb.schema import ensure_schema

log = structlog.get_logger(__name__)


def open_app_db(app_db_path: str) -> sqlite3.Connection:
    """Open ``app.db`` at *app_db_path*, run migrations, return the connection.

    The returned connection is intended to be short-lived: the caller uses it
    for startup work (migrations are already applied here; first-run setup
    detection is the caller's next step) and then closes it. It must not be
    stashed for reuse across requests.

    Args:
        app_db_path: The filesystem path to ``app.db`` (``Settings.APP_DB_PATH``).

    Returns:
        An open, migrated :class:`sqlite3.Connection`.

    Raises:
        appdb.migrations.AppDbError: The database was written by newer code.
    """
    conn = connect(app_db_path)
    ensure_schema(conn)
    log.info("search.app_db_ready", path=app_db_path)
    return conn
