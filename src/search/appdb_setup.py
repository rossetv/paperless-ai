"""Open and prepare the application database for the search server.

:func:`open_app_db` connects to ``app.db`` via :mod:`appdb.connection`, runs
the migrations (creating the ``users``/``sessions`` schema on a fresh
database), and returns the open connection. It is the single place the search
server's startup touches ``app.db`` — the daemons get their own entry point
in Wave 4.

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
