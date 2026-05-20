"""Write API for the search index store.

StoreWriter is the sole write-side interface to the SQLite search index.
The indexer daemon uses it to upsert documents, delete stale documents,
refresh the taxonomy, and manage the embedding-model meta.

Every write goes through an internal threading.Lock so that concurrent
indexer workers can safely share one StoreWriter instance.

Allowed deps: sqlite3, sqlite_vec, store.schema, store.migrations, store.models,
    common.config.
Forbidden: imports from indexer/, search/, or any package above store/.
No HTTP, no LLM calls, no business logic.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Sequence

import sqlite_vec  # type: ignore[import-untyped]  # no stubs shipped
import structlog

from common.clock import utc_now_iso
from common.config import Settings
from store._sql import placeholders
from store.migrations import StoreError
from store.models import ChunkInput, DocumentMeta, IndexState, TaxonomyEntry
from store.schema import connect, ensure_schema

log = structlog.get_logger(__name__)


class StoreWriter:
    """Write API for the SQLite search index.

    Owns all write transactions against the index database.  A single instance
    is shared across the indexer's worker threads; an internal Lock serialises
    every transaction.

    Raises:
        StoreError: Any sqlite3.Error encountered during a write is wrapped
            in StoreError (with ``from``) and re-raised.
    """

    def __init__(self, settings: Settings) -> None:
        """Open a read-write connection and apply pending migrations.

        Args:
            settings: Application settings; ``INDEX_DB_PATH``,
                ``EMBEDDING_MODEL``, and ``EMBEDDING_DIMENSIONS`` are used.
        """
        self._settings = settings
        self._conn = connect(settings.INDEX_DB_PATH, read_only=False)
        # Serialises all write transactions across threads (SPEC §5.6, §8.4).
        self._write_lock = threading.Lock()
        ensure_schema(self._conn)

    # ------------------------------------------------------------------
    # Reads (no lock needed — WAL allows concurrent reads)
    # ------------------------------------------------------------------

    def get_index_state(self) -> dict[int, IndexState]:
        """Return the current indexed state for every document.

        Returns:
            Mapping of document id to its IndexState (modified + content_hash).

        Raises:
            StoreError: On SQLite error.
        """
        try:
            rows = self._conn.execute(
                "SELECT id, modified, content_hash FROM documents"
            ).fetchall()
        except sqlite3.Error as exc:
            raise StoreError("failed to read index state") from exc
        return {row[0]: IndexState(modified=row[1], content_hash=row[2]) for row in rows}

    def get_all_document_ids(self) -> set[int]:
        """Return the set of all document ids currently in the index.

        Raises:
            StoreError: On SQLite error.
        """
        try:
            rows = self._conn.execute("SELECT id FROM documents").fetchall()
        except sqlite3.Error as exc:
            raise StoreError("failed to read document ids") from exc
        return {row[0] for row in rows}

    def read_meta(self, key: str) -> str | None:
        """Read a value from the meta table.

        Args:
            key: The meta key to look up.

        Returns:
            The stored value, or None if the key is absent.

        Raises:
            StoreError: On SQLite error.
        """
        try:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise StoreError(f"failed to read meta key {key!r}") from exc
        return row[0] if row is not None else None

    # ------------------------------------------------------------------
    # Writes (all serialised through _write_lock)
    # ------------------------------------------------------------------

    def write_meta(self, key: str, value: str) -> None:
        """Write or replace a meta key/value pair.

        Args:
            key: The meta key.
            value: The value to store.

        Raises:
            StoreError: On SQLite error.
        """
        try:
            with self._write_lock:
                with self._conn:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        (key, value),
                    )
        except sqlite3.Error as exc:
            raise StoreError(f"failed to write meta key {key!r}") from exc

    def upsert_document(
        self, meta: DocumentMeta, chunks: Sequence[ChunkInput]
    ) -> None:
        """Atomically upsert one document: delete its old chunks, insert new ones.

        The operation runs in a single transaction under the write lock so
        that a crash mid-document leaves the prior version fully intact.

        Sequence of operations inside the transaction:
        1. Read the current chunks.id values for this document.
        2. Delete the matching chunks_fts rows by rowid explicitly (FK cascade
           does NOT cover the FTS5 virtual table — see SPEC §4.5 / §9.8).
        3. Delete the chunks rows (FK cascade removes them from chunks, but
           we delete chunks_fts first while we still have the ids).
        4. Upsert the documents row (INSERT OR REPLACE).
        5. For each ChunkInput: INSERT INTO chunks, capture the auto-assigned id,
           INSERT INTO chunks_fts using that exact id as the rowid.
           This enforces chunks.id == chunks_fts.rowid (SPEC §4.2 invariant).

        Args:
            meta: Document metadata to upsert.
            chunks: Ordered sequence of chunks (with embeddings) to store.

        Raises:
            StoreError: On SQLite error; the transaction is rolled back and
                the prior version remains intact.
        """
        now = utc_now_iso()
        tag_ids_json = json.dumps(list(meta.tag_ids))
        try:
            with self._write_lock:
                with self._conn:
                    self._delete_chunks_for_document(meta.id)
                    self._conn.execute(
                        """
                        INSERT OR REPLACE INTO documents (
                            id, title, correspondent_id, document_type_id,
                            tag_ids, created, modified, content_hash,
                            page_count, chunk_count, indexed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            meta.id,
                            meta.title,
                            meta.correspondent_id,
                            meta.document_type_id,
                            tag_ids_json,
                            meta.created,
                            meta.modified,
                            meta.content_hash,
                            meta.page_count,
                            len(chunks),
                            now,
                        ),
                    )
                    for chunk in chunks:
                        cursor = self._conn.execute(
                            """
                            INSERT INTO chunks (document_id, chunk_index, text, page_hint, embedding)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                meta.id,
                                chunk.chunk_index,
                                chunk.text,
                                chunk.page_hint,
                                sqlite_vec.serialize_float32(list(chunk.embedding)),
                            ),
                        )
                        # Capture the auto-assigned rowid to use as the FTS rowid.
                        # This enforces chunks.id == chunks_fts.rowid (SPEC §4.2).
                        chunk_id = cursor.lastrowid
                        self._conn.execute(
                            # Insert into chunks_fts using the explicit rowid so
                            # that chunks.id == chunks_fts.rowid always holds.
                            "INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)",
                            (chunk_id, chunk.text),
                        )
        except sqlite3.Error as exc:
            raise StoreError(
                f"failed to upsert document {meta.id}"
            ) from exc

    def update_metadata(self, meta: DocumentMeta) -> None:
        """Update only the metadata columns; never touches chunks or chunk_count.

        Called when the Paperless document's OCR content is unchanged but its
        metadata (title, correspondent, tags, modified) has advanced.  Skipping
        re-chunking and re-embedding saves embedding API cost.

        Args:
            meta: Updated document metadata.

        Raises:
            StoreError: On SQLite error.
        """
        now = utc_now_iso()
        tag_ids_json = json.dumps(list(meta.tag_ids))
        try:
            with self._write_lock:
                with self._conn:
                    self._conn.execute(
                        """
                        UPDATE documents SET
                            title            = ?,
                            correspondent_id = ?,
                            document_type_id = ?,
                            tag_ids          = ?,
                            created          = ?,
                            modified         = ?,
                            indexed_at       = ?
                        WHERE id = ?
                        """,
                        (
                            meta.title,
                            meta.correspondent_id,
                            meta.document_type_id,
                            tag_ids_json,
                            meta.created,
                            meta.modified,
                            now,
                            meta.id,
                        ),
                    )
        except sqlite3.Error as exc:
            raise StoreError(
                f"failed to update metadata for document {meta.id}"
            ) from exc

    def delete_documents(self, ids: Iterable[int]) -> None:
        """Delete documents and all their chunks from the index.

        FK ON DELETE CASCADE removes chunks rows when documents rows go.
        chunks_fts is a standalone FTS5 virtual table that does NOT honour FK
        cascade — its rows must be deleted explicitly before the documents
        delete (while the chunk ids are still available).

        Args:
            ids: Document ids to delete.

        Raises:
            StoreError: On SQLite error.
        """
        document_ids = list(ids)
        if not document_ids:
            return
        try:
            with self._write_lock:
                with self._conn:
                    document_marks = placeholders(len(document_ids))
                    chunk_ids = [
                        row[0]
                        for row in self._conn.execute(
                            f"SELECT id FROM chunks WHERE document_id IN ({document_marks})",
                            document_ids,
                        ).fetchall()
                    ]
                    if chunk_ids:
                        # Delete FTS rows explicitly — FK cascade does not cover FTS5
                        # virtual tables (SPEC §4.5 / CODE_GUIDELINES §9.8).
                        self._conn.execute(
                            "DELETE FROM chunks_fts WHERE rowid IN "
                            f"({placeholders(len(chunk_ids))})",
                            chunk_ids,
                        )
                    self._conn.execute(
                        f"DELETE FROM documents WHERE id IN ({document_marks})",
                        document_ids,
                    )
        except sqlite3.Error as exc:
            raise StoreError(
                f"failed to delete documents {document_ids}"
            ) from exc

    def refresh_taxonomy(self, entries: Iterable[TaxonomyEntry]) -> None:
        """Replace the entire taxonomy table with the given entries.

        Runs as one transaction: DELETE all existing rows, then INSERT the
        new ones.  A rename in Paperless therefore takes effect immediately
        for all queries without any document-level rewrite.

        Args:
            entries: The complete current taxonomy from Paperless.

        Raises:
            StoreError: On SQLite error.
        """
        rows = list(entries)
        try:
            with self._write_lock:
                with self._conn:
                    self._conn.execute("DELETE FROM taxonomy")
                    for entry in rows:
                        self._conn.execute(
                            "INSERT INTO taxonomy (kind, id, name) VALUES (?, ?, ?)",
                            (entry.kind, entry.id, entry.name),
                        )
        except sqlite3.Error as exc:
            raise StoreError("failed to refresh taxonomy") from exc

    def check_embedding_model(self) -> bool:
        """Compare the configured embedding model against the stored meta.

        On a mismatch (or first run):
        - Wipes chunks and chunks_fts (vectors from a different model are
          incomparable — SPEC §4.6).
        - Keeps documents and taxonomy intact.
        - Clears the modified_watermark meta key so the next reconciliation
          re-indexes everything from scratch.
        - Writes the new model name and dimensions into meta.
        - Returns True (a rebuild is needed).

        If the model and dimensions already match, returns False.

        Returns:
            True if a rebuild is needed (model or dimensions changed or first
            run); False if the stored model already matches the configured one.

        Raises:
            StoreError: On SQLite error.
        """
        stored_model = self.read_meta("embedding_model")
        stored_dims = self.read_meta("embedding_dimensions")
        configured_model = self._settings.EMBEDDING_MODEL
        configured_dims = str(self._settings.EMBEDDING_DIMENSIONS)

        if stored_model == configured_model and stored_dims == configured_dims:
            return False

        log.warning(
            "store.embedding_model_changed",
            stored_model=stored_model,
            stored_dimensions=stored_dims,
            configured_model=configured_model,
            configured_dimensions=configured_dims,
        )

        try:
            with self._write_lock:
                with self._conn:
                    # Wipe all chunk data — vectors from the old model cannot be
                    # compared with vectors from the new model (SPEC §4.6).
                    self._conn.execute("DELETE FROM chunks_fts")
                    self._conn.execute("DELETE FROM chunks")
                    # Clear the watermark so the reconciler re-embeds all docs.
                    self._conn.execute(
                        "DELETE FROM meta WHERE key = 'modified_watermark'"
                    )
                    self._conn.execute(
                        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        ("embedding_model", configured_model),
                    )
                    self._conn.execute(
                        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        ("embedding_dimensions", configured_dims),
                    )
        except sqlite3.Error as exc:
            raise StoreError("failed to apply embedding model change") from exc

        return True

    def checkpoint(self) -> None:
        """Issue a WAL checkpoint (TRUNCATE mode).

        Called at the end of each reconciliation cycle so the search server
        never chases an unbounded WAL file (SPEC §3.2).

        Raises:
            StoreError: On SQLite error.
        """
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error as exc:
            raise StoreError("failed to checkpoint WAL") from exc

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _delete_chunks_for_document(self, document_id: int) -> None:
        """Delete chunks and chunks_fts rows for *document_id* (no lock, no txn).

        Caller must hold the write lock and be inside a transaction.

        The FK ON DELETE CASCADE on chunks.document_id would remove chunks rows
        when the documents row is deleted, but we delete chunks first (before
        the documents row) so we can collect the chunk ids to delete from
        chunks_fts.  chunks_fts is a standalone FTS5 virtual table — it does NOT
        honour FK cascade and must be cleaned explicitly (SPEC §4.5, §9.8).
        """
        rows = self._conn.execute(
            "SELECT id FROM chunks WHERE document_id = ?", (document_id,)
        ).fetchall()
        chunk_ids = [row[0] for row in rows]
        if chunk_ids:
            self._conn.execute(
                f"DELETE FROM chunks_fts WHERE rowid IN ({placeholders(len(chunk_ids))})",
                chunk_ids,
            )
            self._conn.execute(
                "DELETE FROM chunks WHERE document_id = ?", (document_id,)
            )
