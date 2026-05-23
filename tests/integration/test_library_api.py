"""Integration tests for GET /api/documents — the Library browse endpoint.

Exercises the real FastAPI app via ``TestClient`` against a real seeded
``index.db`` and ``app.db``.  The five-document store from
``tests.integration.library_helpers.seed_library_store`` gives every sort
key, the pager, and every filter dimension something to act on.

Coverage:
- an authenticated Read-only user can list documents (paginated envelope)
- an unauthenticated request is rejected 401
- a DB-backed API-key Bearer token is accepted
- pagination — page/page_size slice the result, total is the full count
- sorting — by created, title, and added, ascending and descending
- filtering — correspondent, document type, tags, date range
- the in-library text query matches title and correspondent
- each document carries metadata and a page count (no deep-link URL)
- an out-of-range sort value is rejected 422

Note: the legacy SEARCH_API_KEY bearer was retired in Wave 3.  Bearer-auth
tests mint a real DB-backed API key via
:func:`tests.integration.library_helpers.mint_bearer`.
"""

from __future__ import annotations

from pathlib import Path

from store.reader import StoreReader
from tests.integration.library_helpers import (
    build_account_client,
    login,
    make_settings,
    mint_bearer,
    open_app_db,
    seed_admin,
    seed_library_store,
    seed_user,
)


def _bearer(key: str) -> dict[str, str]:
    """Return an Authorization header carrying a bearer token."""
    return {"Authorization": f"Bearer {key}"}


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------


class TestLibraryAuth:
    """GET /api/documents requires an authenticated Read-only user."""

    def test_readonly_user_can_list_documents(self, tmp_path: Path) -> None:
        """A logged-in Read-only user gets the paginated envelope."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_user(
                app_db,
                username="reader",
                password="reader-pw",
                role="readonly",
            )
            client = build_account_client(settings, app_db, store_reader)
            assert (
                login(client, username="reader", password="reader-pw").status_code
                == 200
            )
            response = client.get("/api/documents")
            assert response.status_code == 200
            body = response.json()
            assert body["total"] == 5
            assert body["page"] == 1
            assert "documents" in body
            assert "page_size" in body
        finally:
            store_reader.close()
            app_db.close()

    def test_unauthenticated_request_is_rejected(self, tmp_path: Path) -> None:
        """No session and no Bearer → 401."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            response = client.get("/api/documents")
            assert response.status_code == 401
        finally:
            store_reader.close()
            app_db.close()

    def test_api_key_bearer_token_is_accepted(self, tmp_path: Path) -> None:
        """A DB-backed API-key Bearer token authorises the browse."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get("/api/documents", headers=_bearer(raw_key))
            assert response.status_code == 200
            assert response.json()["total"] == 5
        finally:
            store_reader.close()
            app_db.close()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestLibraryPagination:
    """page and page_size slice the result; total is the full count."""

    def test_page_size_limits_the_documents_returned(self, tmp_path: Path) -> None:
        """A page_size of 2 returns two documents but total stays 5."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get(
                "/api/documents",
                params={"page": 1, "page_size": 2},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            body = response.json()
            assert len(body["documents"]) == 2
            assert body["total"] == 5
            assert body["page"] == 1
            assert body["page_size"] == 2
        finally:
            store_reader.close()
            app_db.close()

    def test_second_page_returns_the_next_slice(self, tmp_path: Path) -> None:
        """Page 2 with size 2 returns documents 3 and 4 in title order."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get(
                "/api/documents",
                params={
                    "page": 2,
                    "page_size": 2,
                    "sort": "title",
                    "descending": "false",
                },
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            titles = [d["title"] for d in response.json()["documents"]]
            # Title order: Annual, Boiler, Census, Direct Debit, Energy.
            assert titles == ["Census Letter", "Direct Debit Form"]
        finally:
            store_reader.close()
            app_db.close()

    def test_page_size_over_the_maximum_is_rejected(self, tmp_path: Path) -> None:
        """A page_size above MAX_PAGE_SIZE (100) is rejected 422 by FastAPI."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get(
                "/api/documents",
                params={"page_size": 500},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 422
        finally:
            store_reader.close()
            app_db.close()


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


class TestLibrarySorting:
    """The sort and descending parameters order the result."""

    def test_sort_by_created_descending(self, tmp_path: Path) -> None:
        """Descending created sort puts the newest document first."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get(
                "/api/documents",
                params={"sort": "created", "descending": "true"},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            ids = [d["id"] for d in response.json()["documents"]]
            # created: 2022 (4), 2023 (3), 2024-03 (2), 2024-08 (5), 2024-11 (1)
            assert ids == [1, 5, 2, 3, 4]
        finally:
            store_reader.close()
            app_db.close()

    def test_sort_by_title_ascending(self, tmp_path: Path) -> None:
        """Ascending title sort orders the documents alphabetically."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get(
                "/api/documents",
                params={"sort": "title", "descending": "false"},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            titles = [d["title"] for d in response.json()["documents"]]
            assert titles == [
                "Annual Report",
                "Boiler Invoice",
                "Census Letter",
                "Direct Debit Form",
                "Energy Statement",
            ]
        finally:
            store_reader.close()
            app_db.close()

    def test_sort_by_added_is_accepted(self, tmp_path: Path) -> None:
        """The 'added' sort (indexed_at) is accepted and returns all rows."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get(
                "/api/documents",
                params={"sort": "added"},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            assert response.json()["total"] == 5
        finally:
            store_reader.close()
            app_db.close()

    def test_out_of_range_sort_is_rejected(self, tmp_path: Path) -> None:
        """A sort value outside created/title/added is rejected 422."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get(
                "/api/documents",
                params={"sort": "relevance"},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 422
        finally:
            store_reader.close()
            app_db.close()


# ---------------------------------------------------------------------------
# Filtering and the in-library text query
# ---------------------------------------------------------------------------


class TestLibraryFiltering:
    """The filter and query parameters narrow the result."""

    def test_filter_by_correspondent(self, tmp_path: Path) -> None:
        """A correspondent filter keeps only that correspondent's documents."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            # correspondent_id 1 = British Gas → documents 1, 2, 5.
            response = client.get(
                "/api/documents",
                params={"correspondent_id": 1},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            body = response.json()
            assert body["total"] == 3
            assert {d["id"] for d in body["documents"]} == {1, 2, 5}
        finally:
            store_reader.close()
            app_db.close()

    def test_filter_by_document_type(self, tmp_path: Path) -> None:
        """A document-type filter keeps only documents of that type."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            # document_type_id 11 = Letter → documents 1, 3.
            response = client.get(
                "/api/documents",
                params={"document_type_id": 11},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            assert {d["id"] for d in response.json()["documents"]} == {1, 3}
        finally:
            store_reader.close()
            app_db.close()

    def test_filter_by_tag(self, tmp_path: Path) -> None:
        """A tag filter keeps only documents carrying that tag."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            # tag_ids 100 = utilities → documents 2, 4, 5.
            response = client.get(
                "/api/documents",
                params={"tag_ids": [100]},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            assert {d["id"] for d in response.json()["documents"]} == {2, 4, 5}
        finally:
            store_reader.close()
            app_db.close()

    def test_filter_by_date_range(self, tmp_path: Path) -> None:
        """A date range keeps only documents created within it."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            # 2024 only → documents 1, 2, 5.
            response = client.get(
                "/api/documents",
                params={
                    "date_from": "2024-01-01",
                    "date_to": "2024-12-31",
                },
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            assert {d["id"] for d in response.json()["documents"]} == {1, 2, 5}
        finally:
            store_reader.close()
            app_db.close()

    def test_text_query_matches_title(self, tmp_path: Path) -> None:
        """The in-library text query matches a document title."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get(
                "/api/documents",
                params={"query": "boiler"},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            body = response.json()
            assert body["total"] == 1
            assert body["documents"][0]["id"] == 2
        finally:
            store_reader.close()
            app_db.close()

    def test_text_query_matches_correspondent_name(self, tmp_path: Path) -> None:
        """The text query matches against the correspondent name too."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get(
                "/api/documents",
                params={"query": "water board"},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            # Water Board is correspondent of documents 3 and 4.
            assert {d["id"] for d in response.json()["documents"]} == {3, 4}
        finally:
            store_reader.close()
            app_db.close()


# ---------------------------------------------------------------------------
# The per-document payload
# ---------------------------------------------------------------------------


class TestLibraryDocumentPayload:
    """Each document carries the full Library-card payload."""

    def test_document_carries_metadata_and_page_count(self, tmp_path: Path) -> None:
        """A document exposes names, tags, and page count — no deep-link URL."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get(
                "/api/documents",
                params={"query": "boiler"},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            doc = response.json()["documents"][0]
            assert doc["id"] == 2
            assert doc["title"] == "Boiler Invoice"
            assert doc["correspondent"] == "British Gas"
            assert doc["document_type"] == "Invoice"
            assert doc["created"] == "2024-03-15T00:00:00Z"
            assert doc["page_count"] == 1
            assert set(doc["tags"]) == {"utilities", "2024"}
            assert "paperless_url" not in doc
        finally:
            store_reader.close()
            app_db.close()

    def test_page_count_none_is_serialised_as_null(self, tmp_path: Path) -> None:
        """A document with no page count serialises ``page_count`` as null."""
        from store.models import ChunkInput, DocumentMeta
        from store.writer import StoreWriter

        settings = make_settings(tmp_path)
        seed_library_store(settings)
        # Add a sixth document whose page_count is None.
        writer = StoreWriter(settings)
        try:
            meta = DocumentMeta(
                id=6,
                title="No Page Count",
                correspondent_id=None,
                document_type_id=None,
                tag_ids=(),
                created="2025-01-01T00:00:00Z",
                modified="2025-01-01T00:00:00Z",
                content_hash="hash-6",
                page_count=None,
            )
            chunk = ChunkInput(
                chunk_index=0,
                text="No page count document.",
                page_hint=1,
                embedding=(1.0, 0.0, 0.0, 0.0),
            )
            writer.upsert_document(meta, [chunk])
        finally:
            writer.close()

        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get(
                "/api/documents",
                params={"query": "no page count"},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 200
            body = response.json()
            assert body["total"] == 1
            assert body["documents"][0]["page_count"] is None
        finally:
            store_reader.close()
            app_db.close()


# ---------------------------------------------------------------------------
# Input-bounds validation
# ---------------------------------------------------------------------------


class TestLibraryInputBounds:
    """FastAPI rejects out-of-bound query parameters with 422."""

    def test_page_over_the_maximum_is_rejected(self, tmp_path: Path) -> None:
        """A page value above MAX_PAGE_NUMBER (10 000) is rejected 422."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get(
                "/api/documents",
                params={"page": 99_999},
                headers=_bearer(raw_key),
            )
            assert response.status_code == 422
        finally:
            store_reader.close()
            app_db.close()

    def test_too_many_tag_ids_is_rejected(self, tmp_path: Path) -> None:
        """More than 64 tag_ids in a single request is rejected 422."""
        settings = make_settings(tmp_path)
        seed_library_store(settings)
        app_db = open_app_db(tmp_path)
        store_reader = StoreReader(settings)
        try:
            seed_admin(app_db, username="boss", password="boss-pw")
            client = build_account_client(settings, app_db, store_reader)
            raw_key = mint_bearer(app_db)
            response = client.get(
                "/api/documents",
                params={"tag_ids": list(range(1, 66))},  # 65 ids — over the limit
                headers=_bearer(raw_key),
            )
            assert response.status_code == 422
        finally:
            store_reader.close()
            app_db.close()
