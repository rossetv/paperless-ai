"""Helpers for the Library integration tests.

Re-exports the account helpers and adds :func:`seed_library_store`, which seeds
enough distinct documents to page, sort and filter.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

from store.models import ChunkInput, DocumentMeta, TaxonomyEntry
from store.writer import StoreWriter

# Re-exported so a Library test imports everything from one module.
from tests.integration.accounts_helpers import (  # noqa: F401
    build_account_client,
    login,
    make_mock_core,
    make_settings,
    open_app_db,
    seed_admin,
    seed_user,
)
from tests.helpers.search import mint_api_key

# The Library never exercises retrieval geometry; any vector of the right width works.
_AXIS_A: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0)

# The taxonomy ids the seeded documents reference.
CORRESPONDENT_GAS = 1
CORRESPONDENT_WATER = 2
DOC_TYPE_INVOICE = 10
DOC_TYPE_LETTER = 11
TAG_UTILITIES = 100
TAG_2024 = 101


def seed_library_store(settings: MagicMock) -> None:
    """Seed the index with five documents that differ on every sort and filter key.

    A reconcile timestamp is written so the store reports itself ready.

    Documents (id · title · correspondent · type · tags · created):
      1 · "Annual Report"      · British Gas  · Letter  · {2024}            · 2024-11-02
      2 · "Boiler Invoice"     · British Gas  · Invoice · {utilities,2024}  · 2024-03-15
      3 · "Census Letter"      · Water Board  · Letter  · {}                · 2023-07-01
      4 · "Direct Debit Form"  · Water Board  · Invoice · {utilities}       · 2022-01-09
      5 · "Energy Statement"   · British Gas  · Invoice · {utilities,2024}  · 2024-08-20
    """
    writer = StoreWriter(settings)
    try:
        writer.refresh_taxonomy(
            [
                TaxonomyEntry(
                    kind="correspondent",
                    id=CORRESPONDENT_GAS,
                    name="British Gas",
                ),
                TaxonomyEntry(
                    kind="correspondent",
                    id=CORRESPONDENT_WATER,
                    name="Water Board",
                ),
                TaxonomyEntry(
                    kind="document_type",
                    id=DOC_TYPE_INVOICE,
                    name="Invoice",
                ),
                TaxonomyEntry(
                    kind="document_type",
                    id=DOC_TYPE_LETTER,
                    name="Letter",
                ),
                TaxonomyEntry(kind="tag", id=TAG_UTILITIES, name="utilities"),
                TaxonomyEntry(kind="tag", id=TAG_2024, name="2024"),
            ]
        )
        documents = [
            (
                1,
                "Annual Report",
                CORRESPONDENT_GAS,
                DOC_TYPE_LETTER,
                (TAG_2024,),
                "2024-11-02T00:00:00Z",
                12,
            ),
            (
                2,
                "Boiler Invoice",
                CORRESPONDENT_GAS,
                DOC_TYPE_INVOICE,
                (TAG_UTILITIES, TAG_2024),
                "2024-03-15T00:00:00Z",
                1,
            ),
            (
                3,
                "Census Letter",
                CORRESPONDENT_WATER,
                DOC_TYPE_LETTER,
                (),
                "2023-07-01T00:00:00Z",
                3,
            ),
            (
                4,
                "Direct Debit Form",
                CORRESPONDENT_WATER,
                DOC_TYPE_INVOICE,
                (TAG_UTILITIES,),
                "2022-01-09T00:00:00Z",
                2,
            ),
            (
                5,
                "Energy Statement",
                CORRESPONDENT_GAS,
                DOC_TYPE_INVOICE,
                (TAG_UTILITIES, TAG_2024),
                "2024-08-20T00:00:00Z",
                4,
            ),
        ]
        for doc_id, title, corr, dtype, tags, created, pages in documents:
            meta = DocumentMeta(
                id=doc_id,
                title=title,
                correspondent_id=corr,
                document_type_id=dtype,
                tag_ids=tags,
                created=created,
                modified="2024-12-01T00:00:00Z",
                content_hash=f"hash-{doc_id}",
                page_count=pages,
            )
            chunk = ChunkInput(
                chunk_index=0,
                text=f"Body text of {title}.",
                page_hint=1,
                embedding=_AXIS_A,
            )
            writer.upsert_document(meta, [chunk])
        writer.write_meta("last_reconcile_at", "2024-12-01T00:00:00Z")
    finally:
        writer.close()


def mint_bearer(app_db: sqlite3.Connection) -> str:
    """Create an admin and an ``api``-scoped key for it; return the raw bearer token.

    ``GET /api/documents`` requires the ``api`` scope as well as the role.
    """
    from appdb.passwords import hash_password
    from appdb.users import create as create_user

    user = create_user(
        app_db,
        username="api-user",
        password_hash=hash_password("api-pw"),
        role="member",
    )
    return mint_api_key(app_db, owner_user_id=user.id, scopes="api")
