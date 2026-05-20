"""Shared helpers for the search-pipeline integration tests.

The ``test_search_pipeline`` integration tests are split across two files for
the 500-line ceiling (CODE_GUIDELINES §3.1) — ``test_search_pipeline`` and
``test_search_pipeline_refinement``.  The store-seeding helpers and the
embedding geometry they both use live here so each file imports one definition
rather than redeclaring it, mirroring ``tests/unit/indexer/conftest.py``.

The geometry: every document is embedded onto one of a small set of orthogonal
unit vectors.  A query embedded onto the same axis as a document has cosine
distance 0 to it (nearest); onto a different axis, distance 1.  This makes
vector search deterministic without needing real embeddings.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from store.models import ChunkInput, DocumentMeta
from store.writer import StoreWriter
from tests.helpers.factories import make_search_settings

# Embedding width for every integration store; four keeps test vectors tiny.
PIPELINE_DIMENSIONS = 4

# Orthogonal unit axes.  AXIS_BOILER backs the "boiler" document; AXIS_OTHER an
# unrelated one; AXIS_REFINED the document a refined retrieval round surfaces.
AXIS_BOILER: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0)
AXIS_OTHER: tuple[float, ...] = (0.0, 1.0, 0.0, 0.0)
AXIS_REFINED: tuple[float, ...] = (0.0, 0.0, 1.0, 0.0)


def make_pipeline_settings(tmp_path: Any, **overrides: Any) -> MagicMock:
    """Build a settings mock the store, the pipeline stages, and core all read.

    Args:
        tmp_path: The pytest ``tmp_path`` for the index database.
        **overrides: Any further Settings field overrides.
    """
    return make_search_settings(
        INDEX_DB_PATH=str(tmp_path / "index.db"),
        EMBEDDING_DIMENSIONS=PIPELINE_DIMENSIONS,
        **overrides,
    )


def make_axis_embedding_client(axis: tuple[float, ...]) -> MagicMock:
    """A mock EmbeddingClient that embeds every query text onto *axis*.

    The retriever batches every semantic query and sub-question into one
    embed() call; returning the same axis vector for each keeps the test's
    geometry fixed regardless of how many rephrasings the plan carries.
    """
    client = MagicMock()
    client.embed.side_effect = lambda texts: [list(axis) for _ in texts]
    return client


def seed_pipeline_document(
    store_writer: StoreWriter,
    *,
    document_id: int,
    title: str,
    text: str,
    embedding: tuple[float, ...],
    correspondent_id: int | None = None,
    document_type_id: int | None = None,
) -> None:
    """Upsert one document with a single chunk into the real store.

    Args:
        store_writer: The real StoreWriter to upsert through.
        document_id: The document id.
        title: The document title.
        text: The single chunk's text.
        embedding: The chunk's embedding vector (one of the AXIS_* constants).
        correspondent_id: An optional taxonomy correspondent id.
        document_type_id: An optional taxonomy document-type id.
    """
    meta = DocumentMeta(
        id=document_id,
        title=title,
        correspondent_id=correspondent_id,
        document_type_id=document_type_id,
        tag_ids=(),
        created="2024-01-15T00:00:00+00:00",
        modified="2024-06-01T12:00:00+00:00",
        content_hash=f"hash-{document_id}",
        page_count=1,
    )
    chunk = ChunkInput(
        chunk_index=0, text=text, page_hint=1, embedding=embedding
    )
    store_writer.upsert_document(meta, [chunk])
