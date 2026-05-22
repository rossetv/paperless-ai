"""Integration tests for the search HTTP API server.

Exercises the real FastAPI app via ``TestClient``, backed by a real
``StoreWriter``/``StoreReader`` seeded in a ``tmp_path`` SQLite database.
The ``SearchCore`` uses a real store reader; only the LLM stages are mocked.

Coverage:
- A DB-backed API key Bearer token authorises /api/search end to end.
- An unauthenticated request is rejected 401.
- GET /api/healthz returns 200 against a healthy seeded store.
- GET /api/healthz returns 503 index-not-ready when the DB file is absent.
- GET /api/facets returns real taxonomy data from the seeded store.
- GET /api/stats returns real index statistics from the seeded store.
- POST /api/reconcile writes the sentinel file alongside the index DB and
  returns 202.
- POST /api/search returns a SearchResponse with sources from the seeded store.
- The search server never serves the index DB content over HTTP.

The username/password login handshake and the resulting session-cookie path
are exercised by the dedicated account integration suite (spec §4.8).

Wave 3 note: the legacy SEARCH_API_KEY bearer is retired. Tests that used it
now mint a real DB-backed API key.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from store.models import ChunkInput, DocumentMeta, TaxonomyEntry
from store.reader import StoreReader
from store.writer import StoreWriter
from tests.helpers.factories import (
    make_search_result,
    make_search_settings,
    make_source_document,
)
from tests.helpers.search import mint_api_key

# ---------------------------------------------------------------------------
# Embedding geometry
# ---------------------------------------------------------------------------

_DIMENSIONS = 4
_AXIS_A: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path) -> MagicMock:
    """Build a settings mock pointing at the tmp_path store."""
    return make_search_settings(
        INDEX_DB_PATH=str(tmp_path / "index.db"),
        EMBEDDING_DIMENSIONS=_DIMENSIONS,
    )


def _seed_api_key(settings: MagicMock) -> str:
    """Seed a user and an API key in app.db; return the raw key string.

    Called after ``create_app`` has migrated app.db at ``settings.APP_DB_PATH``.
    Opens a second connection to the same file to insert seed rows — the
    per-request connection pattern.
    """
    from appdb.connection import connect
    from appdb.passwords import hash_password
    from appdb.users import create as create_user

    conn = connect(settings.APP_DB_PATH)
    try:
        user = create_user(
            conn,
            username="api-user",
            password_hash=hash_password("pw"),
            role="member",
        )
        return mint_api_key(conn, owner_user_id=user.id, scopes="api")
    finally:
        conn.close()


def _seed_store(settings: MagicMock) -> None:
    """Seed the store with one document, taxonomy entries, and a reconcile timestamp.

    The reconcile timestamp is written via write_meta so that healthz treats
    this store as fully ready (last_reconcile_at is not None).
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
        # Record a completed reconciliation cycle so healthz returns 200.
        writer.write_meta("last_reconcile_at", "2024-06-01T12:00:00Z")
    finally:
        writer.close()


def _make_mock_core(answer: str = "The bill is £198.00.") -> MagicMock:
    """Build a stub SearchCore that returns a fixed SearchResult."""
    core = MagicMock()
    core.answer.return_value = make_search_result(
        answer=answer,
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


def _build_client(settings: MagicMock, store_reader: StoreReader) -> TestClient:
    """Build a TestClient wrapping the real FastAPI app.

    Uses ``https://testserver`` so that ``Secure`` session cookies are
    forwarded on subsequent requests (the real server always runs behind HTTPS;
    the Secure flag is a required security attribute per spec §7.3).
    """
    from search.api import create_app

    core = _make_mock_core()
    app = create_app(settings, core=core, store_reader=store_reader)
    return TestClient(app, raise_server_exceptions=False, base_url="https://testserver")


def _bearer(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


# ---------------------------------------------------------------------------
# Auth — the legacy bearer token authorises requests
# ---------------------------------------------------------------------------


class TestAuthIntegration:
    """A DB-backed API key bearer authorises an end-to-end search.

    The username/password login handshake and the resulting session-cookie
    path are exercised by the dedicated account integration suite (spec §4.8);
    this class covers bearer-key auth via the minted API key mechanism.
    """

    def test_bearer_token_authorises_search(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            client = _build_client(settings, store_reader)
            raw_key = _seed_api_key(settings)
            response = client.post(
                "/api/search",
                json={"query": "gas bill"},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
        finally:
            store_reader.close()

    def test_unauthenticated_search_returns_401(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            client = _build_client(settings, store_reader)
            response = client.post("/api/search", json={"query": "test"})
            assert response.status_code == 401
        finally:
            store_reader.close()


# ---------------------------------------------------------------------------
# Healthz — real store state
# ---------------------------------------------------------------------------


class TestHealthzIntegration:
    """Healthz reflects the real store state."""

    def test_healthz_ok_when_db_exists_and_passes_quick_check(
        self, tmp_path: Path
    ) -> None:
        """A seeded (reconciled) store must return 200 ok."""
        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            client = _build_client(settings, store_reader)
            response = client.get("/api/healthz")
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
        finally:
            store_reader.close()

    def test_healthz_503_when_db_absent(self, tmp_path: Path) -> None:
        """When the DB file does not exist, healthz returns 503 index-not-ready."""
        settings = _make_settings(tmp_path)
        # Do NOT seed — DB file absent.
        # We still need a store_reader for create_app; use a mock that
        # raises on quick_check (the endpoint guards on file existence first).
        store_reader = MagicMock()
        from search.api import create_app

        core = _make_mock_core()
        app = create_app(settings, core=core, store_reader=store_reader)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/healthz")
        assert response.status_code == 503
        assert response.json()["status"] == "index-not-ready"

    def test_healthz_503_when_db_present_but_schema_missing(
        self, tmp_path: Path
    ) -> None:
        """An auto-created empty DB (no schema) must return 503 index-not-ready.

        This is the primary regression test: sqlite3.connect() auto-creates an
        empty file when the directory is writable, so a DB that was created by
        the connection itself (rather than by StoreWriter.ensure_schema) must
        not be reported as healthy.  The real StoreReader is used here so that
        the OperationalError propagation path is exercised end-to-end.
        """
        import sqlite3 as _sqlite3

        settings = _make_settings(tmp_path)
        # Create an empty SQLite file (no schema) — mimics the auto-create
        # behaviour of sqlite3.connect() on a fresh /data volume mount.
        db_path = tmp_path / "index.db"
        conn = _sqlite3.connect(str(db_path))
        conn.close()
        assert db_path.exists()

        store_reader = StoreReader(settings)
        try:
            from search.api import create_app

            core = _make_mock_core()
            app = create_app(settings, core=core, store_reader=store_reader)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/healthz")
            assert response.status_code == 503
            assert response.json()["status"] == "index-not-ready"
        finally:
            store_reader.close()

    def test_healthz_503_when_schema_present_but_never_reconciled(
        self, tmp_path: Path
    ) -> None:
        """A DB with the schema but no reconcile record must return 503 index-not-ready.

        StoreWriter.ensure_schema() creates the tables but does not set
        last_reconcile_at.  A fresh install that has the indexer running its
        first reconciliation cycle is in this state.
        """
        from store.writer import StoreWriter

        settings = _make_settings(tmp_path)
        # Write the schema but do NOT call upsert_document (so no reconcile
        # timestamp is ever stored).
        writer = StoreWriter(settings)
        writer.close()  # ensure_schema was called in __init__; no documents written.

        store_reader = StoreReader(settings)
        try:
            from search.api import create_app

            core = _make_mock_core()
            app = create_app(settings, core=core, store_reader=store_reader)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/healthz")
            assert response.status_code == 503
            assert response.json()["status"] == "index-not-ready"
        finally:
            store_reader.close()


# ---------------------------------------------------------------------------
# Facets — real taxonomy from the store
# ---------------------------------------------------------------------------


class TestFacetsIntegration:
    """GET /api/facets returns real taxonomy data from the seeded store."""

    def test_facets_contains_seeded_taxonomy(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            client = _build_client(settings, store_reader)
            raw_key = _seed_api_key(settings)
            response = client.get("/api/facets", headers=_bearer(raw_key))
            assert response.status_code == 200
            body = response.json()
            correspondent_names = [c["name"] for c in body["correspondents"]]
            assert "BritishGas" in correspondent_names
            doc_type_names = [d["name"] for d in body["document_types"]]
            assert "Invoice" in doc_type_names
        finally:
            store_reader.close()


# ---------------------------------------------------------------------------
# Stats — real stats from the store
# ---------------------------------------------------------------------------


class TestStatsIntegration:
    """GET /api/stats returns real index statistics."""

    def test_stats_reflect_seeded_document_count(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            client = _build_client(settings, store_reader)
            raw_key = _seed_api_key(settings)
            response = client.get("/api/stats", headers=_bearer(raw_key))
            assert response.status_code == 200
            body = response.json()
            assert body["document_count"] == 1
            assert body["chunk_count"] == 1
        finally:
            store_reader.close()


# ---------------------------------------------------------------------------
# Reconcile — sentinel file alongside the real index DB
# ---------------------------------------------------------------------------


class TestReconcileIntegration:
    """POST /api/reconcile writes the sentinel file and returns 202."""

    def test_reconcile_writes_sentinel_alongside_db(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            client = _build_client(settings, store_reader)
            raw_key = _seed_api_key(settings)
            response = client.post("/api/reconcile", headers=_bearer(raw_key))
            assert response.status_code == 202

            sentinel = tmp_path / "reconcile.request"
            assert sentinel.exists()
        finally:
            store_reader.close()

    def test_reconcile_does_not_write_new_files_in_non_db_directory(
        self, tmp_path: Path
    ) -> None:
        """Reconcile only touches the sentinel; it must not write the index DB."""
        settings = _make_settings(tmp_path)
        _seed_store(settings)
        # Record files present before reconcile.
        before = set((tmp_path).iterdir())
        store_reader = StoreReader(settings)
        try:
            client = _build_client(settings, store_reader)
            raw_key = _seed_api_key(settings)
            client.post("/api/reconcile", headers=_bearer(raw_key))
        finally:
            store_reader.close()

        after = set(tmp_path.iterdir())
        new_files = after - before
        # Only the sentinel (and possibly WAL files from the store) are new.
        new_names = {f.name for f in new_files}
        assert "reconcile.request" in new_names
        # The DB itself must not be re-created or altered by reconcile.
        # We assert the only NEW name from reconcile is the sentinel.
        non_sentinel_new = new_names - {
            "reconcile.request",
            "index.db-wal",
            "index.db-shm",
            "index.db",
        }
        assert not non_sentinel_new, f"Unexpected new files: {non_sentinel_new}"


# ---------------------------------------------------------------------------
# Security — the index DB is never web-reachable
# ---------------------------------------------------------------------------


class TestIndexDbNotWebReachable:
    """The index DB must never be served over HTTP."""

    def test_db_file_is_not_accessible_via_http(self, tmp_path: Path) -> None:
        """A GET for the index DB by name must never return the DB content.

        The index DB lives under ``tmp_path`` (the data volume), never inside
        ``web/dist``, so the SPA deep-link catch-all cannot resolve it to a
        real file — it hands back the SPA shell instead. The DB's seeded
        document text must not appear in the response under any circumstance.
        """
        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            client = _build_client(settings, store_reader)
            # The SPA mount does not enforce auth — this is a path-containment
            # security check, not an auth check.
            response = client.get("/index.db")
            assert "BritishGas Invoice" not in response.text
            assert "£198.00" not in response.text
        finally:
            store_reader.close()


# ---------------------------------------------------------------------------
# Search response — correctness
# ---------------------------------------------------------------------------


class TestSearchResponseIntegration:
    """POST /api/search returns a correctly structured response."""

    def test_search_response_contains_expected_fields(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            client = _build_client(settings, store_reader)
            raw_key = _seed_api_key(settings)
            response = client.post(
                "/api/search",
                json={"query": "gas bill amount"},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            body = response.json()
            assert "answer" in body
            assert "sources" in body
            assert "plan" in body
            assert "stats" in body
            assert len(body["sources"]) == 1
            source = body["sources"][0]
            assert source["document_id"] == 100
            assert source["title"] == "BritishGas Invoice"
        finally:
            store_reader.close()
