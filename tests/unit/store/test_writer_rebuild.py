"""Tests for StoreWriter.rebuild_index — the full index wipe.

Covers: after rebuild_index the documents and chunks tables are empty and
the modified_watermark meta key is cleared, so the next reconcile re-indexes
everything; the embedding-model meta is stamped with the configured model so
the next boot does not see a false drift and re-embed twice.
"""

from __future__ import annotations

import structlog.testing

from store.writer import StoreWriter
from tests.helpers.factories import make_chunks, make_document_meta
from tests.helpers.store import open_writer


# db_path comes from tests/unit/store/conftest.py (a fresh tmp_path file
# per test — the same fixture every other store unit test uses).


def test_rebuild_index_empties_documents_and_chunks(db_path: str) -> None:
    writer = open_writer(db_path)
    try:
        writer.upsert_document(make_document_meta(id=1), make_chunks(2))
        writer.rebuild_index(
            embedding_model="text-embedding-3-small", embedding_dimensions=1536
        )
        assert writer.get_all_document_ids() == set()
    finally:
        writer.close()


def test_rebuild_index_clears_the_watermark(db_path: str) -> None:
    writer = open_writer(db_path)
    try:
        writer.write_meta("modified_watermark", "2026-05-22T00:00:00+00:00")
        writer.rebuild_index(
            embedding_model="text-embedding-3-small", embedding_dimensions=1536
        )
        assert writer.read_meta("modified_watermark") is None
    finally:
        writer.close()


def test_rebuild_index_writes_the_configured_embedding_model_meta(
    db_path: str,
) -> None:
    """rebuild_index stamps the model/dims the next reconcile will re-embed with."""
    writer = open_writer(db_path)
    try:
        writer.rebuild_index(
            embedding_model="text-embedding-3-small", embedding_dimensions=1536
        )
        assert writer.read_meta("embedding_model") == "text-embedding-3-small"
        assert writer.read_meta("embedding_dimensions") == "1536"
    finally:
        writer.close()


def test_rebuild_index_reconciles_meta_to_a_changed_model(db_path: str) -> None:
    """Regression (IDX): a rebuild after the operator switches models in the UI
    must stamp the NEW model into meta. Otherwise the next boot's
    check_embedding_model() sees stored small vs configured large, calls it
    drift, and redundantly re-embeds the whole corpus a second time.
    """
    writer = open_writer(db_path)
    try:
        writer.write_meta("embedding_model", "text-embedding-3-small")
        writer.write_meta("embedding_dimensions", "1536")
        writer.rebuild_index(
            embedding_model="text-embedding-3-large", embedding_dimensions=3072
        )
        assert writer.read_meta("embedding_model") == "text-embedding-3-large"
        assert writer.read_meta("embedding_dimensions") == "3072"
    finally:
        writer.close()


def test_rebuild_index_is_a_writer_only_operation(db_path: str) -> None:
    """I4: the wipe lives only on the write side (StoreWriter).

    A regression guard: rebuild_index must remain a StoreWriter method (gated by
    the indexer's single-writer flock), never reachable from the read side. The
    StoreReader has no such method — asserting its absence pins the invariant
    that a full re-embed cannot be triggered from a read/search path.
    """
    from store.reader import StoreReader

    assert hasattr(StoreWriter, "rebuild_index")
    assert not hasattr(StoreReader, "rebuild_index")
    assert not hasattr(StoreReader, "check_embedding_model")


def test_rebuild_index_logs_projected_scope_at_critical(db_path: str) -> None:
    """rebuild_index logs a CRITICAL projected-cost line before the wipe (IDX-04)."""
    writer = open_writer(db_path)
    try:
        writer.upsert_document(make_document_meta(id=1), make_chunks(3))
        writer.upsert_document(make_document_meta(id=2), make_chunks(2))
        with structlog.testing.capture_logs() as captured:
            writer.rebuild_index(
                embedding_model="text-embedding-3-small", embedding_dimensions=1536
            )
    finally:
        writer.close()

    critical = [
        event for event in captured if event["event"] == "store.full_reembed_projected"
    ]
    assert len(critical) == 1
    assert critical[0]["log_level"] == "critical"
    assert critical[0]["trigger"] == "index_rebuild"
    assert critical[0]["document_count"] == 2
    assert critical[0]["current_chunk_count"] == 5


def test_rebuild_index_still_wipes_after_logging(db_path: str) -> None:
    """The CRITICAL log does not gate the wipe — the index is still emptied."""
    writer = open_writer(db_path)
    try:
        writer.upsert_document(make_document_meta(id=1), make_chunks(3))
        writer.rebuild_index(
            embedding_model="text-embedding-3-small", embedding_dimensions=1536
        )
        assert writer.get_all_document_ids() == set()
    finally:
        writer.close()
