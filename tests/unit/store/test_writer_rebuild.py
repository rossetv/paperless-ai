"""Tests for StoreWriter.rebuild_index — the full index wipe.

Covers: after rebuild_index the documents and chunks tables are empty and
the modified_watermark meta key is cleared, so the next reconcile re-indexes
everything; the embedding-model meta is preserved.
"""

from __future__ import annotations

from tests.helpers.factories import make_chunks, make_document_meta
from tests.helpers.store import open_writer


# db_path comes from tests/unit/store/conftest.py (a fresh tmp_path file
# per test — the same fixture every other store unit test uses).


def test_rebuild_index_empties_documents_and_chunks(db_path: str) -> None:
    writer = open_writer(db_path)
    try:
        writer.upsert_document(make_document_meta(id=1), make_chunks(2))
        writer.rebuild_index()
        assert writer.get_all_document_ids() == set()
    finally:
        writer.close()


def test_rebuild_index_clears_the_watermark(db_path: str) -> None:
    writer = open_writer(db_path)
    try:
        writer.write_meta("modified_watermark", "2026-05-22T00:00:00+00:00")
        writer.rebuild_index()
        assert writer.read_meta("modified_watermark") is None
    finally:
        writer.close()


def test_rebuild_index_preserves_the_embedding_model_meta(db_path: str) -> None:
    writer = open_writer(db_path)
    try:
        writer.write_meta("embedding_model", "text-embedding-3-small")
        writer.rebuild_index()
        assert writer.read_meta("embedding_model") == "text-embedding-3-small"
    finally:
        writer.close()
