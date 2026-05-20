"""Shared fixtures for the store unit tests.

Provides:

- ``db_path`` — a fresh ``tmp_path`` SQLite path every store test uses.
- ``populated_db`` — a store seeded with two documents, their chunks, and a
  taxonomy, shared by the reader test files (split for the 500-line ceiling).
- :func:`unit_vec` — an axis-aligned unit vector, the deterministic embedding
  the ranking tests need (distinct from the all-equal vector the generic
  factories produce).
"""

from __future__ import annotations

from typing import Any

import pytest

from store.models import ChunkInput, DocumentMeta, TaxonomyEntry
from tests.helpers.store import open_writer


@pytest.fixture()
def db_path(tmp_path: Any) -> str:
    """Return a fresh, unique index-database path inside ``tmp_path``."""
    return str(tmp_path / "store_test.db")


def unit_vec(dimensions: int, axis: int) -> tuple[float, ...]:
    """Return a unit vector with ``1.0`` on *axis* and ``0.0`` elsewhere.

    The ranking tests need embeddings whose pairwise cosine distances are known
    exactly: two identical axis vectors have distance ``0.0``, orthogonal ones
    distance ``1.0``.  This is distinct from
    :func:`tests.helpers.factories.make_embedding`, whose all-equal vector
    cannot distinguish chunks for a ranking assertion.
    """
    vec = [0.0] * dimensions
    vec[axis] = 1.0
    return tuple(vec)


@pytest.fixture()
def populated_db(db_path: str) -> str:
    """Seed the store with two documents, their chunks, and a taxonomy.

    Document 1:
        - correspondent_id=10 ("Alpha Corp"), document_type_id=20 ("Invoice")
        - tag_ids=(101, 102), created="2023-01-01T00:00:00+00:00"
        - chunk 0 embedding on axis 0; chunk 1 on axis 1
    Document 2:
        - correspondent_id=11 ("Beta Ltd"), document_type_id=None
        - tag_ids=(102,), created="2024-06-15T00:00:00+00:00"
        - chunk 0 embedding on axis 2; chunk 1 on axis 3

    Tag 101 belongs only to document 1, so a ``tag_ids=(101,)`` filter isolates
    it; the axis-aligned chunk embeddings make every ranking outcome exact.

    Returns:
        The database path, ready to open with a StoreReader.
    """
    writer = open_writer(db_path)

    writer.refresh_taxonomy(
        [
            TaxonomyEntry(kind="correspondent", id=10, name="Alpha Corp"),
            TaxonomyEntry(kind="correspondent", id=11, name="Beta Ltd"),
            TaxonomyEntry(kind="document_type", id=20, name="Invoice"),
            TaxonomyEntry(kind="tag", id=101, name="important"),
            TaxonomyEntry(kind="tag", id=102, name="scanned"),
        ]
    )

    writer.upsert_document(
        DocumentMeta(
            id=1,
            title="Alpha Invoice",
            correspondent_id=10,
            document_type_id=20,
            tag_ids=(101, 102),
            created="2023-01-01T00:00:00+00:00",
            modified="2023-03-01T00:00:00+00:00",
            content_hash="hash1",
            page_count=1,
        ),
        [
            ChunkInput(
                chunk_index=0,
                text="boiler warranty letter",
                page_hint=1,
                embedding=unit_vec(4, 0),
            ),
            ChunkInput(
                chunk_index=1,
                text="invoice total amount due",
                page_hint=1,
                embedding=unit_vec(4, 1),
            ),
        ],
    )

    writer.upsert_document(
        DocumentMeta(
            id=2,
            title="Beta Scan",
            correspondent_id=11,
            document_type_id=None,
            tag_ids=(102,),
            created="2024-06-15T00:00:00+00:00",
            modified="2024-08-01T00:00:00+00:00",
            content_hash="hash2",
            page_count=2,
        ),
        [
            ChunkInput(
                chunk_index=0,
                text="electricity bill payment receipt",
                page_hint=1,
                embedding=unit_vec(4, 2),
            ),
            ChunkInput(
                chunk_index=1,
                text="account statement balance",
                page_hint=2,
                embedding=unit_vec(4, 3),
            ),
        ],
    )

    # Meta so get_stats has last_reconcile_at and embedding_model to report.
    writer.write_meta("last_reconcile_at", "2024-09-01T00:00:00+00:00")
    writer.write_meta("embedding_model", "test-model")
    writer.close()

    return db_path
