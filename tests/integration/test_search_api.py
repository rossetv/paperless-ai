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
from tests.helpers.llm import (
    ScriptedLLMClient,
    _make_spec,
    answered_response_json,
    planner_response_json,
)
from tests.helpers.search import build_search_core, mint_api_key

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
    # The search handler sizes the semaphore from the core's settings; give the
    # stub a real int-typed settings object so set_limit receives an int.
    core.settings = make_search_settings()
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


# ---------------------------------------------------------------------------
# Mid-rebuild — a schema-less index returns 503, never 500 (M9)
# ---------------------------------------------------------------------------


def _make_schemaless_index(tmp_path: Path) -> None:
    """Create a present-but-schema-less index DB at the settings path.

    sqlite3.connect() auto-creates an empty file; the indexer drops the schema
    and recreates it mid-rebuild, so for a brief window the file exists with no
    taxonomy table — exactly the state a real StoreReader sees here.
    """
    import sqlite3 as _sqlite3

    db_path = tmp_path / "index.db"
    conn = _sqlite3.connect(str(db_path))
    conn.close()
    assert db_path.exists()


def _real_core(settings: MagicMock, store_reader: StoreReader) -> object:
    """Build a real SearchCore so list_facets actually runs against the store.

    The mock core in :func:`_make_mock_core` never touches the store; this test
    needs the real pipeline so the schema-less ``list_facets`` raises
    ``SchemaNotReadyError`` and the route's 503 mapping is exercised end to end.
    """
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(specs=[_make_spec(semantic="anything")]),
        synthesiser_responses=[answered_response_json("unused", citations=[])],
    )
    embedding_client = MagicMock()
    embedding_client.embed.return_value = [[1.0, 0.0, 0.0, 0.0]]
    return build_search_core(
        settings=settings,
        llm_client=llm_client,
        store_reader=store_reader,
        embedding_client=embedding_client,
    )


class TestSearchMidRebuildReturns503:
    """A search against a schema-less (mid-rebuild) index returns 503, not 500 (M9).

    The pipeline reads the live taxonomy at the top of every search; a
    mid-rebuild window — schema dropped, not yet recreated — makes that read
    raise ``SchemaNotReadyError``. Before the fix it bubbled out as an uncaught
    500 on the billable endpoint; it must now map to a 503 index-not-ready, the
    same contract /api/facets, /api/stats, and the Library browse already honour.
    """

    def test_search_returns_503_when_schema_missing(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        _make_schemaless_index(tmp_path)
        store_reader = StoreReader(settings)
        try:
            from search.api import create_app

            core = _real_core(settings, store_reader)
            app = create_app(settings, core=core, store_reader=store_reader)
            client = TestClient(
                app, raise_server_exceptions=False, base_url="https://testserver"
            )
            raw_key = _seed_api_key(settings)
            response = client.post(
                "/api/search",
                json={"query": "invoices 2025"},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 503
        finally:
            store_reader.close()

    def test_facets_returns_503_when_schema_missing(self, tmp_path: Path) -> None:
        """The sibling endpoint the search now matches: facets is 503 too."""
        settings = _make_settings(tmp_path)
        _make_schemaless_index(tmp_path)
        store_reader = StoreReader(settings)
        try:
            client = _build_client(settings, store_reader)
            raw_key = _seed_api_key(settings)
            response = client.get("/api/facets", headers=_bearer(raw_key))
            assert response.status_code == 503
        finally:
            store_reader.close()

    def test_stats_returns_503_when_schema_missing(self, tmp_path: Path) -> None:
        """And /api/stats, which surfaces SchemaNotReadyError from get_stats."""
        settings = _make_settings(tmp_path)
        _make_schemaless_index(tmp_path)
        store_reader = StoreReader(settings)
        try:
            client = _build_client(settings, store_reader)
            raw_key = _seed_api_key(settings)
            response = client.get("/api/stats", headers=_bearer(raw_key))
            assert response.status_code == 503
        finally:
            store_reader.close()


# ---------------------------------------------------------------------------
# M12 — HTTP and MCP share ONE concurrency semaphore (not 2N)
# ---------------------------------------------------------------------------


class TestSharedConcurrencyBound:
    """The app factory injects the same LazySemaphore into both surfaces."""

    def test_http_and_mcp_share_the_same_semaphore_object(self, tmp_path: Path) -> None:
        """SEARCH_MAX_CONCURRENT must be one ceiling, not one per surface (M12).

        Before the fix, ``build_api_router`` and ``build_mcp_app`` each created
        their own ``LazySemaphore``, so the real cap was 2N. The app factory now
        creates one and injects the same instance into both; this test captures
        the semaphore each builder receives and asserts they are the *same*
        object.
        """
        from unittest.mock import patch

        import search.api as api_module

        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)

        captured: dict[str, object] = {}
        real_build_api_router = api_module.build_api_router
        real_build_mcp_app = api_module.build_mcp_app

        def spy_api_router(*args, **kwargs):
            captured["http"] = kwargs["search_semaphore"]
            return real_build_api_router(*args, **kwargs)

        def spy_mcp_app(*args, **kwargs):
            captured["mcp"] = kwargs["search_semaphore"]
            return real_build_mcp_app(*args, **kwargs)

        try:
            with (
                patch.object(api_module, "build_api_router", spy_api_router),
                patch.object(api_module, "build_mcp_app", spy_mcp_app),
            ):
                from search.api import create_app

                core = _make_mock_core()
                create_app(settings, core=core, store_reader=store_reader)

            assert "http" in captured and "mcp" in captured
            # The SAME object backs both surfaces — one ceiling across HTTP+MCP.
            assert captured["http"] is captured["mcp"]
        finally:
            store_reader.close()


# ---------------------------------------------------------------------------
# Security headers — defence-in-depth on every response
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    """The global middleware stamps the security-header set on every response.

    Covers both an API response (a JSON route) and an SPA response (the
    ``index.html`` deep-link shell) so the headers are proven present on both
    surfaces, and the CSP is asserted to be SPA-safe (allows the inline
    theme-bootstrap script and runtime-injected styles).
    """

    def _assert_security_headers(self, headers) -> None:
        """Assert the full conservative header set is present and correct."""
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "max-age=31536000" in headers["strict-transport-security"]
        assert "includeSubDomains" in headers["strict-transport-security"]
        csp = headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp
        assert "base-uri 'self'" in csp
        # SPA-safe: the built index.html carries one inline script and the
        # Vite/React runtime injects <style> elements, so both must be allowed
        # or the app blanks. (See web/dist/index.html.)
        assert "'unsafe-inline'" in csp

    def test_headers_present_on_an_api_response(self, tmp_path: Path) -> None:
        """The security headers are on a JSON API response (healthz)."""
        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            client = _build_client(settings, store_reader)
            response = client.get("/api/healthz")
            assert response.status_code == 200
            self._assert_security_headers(response.headers)
        finally:
            store_reader.close()

    def test_headers_present_on_an_spa_response(self, tmp_path: Path) -> None:
        """The security headers are on the SPA index.html deep-link shell.

        ``search.api`` reads ``FRONTEND_DIST`` at import time, so a fake built
        ``dist`` is supplied via the env var and the module reloaded before
        ``create_app`` — the Python CI job does not build ``web/dist``, so the
        test must not depend on the real build being present.
        """
        import importlib
        import os

        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text(
            "<!doctype html><html><body><div id=root></div></body></html>"
        )

        os.environ["FRONTEND_DIST"] = str(dist)
        import search.api as search_api

        importlib.reload(search_api)
        try:
            settings = _make_settings(tmp_path)
            _seed_store(settings)
            store_reader = StoreReader(settings)
            try:
                app = search_api.create_app(
                    settings, core=_make_mock_core(), store_reader=store_reader
                )
                client = TestClient(
                    app, raise_server_exceptions=False, base_url="https://testserver"
                )
                response = client.get("/login")
                assert response.status_code == 200
                assert "text/html" in response.headers["content-type"]
                self._assert_security_headers(response.headers)
            finally:
                store_reader.close()
        finally:
            os.environ.pop("FRONTEND_DIST", None)
            importlib.reload(search_api)


# ---------------------------------------------------------------------------
# Refreshable price book — startup load, background refresh, response provenance
# ---------------------------------------------------------------------------


def _real_core_over_seeded_store(
    settings: MagicMock, store_reader: StoreReader
) -> object:
    """Build a real SearchCore that answers from the seeded store.

    The scripted planner returns one semantic spec matching the seeded chunk;
    the embedding client returns ``_AXIS_A`` (the seeded chunk's vector), so
    retrieval finds the document and the synthesiser produces an answer. Used by
    the price-book tests so the cost summary carries the live book's provenance
    rather than a mock core's fixed result.
    """
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(specs=[_make_spec(semantic="gas bill")]),
        synthesiser_responses=[
            answered_response_json("The bill is £198.", citations=[100])
        ],
    )
    embedding_client = MagicMock()
    embedding_client.embed.return_value = [list(_AXIS_A)]
    return build_search_core(
        settings=settings,
        llm_client=llm_client,
        store_reader=store_reader,
        embedding_client=embedding_client,
    )


def _seed_price_cache(settings: MagicMock, *, source: str, as_of: str) -> None:
    """Write one model_pricing cache row into the create_app-migrated app.db.

    Opens a second connection to ``settings.APP_DB_PATH`` (already migrated by
    create_app) and replaces the cache, mirroring the per-request connection
    pattern the other seed helpers use.
    """
    from appdb.connection import connect
    from appdb.model_pricing import CachedModelPrice, save_cached_prices

    conn = connect(settings.APP_DB_PATH)
    try:
        save_cached_prices(
            conn,
            table={
                "gpt-5.4": CachedModelPrice(input_per_mtok=1.0, output_per_mtok=4.0)
            },
            as_of=as_of,
            source=source,
            fetched_at="2026-07-01T00:00:00+00:00",
        )
    finally:
        conn.close()


class TestPriceBookWiring:
    """The live price book reaches the cost summary; refresh is opt-in only.

    The headline guarantee: with ``PRICING_REFRESH_URL`` unset (prod's default),
    create_app starts NO refresh thread and makes NO network call, and the cost
    summary reports the bundled seed's provenance — byte-identical behaviour.
    """

    def _search(
        self, settings: MagicMock, store_reader: StoreReader
    ) -> dict[str, object]:
        """Run one authorised search against a real core; return the JSON body."""
        from search.api import create_app

        core = _real_core_over_seeded_store(settings, store_reader)
        app = create_app(settings, core=core, store_reader=store_reader)
        client = TestClient(
            app, raise_server_exceptions=False, base_url="https://testserver"
        )
        raw_key = _seed_api_key(settings)
        response = client.post(
            "/api/search",
            json={"query": "gas bill amount"},
            headers=_bearer(raw_key),
        )
        assert response.status_code == 200
        return response.json()

    def test_no_url_starts_no_refresh_thread_and_no_network(
        self, tmp_path: Path
    ) -> None:
        """The prod default: empty URL ⇒ no refresh thread, zero network calls.

        respx with ``assert_all_mocked`` and no routes turns any outbound HTTP
        into an error, so a passing test proves create_app made none. The
        refresh thread is also asserted absent by name.
        """
        import threading

        import respx

        settings = _make_settings(tmp_path)
        assert settings.PRICING_REFRESH_URL == ""  # the behaviour-preserving default
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            from search.api import create_app

            core = _make_mock_core()
            with respx.mock(assert_all_mocked=True):
                create_app(settings, core=core, store_reader=store_reader)
            # No background price-refresh thread was started.
            assert not any(
                t.name == "search-price-refresh" for t in threading.enumerate()
            )
        finally:
            store_reader.close()

    def test_no_url_search_reports_bundled_seed_provenance(
        self, tmp_path: Path
    ) -> None:
        """With no URL the cost summary carries the bundled seed's as-of + source.

        Proves the only visible addition on the default path: the cost figure now
        also reports where the prices came from — and they come from the seed.
        """
        from search.pricing import SEED_PRICES_AS_OF

        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            body = self._search(settings, store_reader)
            cost = body["cost"]
            assert cost["prices_source"] == "bundled"
            assert cost["prices_as_of"] == SEED_PRICES_AS_OF
            # The default path is honestly priced (zero scripted tokens → $0),
            # never None — the seed prices every prod model.
            assert cost["usd"] == 0.0
        finally:
            store_reader.close()

    def test_startup_loads_the_app_db_price_cache(self, tmp_path: Path) -> None:
        """A pre-existing model_pricing cache becomes the live book at startup.

        create_app migrates app.db first, so seed the cache, then build the app
        again over the same path: the live book — and therefore the search's
        cost provenance — is the cached source/as-of, not the seed.
        """
        from search.api import create_app

        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            # First build migrates app.db (so the table exists to seed).
            create_app(settings, core=_make_mock_core(), store_reader=store_reader)
            _seed_price_cache(
                settings,
                source="https://prices.example/openai.json",
                as_of="2026-07-01",
            )
            # Second build loads the just-seeded cache into the live book.
            body = self._search(settings, store_reader)
            cost = body["cost"]
            assert cost["prices_source"] == "https://prices.example/openai.json"
            assert cost["prices_as_of"] == "2026-07-01"
        finally:
            store_reader.close()

    def test_background_refresh_persists_and_publishes(self, tmp_path: Path) -> None:
        """A configured URL refreshes once, persists the cache, and swaps the book.

        The refresh helper is driven directly (no real multi-hour sleep) against
        a respx-mocked URL; it must save the fetched table to app.db and publish
        it as the live book.
        """
        import httpx
        import respx

        from appdb.connection import connect
        from appdb.model_pricing import load_cached_prices
        from search.api import _refresh_once
        from search.pricing_book import get_current_price_book

        url = "https://prices.example/openai.json"
        payload = {
            "as_of": "2026-08-15",
            "currency": "USD",
            "models": {"gpt-5.5": {"input_per_mtok": 7.0, "output_per_mtok": 33.0}},
        }
        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            # Migrate app.db so the cache write target exists.
            create_app_path = settings.APP_DB_PATH
            from search.api import create_app

            create_app(settings, core=_make_mock_core(), store_reader=store_reader)

            with respx.mock:
                respx.get(url).mock(return_value=httpx.Response(200, json=payload))
                _refresh_once(url, create_app_path)

            # Published as the live book.
            live = get_current_price_book()
            assert live.source == url
            assert live.as_of == "2026-08-15"
            # Persisted to app.db so it survives a restart.
            conn = connect(create_app_path)
            try:
                cached = load_cached_prices(conn)
            finally:
                conn.close()
            assert cached is not None
            assert cached.source == url and cached.as_of == "2026-08-15"
        finally:
            store_reader.close()

    def test_refresh_failure_keeps_the_previous_book(self, tmp_path: Path) -> None:
        """A failed fetch logs and keeps the current book — it never crashes."""
        import httpx
        import respx

        from search.api import _refresh_once
        from search.pricing_book import (
            BUNDLED_SOURCE,
            get_current_price_book,
            reset_current_price_book,
        )

        url = "https://prices.example/openai.json"
        settings = _make_settings(tmp_path)
        store_reader = StoreReader(settings)
        try:
            reset_current_price_book()  # start from the seed
            from search.api import create_app

            create_app(settings, core=_make_mock_core(), store_reader=store_reader)
            with respx.mock:
                respx.get(url).mock(return_value=httpx.Response(503, text="down"))
                # Must not raise — a flaky host never crashes the server.
                _refresh_once(url, settings.APP_DB_PATH)
            # The seed book is untouched.
            assert get_current_price_book().source == BUNDLED_SOURCE
        finally:
            store_reader.close()

    def test_cost_response_carries_provenance_fields(self, tmp_path: Path) -> None:
        """The wire response exposes prices_as_of and prices_source for the UI."""
        settings = _make_settings(tmp_path)
        _seed_store(settings)
        store_reader = StoreReader(settings)
        try:
            body = self._search(settings, store_reader)
            cost = body["cost"]
            assert "prices_as_of" in cost
            assert "prices_source" in cost
        finally:
            store_reader.close()
