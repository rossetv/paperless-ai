"""The Reconciler facade over the incremental sync and the deletion sweep."""

from __future__ import annotations

from typing import TYPE_CHECKING

from indexer.reconciler._incremental import SyncReport, run_incremental_sync
from indexer.reconciler._sweep import SweepReport, run_deletion_sweep
from indexer.worker import DocumentIndexer

if TYPE_CHECKING:
    from common.config import Settings
    from common.embeddings import EmbeddingClient
    from common.paperless import PaperlessClient
    from store.writer import StoreWriter


class Reconciler:
    """Diffs Paperless-ngx against the search store and keeps the store in sync.

    Holds no per-cycle state; all persistent state lives in the store's meta
    table.
    """

    def __init__(
        self,
        settings: Settings,
        paperless: PaperlessClient,
        store_writer: StoreWriter,
        embedding_client: EmbeddingClient,
    ) -> None:
        self._settings = settings
        self._paperless = paperless
        self._store_writer = store_writer
        self._embedding_client = embedding_client
        # Stateless and thread-safe, so one instance serves the whole pool.
        self._indexer = DocumentIndexer(settings, store_writer, embedding_client)

    @property
    def paperless(self) -> PaperlessClient:
        """The Paperless client, exposed so the daemon can close it on reload."""
        return self._paperless

    @property
    def embedding_client(self) -> EmbeddingClient:
        """The embedding client, exposed so the daemon can close it on reload."""
        return self._embedding_client

    @property
    def store_writer(self) -> StoreWriter:
        """The store writer, which a reconciler rebuilt on config reload inherits."""
        return self._store_writer

    def incremental_sync(self) -> SyncReport:
        """Index every document modified since the watermark, plus retries."""
        return run_incremental_sync(
            self._paperless,
            self._store_writer,
            self._indexer,
            self._settings.DOCUMENT_WORKERS,
        )

    def deletion_sweep(self) -> SweepReport:
        """Prune documents deleted from Paperless."""
        return run_deletion_sweep(self._paperless, self._store_writer)
