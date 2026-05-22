"""Shared helpers for the Wave 1 account integration tests.

The account integration tests (``test_accounts_setup``, ``test_accounts_auth``,
``test_accounts_rbac``, ``test_accounts_guards``) all build the real search
FastAPI app over a real ``tmp_path`` ``app.db`` and a real seeded
``index.db``. The app-building, store-seeding and account-seeding code lives
here so each file imports one definition, mirroring
``tests/integration/conftest.py`` for the search pipeline.

Two ways in:

- :func:`build_account_client` builds the app and returns the ``TestClient``
  plus the open ``app.db`` connection, so a test can inspect or mutate the
  database directly (e.g. assert sessions were deleted).
- :func:`seed_admin` / :func:`seed_user` insert a user straight through
  ``appdb`` — bypassing the setup flow — for tests that need an existing
  account without driving ``POST /api/setup``.

``base_url="https://testserver"`` is used so the ``Secure`` session cookie is
retained on follow-up requests (the cookie carries the ``Secure`` flag, which
a plain ``http://`` test client would drop).
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

# The legacy SEARCH_API_KEY used by the integration suite. The legacy-bearer
# tests assert a request carrying this key as a Bearer token is authorised.
LEGACY_API_KEY = "integration-accounts-legacy-key"

# Embedding width — four keeps the seeded vector tiny; the integration tests
# never exercise real retrieval geometry, only routing and auth.
_DIMENSIONS = 4
_AXIS_A: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0)


def make_settings(tmp_path: Path, **overrides: Any) -> MagicMock:
    """Build a settings mock pointing at the ``tmp_path`` index store.

    ``APP_DB_PATH`` is set to a ``tmp_path`` file too, although the account
    tests pass an explicit in-tree ``app.db`` connection to
    :func:`build_account_client` and never let ``create_app`` open one itself.

    Args:
        tmp_path: The pytest ``tmp_path`` directory.
        **overrides: Any further ``Settings`` field overrides.
    """
    return make_search_settings(
        SEARCH_API_KEY=LEGACY_API_KEY,
        INDEX_DB_PATH=str(tmp_path / "index.db"),
        APP_DB_PATH=str(tmp_path / "app.db"),
        EMBEDDING_DIMENSIONS=_DIMENSIONS,
        **overrides,
    )


def seed_store(settings: MagicMock) -> None:
    """Seed the index store with one reconciled document and taxonomy.

    The reconcile timestamp is written so ``GET /api/healthz`` and the public
    stats endpoint see a fully-ready store.

    Args:
        settings: The settings mock from :func:`make_settings`.
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

    The account integration tests only need ``/api/search`` to *succeed* once
    a caller is authorised — the answer content is irrelevant — so the core
    is a stub rather than the real pipeline.
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
    return core


def build_account_client(
    settings: MagicMock,
    app_db: sqlite3.Connection,
    store_reader: StoreReader,
) -> TestClient:
    """Build a ``TestClient`` over the real app with an explicit ``app.db``.

    Passes a pre-opened, migrated *app_db* into ``create_app`` so the test
    owns the connection and can inspect it. ``base_url="https://testserver"``
    keeps the ``Secure`` session cookie on follow-up requests.

    Args:
        settings: The settings mock from :func:`make_settings`.
        app_db: A pre-opened, migrated ``app.db`` connection.
        store_reader: A real :class:`~store.reader.StoreReader`.

    Returns:
        A :class:`~fastapi.testclient.TestClient` over the app.
    """
    from search.api import create_app

    app = create_app(
        settings,
        core=make_mock_core(),
        store_reader=store_reader,
        app_db=app_db,
    )
    return TestClient(
        app, raise_server_exceptions=False, base_url="https://testserver"
    )


def open_app_db(tmp_path: Path) -> sqlite3.Connection:
    """Open and migrate a fresh ``app.db`` under *tmp_path*.

    Args:
        tmp_path: The pytest ``tmp_path`` directory.

    Returns:
        An open, migrated :class:`sqlite3.Connection` with no users — the app
        built over it starts in first-run setup mode.
    """
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
    """Insert a user straight into *app_db*, bypassing the setup flow.

    Args:
        app_db: The open ``app.db`` connection.
        username: The login name.
        password: The plaintext password (hashed before storage).
        role: The account role.

    Returns:
        The created :class:`~appdb.users.User`.
    """
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
    """Insert an admin user straight into *app_db*.

    A convenience over :func:`seed_user` with ``role="admin"``, used by every
    test that needs the deployment to be past first-run setup.

    Args:
        app_db: The open ``app.db`` connection.
        username: The admin's login name.
        password: The admin's plaintext password.

    Returns:
        The created admin :class:`~appdb.users.User`.
    """
    return seed_user(app_db, username=username, password=password, role="admin")


def login(
    client: TestClient,
    *,
    username: str,
    password: str,
    remember: bool = False,
) -> Any:
    """Drive ``POST /api/auth/login`` and return the raw response.

    The client's cookie jar holds the ``search_session`` cookie afterwards on
    success, so subsequent requests on the same client are authenticated.

    Args:
        client: The ``TestClient`` over the app.
        username: The username to authenticate as.
        password: The password to authenticate with.
        remember: The "keep me signed in" flag.

    Returns:
        The :class:`httpx.Response` from the login call.
    """
    return client.post(
        "/api/auth/login",
        json={
            "username": username,
            "password": password,
            "remember": remember,
        },
    )
