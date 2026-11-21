"""Open and migrate ``app.db`` at server startup."""

from __future__ import annotations

import sqlite3

import structlog

from appdb.connection import connect
from appdb.schema import ensure_schema

log = structlog.get_logger(__name__)


def open_app_db(app_db_path: str) -> sqlite3.Connection:
    """Open ``app.db`` at *app_db_path*, run migrations, return the connection.

    The connection is for startup work only and must not be reused across
    requests; those open their own via :func:`search.deps.get_app_db`.

    Raises:
        appdb.migrations.AppDbError: The database was written by newer code.
    """
    conn = connect(app_db_path)
    ensure_schema(conn)
    log.info("search.app_db_ready", path=app_db_path)
    return conn
