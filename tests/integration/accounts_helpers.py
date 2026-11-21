"""Helpers for the account integration tests.

They build the real search app over a ``tmp_path`` ``app.db`` and a seeded
``index.db``, and seed users straight through ``appdb`` to skip first-run setup.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from appdb.connection import connect
from appdb.passwords import hash_password
from appdb.schema import ensure_schema
from appdb.users import User
from appdb.users import create as create_user
from store.models import ChunkInput, DocumentMeta, TaxonomyEntry
from store.reader import StoreReader
from store.writer import StoreWriter
from tests.helpers.factories import (
    make_search_result,
    make_search_settings,
    make_source_document,
)

# These tests exercise routing and auth, never retrieval geometry.
_DIMENSIONS = 4
_AXIS_A: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0)


def make_settings(tmp_path: Path, **overrides: Any) -> MagicMock:
    """Build a settings mock pointing the index and app databases at *tmp_path*."""
    return make_search_settings(
        INDEX_DB_PATH=str(tmp_path / "index.db"),
        APP_DB_PATH=str(tmp_path / "app.db"),
        EMBEDDING_DIMENSIONS=_DIMENSIONS,
        **overrides,
    )


def seed_store(settings: MagicMock) -> None:
    """Seed the index with one document, taxonomy and a reconcile timestamp.

    The timestamp makes healthz and the stats endpoint report a ready store.
    """
    writer = StoreWriter(settings)
    try:
        writer.refresh_taxonomy(
            [
                TaxonomyEntry(kind="correspondent", id=1, name="BritishGas"),
                TaxonomyEntry(kind="document_type", id=2, name="Invoice"),
            ]
        )
        meta = DocumentMeta(
            id=100,
            title="BritishGas Invoice",
            correspondent_id=1,
            document_type_id=2,
            tag_ids=(),
            created="2024-03-01T00:00:00Z",
            modified="2024-06-01T12:00:00Z",
            content_hash="abc123",
            page_count=2,
        )
        chunk = ChunkInput(
            chunk_index=0,
            text="Your total bill amount is £198.00 for the quarter.",
            page_hint=1,
            embedding=_AXIS_A,
        )
        writer.upsert_document(meta, [chunk])
        writer.write_meta("last_reconcile_at", "2024-06-01T12:00:00Z")
    finally:
        writer.close()


def make_mock_core() -> MagicMock:
    """Build a stub ``SearchCore`` returning one fixed source document.

    Account tests only need ``/api/search`` to succeed once a caller is authorised.
    """
    core = MagicMock()
    core.answer.return_value = make_search_result(
        answer="The bill is £198.00.",
        sources=(
            make_source_document(
                document_id=100,
                title="BritishGas Invoice",
                correspondent="BritishGas",
                document_type="Invoice",
                created="2024-03-01T00:00:00Z",
                snippet="Your total bill amount is £198.00.",
                score=0.95,
            ),
        ),
    )
    # /api/search sizes its semaphore from core.settings.SEARCH_MAX_CONCURRENT,
    # so the stub needs a real int there, not a MagicMock.
    core.settings = make_search_settings()
    return core


def build_account_client(
    settings: MagicMock,
    app_db: sqlite3.Connection,
    store_reader: StoreReader,
) -> TestClient:
    """Build a ``TestClient`` over the real app, sharing the test's ``app.db``.

    The app opens its own connection to ``settings.APP_DB_PATH`` per request.
    *app_db* is the test's connection to the same file, kept only for seeding
    and inspection; under WAL it sees every write the app commits. The
    ``https`` base URL keeps the ``Secure`` session cookie on follow-up requests.
    """
    # Deliberately not passed to create_app, which opens its own connections.
    _ = app_db
    from search.api import create_app

    app = create_app(
        settings,
        core=make_mock_core(),
        store_reader=store_reader,
    )
    return TestClient(app, raise_server_exceptions=False, base_url="https://testserver")


def open_app_db(tmp_path: Path) -> sqlite3.Connection:
    """Open and migrate a fresh ``app.db`` with no users (first-run setup mode)."""
    conn = connect(str(tmp_path / "app.db"))
    ensure_schema(conn)
    return conn


def seed_user(
    app_db: sqlite3.Connection,
    *,
    username: str,
    password: str = "test-password",
    role: str = "member",
) -> User:
    """Insert a user straight into *app_db*, bypassing the setup flow."""
    return create_user(
        app_db,
        username=username,
        password_hash=hash_password(password),
        role=role,
    )


def seed_admin(
    app_db: sqlite3.Connection,
    *,
    username: str = "admin",
    password: str = "admin-password",
) -> User:
    """Insert an admin user straight into *app_db*, putting it past first-run setup."""
    return seed_user(app_db, username=username, password=password, role="admin")


def login(
    client: TestClient,
    *,
    username: str,
    password: str,
    remember: bool = False,
) -> Any:
    """Drive ``POST /api/auth/login``; on success the client holds the session."""
    return client.post(
        "/api/auth/login",
        json={
            "username": username,
            "password": password,
            "remember": remember,
        },
    )
