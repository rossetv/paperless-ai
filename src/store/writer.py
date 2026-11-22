"""Write API for the search index, used only by the indexer daemon."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Sequence

# sqlite_vec ships no type stubs.
import sqlite_vec  # type: ignore[import-untyped]
import structlog

from common.clock import utc_now_iso
from common.config import Settings
from store._reembed_guard import log_reembed_projection, project_reembed_scope
from store._sql import placeholders
from store.migrations import StoreError
from store.models import ChunkInput, DocumentMeta, IndexState, TaxonomyEntry
from store.schema import connect, ensure_schema

log = structlog.get_logger(__name__)

# Ids bound per statement; SQLite caps bound variables per statement.
_DELETE_SLICE = 500


class StoreWriter:
    """Write API for the SQLite search index.

    One instance is shared across the indexer's worker threads; an internal lock
    serialises every write transaction. Every ``sqlite3.Error`` is re-raised as
    :class:`StoreError`.
    """

    def __init__(self, settings: Settings) -> None:
        """Open a read-write connection and apply pending migrations."""
        self._settings = settings
        self._conn = connect(settings.INDEX_DB_PATH)
        self._write_lock = threading.Lock()
        ensure_schema(self._conn)

    # Reads take no lock: WAL allows concurrent reads.

    def get_index_state(self) -> dict[int, IndexState]:
        """Return the current indexed state of every document, keyed by id."""
        try:
            rows = self._conn.execute(
                "SELECT id, modified, content_hash FROM documents"
            ).fetchall()
        except sqlite3.Error as exc:
            raise StoreError("failed to read index state") from exc
        return {
            row[0]: IndexState(modified=row[1], content_hash=row[2]) for row in rows
        }

    def get_all_document_ids(self) -> set[int]:
        """Return the set of all document ids currently in the index."""
        try:
            rows = self._conn.execute("SELECT id FROM documents").fetchall()
        except sqlite3.Error as exc:
            raise StoreError("failed to read document ids") from exc
        return {row[0] for row in rows}

    def read_meta(self, key: str) -> str | None:
        """Return the meta value for *key*, or None if absent."""
        try:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise StoreError(f"failed to read meta key {key!r}") from exc
        return row[0] if row is not None else None

    # Writes are serialised through _write_lock.

    def write_meta(self, key: str, value: str) -> None:
        """Write or replace a meta key/value pair."""
        try:
            with self._write_lock:
                with self._conn:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        (key, value),
                    )
        except sqlite3.Error as exc:
            raise StoreError(f"failed to write meta key {key!r}") from exc

    def upsert_document(self, meta: DocumentMeta, chunks: Sequence[ChunkInput]) -> None:
        """Atomically replace one document and its chunks.

        One transaction, so a crash leaves the prior version intact. Each chunk's
        ``chunks_fts`` row reuses the chunk's id as its rowid; that invariant is
        how FTS rows are found and deleted later.
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
                    # Chunks are inserted one by one to capture lastrowid; the
                    # FTS rows then go in one executemany.
                    fts_rows: list[tuple[int, str]] = []
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
                        # Never None after a successful INSERT; guarded for typing.
                        chunk_id = cursor.lastrowid
                        if chunk_id is None:
                            raise StoreError(
                                f"upsert_document: INSERT INTO chunks returned no "
                                f"lastrowid for document {meta.id}"
                            )
                        fts_rows.append((chunk_id, chunk.text))
                    self._conn.executemany(
                        "INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)",
                        fts_rows,
                    )
        except sqlite3.Error as exc:
            raise StoreError(f"failed to upsert document {meta.id}") from exc

    def update_metadata(self, meta: DocumentMeta) -> None:
        """Update only the metadata columns; never touches chunks or chunk_count.

        Used when the OCR content is unchanged, which saves re-embedding.

        Raises:
            StoreError: On SQLite error, or when no row matched ``meta.id``: the
                index has diverged from the reconciler's state.
        """
        now = utc_now_iso()
        tag_ids_json = json.dumps(list(meta.tag_ids))
        try:
            with self._write_lock:
                with self._conn:
                    cursor = self._conn.execute(
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
                    # Fail loudly so the next reconcile re-indexes the document
                    # instead of the index quietly missing it.
                    if cursor.rowcount == 0:
                        raise StoreError(
                            f"update_metadata: document {meta.id} is not in the "
                            "index (0 rows updated); the index has diverged from "
                            "the reconciler state"
                        )
        except sqlite3.Error as exc:
            raise StoreError(
                f"failed to update metadata for document {meta.id}"
            ) from exc

    def delete_documents(self, ids: Iterable[int]) -> None:
        """Delete documents and all their chunks from the index.

        The FK cascade removes chunks but not their ``chunks_fts`` rows, so those
        are deleted first, while the chunk ids are still known.
        """
        document_ids = list(ids)
        if not document_ids:
            return
        try:
            with self._write_lock:
                with self._conn:
                    for start in range(0, len(document_ids), _DELETE_SLICE):
                        batch = document_ids[start : start + _DELETE_SLICE]
                        marks = placeholders(len(batch))
                        chunk_ids = [
                            row[0]
                            for row in self._conn.execute(
                                f"SELECT id FROM chunks WHERE document_id IN ({marks})",  # nosec B608 - marks is `?,?,?` from placeholders(); ids bound via ?
                                batch,
                            ).fetchall()
                        ]
                        self._delete_fts_rows(chunk_ids)
                        self._conn.execute(
                            f"DELETE FROM documents WHERE id IN ({marks})",  # nosec B608 - marks is `?,?,?` from placeholders(); ids bound via ?
                            batch,
                        )
        except sqlite3.Error as exc:
            shown = ", ".join(str(i) for i in document_ids[:10])
            more = ", ..." if len(document_ids) > 10 else ""
            raise StoreError(
                f"failed to delete {len(document_ids)} documents ({shown}{more})"
            ) from exc

    def refresh_taxonomy(self, entries: Iterable[TaxonomyEntry]) -> None:
        """Replace the entire taxonomy table in one transaction.

        Documents store ids only, so a rename in Paperless takes effect without
        rewriting any document.
        """
        rows = list(entries)
        try:
            with self._write_lock:
                with self._conn:
                    self._conn.execute("DELETE FROM taxonomy")
                    self._conn.executemany(
                        "INSERT INTO taxonomy (kind, id, name) VALUES (?, ?, ?)",
                        [(e.kind, e.id, e.name) for e in rows],
                    )
        except sqlite3.Error as exc:
            raise StoreError("failed to refresh taxonomy") from exc

    def check_embedding_model(self) -> bool:
        """Wipe the index if the embedding identity changed; return whether it did.

        The identity is ``(provider, model, dimensions)``. On a mismatch or first
        run the index is emptied via :meth:`_wipe_and_stamp_model` so the next
        reconcile re-embeds everything; vectors from different models or
        providers are not comparable.
        """
        # Indexes that predate the embedding_provider key were all built with
        # OpenAI; reading a missing key as "openai" avoids a false re-embed.
        stored_provider = self.read_meta("embedding_provider") or "openai"
        stored_model = self.read_meta("embedding_model")
        stored_dims = self.read_meta("embedding_dimensions")
        configured_provider = self._settings.EMBEDDING_PROVIDER
        configured_model = self._settings.EMBEDDING_MODEL
        configured_dims = str(self._settings.EMBEDDING_DIMENSIONS)

        if (
            stored_provider == configured_provider
            and stored_model == configured_model
            and stored_dims == configured_dims
        ):
            return False

        log.warning(
            "store.embedding_model_changed",
            stored_provider=stored_provider,
            stored_model=stored_model,
            stored_dimensions=stored_dims,
            configured_provider=configured_provider,
            configured_model=configured_model,
            configured_dimensions=configured_dims,
        )
        # A fresh database has nothing to re-embed, so the alarm would be false.
        # Read outside the write lock, before the wipe.
        if stored_model is not None or project_reembed_scope(self._conn)[1] != 0:
            log_reembed_projection(
                self._conn,
                trigger="embedding_model_change",
                stored_model=stored_model,
                configured_model=configured_model,
            )

        try:
            self._wipe_and_stamp_model(
                embedding_provider=configured_provider,
                embedding_model=configured_model,
                embedding_dimensions=self._settings.EMBEDDING_DIMENSIONS,
            )
        except sqlite3.Error as exc:
            raise StoreError("failed to apply embedding model change") from exc

        return True

    def _wipe_and_stamp_model(
        self,
        *,
        embedding_provider: str,
        embedding_model: str,
        embedding_dimensions: int,
    ) -> None:
        """Empty every indexed table and stamp the identity the next reconcile uses.

        ``documents`` must go too: if its rows survived, the content-hash check
        would treat every document as unchanged and never re-create the chunks.
        Clearing ``modified_watermark`` makes the next sync re-fetch everything.
        The identity is stamped in the same transaction, so it can never disagree
        with the chunk set.

        Takes the write lock and propagates ``sqlite3.Error`` for the caller to
        wrap.
        """
        with self._write_lock:
            with self._conn:
                self._conn.execute("DELETE FROM chunks_fts")
                self._conn.execute("DELETE FROM chunks")
                self._conn.execute("DELETE FROM documents")
                self._conn.execute("DELETE FROM taxonomy")
                self._conn.execute("DELETE FROM meta WHERE key = 'modified_watermark'")
                self._conn.executemany(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    [
                        ("embedding_provider", embedding_provider),
                        ("embedding_model", embedding_model),
                        ("embedding_dimensions", str(embedding_dimensions)),
                    ],
                )

    def rebuild_index(
        self,
        *,
        embedding_model: str,
        embedding_dimensions: int,
        embedding_provider: str | None = None,
    ) -> None:
        """Wipe the entire index in one transaction for the "Rebuild index" action.

        The caller passes the live (hot-reloaded) embedding identity, not the boot
        settings: stamping the old model would make the next boot's
        ``check_embedding_model`` see a false drift and re-embed everything again.
        *embedding_provider* defaults to the boot ``EMBEDDING_PROVIDER``; if it was
        hot-switched, the next boot's check corrects it.
        """
        provider = (
            embedding_provider
            if embedding_provider is not None
            else self._settings.EMBEDDING_PROVIDER
        )
        log.warning("store.index_rebuild_started")
        log_reembed_projection(self._conn, trigger="index_rebuild")
        try:
            self._wipe_and_stamp_model(
                embedding_provider=provider,
                embedding_model=embedding_model,
                embedding_dimensions=embedding_dimensions,
            )
        except sqlite3.Error as exc:
            raise StoreError("failed to rebuild the index") from exc
        log.warning("store.index_rebuild_completed")

    def checkpoint(self) -> None:
        """Refresh query-planner stats, then issue a WAL checkpoint (TRUNCATE).

        Called after each reconciliation cycle so the WAL never grows unbounded.
        ``PRAGMA optimize`` gives the search server's planner statistics after a
        large backfill; it is a no-op when nothing changed, so it is cheap every
        cycle, and running it first folds its write into the same truncation.
        """
        try:
            self._conn.execute("PRAGMA optimize")
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error as exc:
            raise StoreError("failed to checkpoint WAL") from exc

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    def _delete_fts_rows(self, chunk_ids: list[int]) -> None:
        """Delete chunks_fts rows for *chunk_ids*; FTS5 ignores the FK cascade.

        Caller must hold the write lock and be inside a transaction.
        """
        for start in range(0, len(chunk_ids), _DELETE_SLICE):
            batch = chunk_ids[start : start + _DELETE_SLICE]
            self._conn.execute(
                f"DELETE FROM chunks_fts WHERE rowid IN ({placeholders(len(batch))})",  # nosec B608 - placeholders() emits `?,?,?` from an int; ids bound via ?
                batch,
            )

    def _delete_chunks_for_document(self, document_id: int) -> None:
        """Delete chunks and chunks_fts rows for *document_id*.

        Caller must hold the write lock and be inside a transaction.
        """
        rows = self._conn.execute(
            "SELECT id FROM chunks WHERE document_id = ?", (document_id,)
        ).fetchall()
        chunk_ids = [row[0] for row in rows]
        self._delete_fts_rows(chunk_ids)
        if chunk_ids:
            self._conn.execute(
                "DELETE FROM chunks WHERE document_id = ?", (document_id,)
            )
