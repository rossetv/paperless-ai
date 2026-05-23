"""The Reconciler facade — the indexer's correctness-critical core.

:class:`Reconciler` holds the long-lived clients and the per-document worker,
and exposes the two operations the daemon loop (SPEC §5.1) calls in turn:
``incremental_sync`` and ``deletion_sweep``.  The implementations live in the
three sibling concept-modules — :mod:`._incremental`, :mod:`._failed_documents`,
and :mod:`._sweep` — and this class is a thin facade that owns the shared state
and delegates.
"""

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

    One instance is created per daemon and reused for every cycle.  It holds no
    per-cycle mutable state; all state lives in the store's meta table or is
    local to a method call.

    Args:
        settings: Application settings.  ``DOCUMENT_WORKERS`` sizes the worker
            pool; the worker reads ``ERROR_TAG_ID``, ``CHUNK_SIZE``, and
            ``CHUNK_OVERLAP`` from the same object.
        paperless: The Paperless API client.  Used read-only here:
            ``iter_all_documents``, the taxonomy lists, and ``document_exists``.
        store_writer: The write-side store API — the sole writer to the index.
        embedding_client: The batched embedding client, forwarded to the
            per-document worker.
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
        # The worker is stateless and thread-safe; one instance is shared
        # across the pool for the reconciler's lifetime (SPEC §5.3).
        self._indexer = DocumentIndexer(settings, store_writer, embedding_client)

    @property
    def paperless(self) -> PaperlessClient:
        """The Paperless API client.

        Exposed so the indexer daemon can explicitly close it when the
        reconciler is replaced on a hot-load config change, matching the
        explicit-close convention used by the OCR and classifier daemons.
        """
        return self._paperless

    @property
    def store_writer(self) -> StoreWriter:
        """The store writer this reconciler reads and writes.

        Exposed so the indexer daemon can re-use the same writer when it
        rebuilds the reconciler on a hot-load config change (web-redesign §5):
        the index database is bootstrap-only and never replaced mid-run, so a
        rebuilt reconciler always inherits the original writer.
        """
        return self._store_writer

    def incremental_sync(self) -> SyncReport:
        """Index every document modified since the watermark, plus retries.

        See :func:`indexer.reconciler._incremental.run_incremental_sync`.
        """
        return run_incremental_sync(
            self._paperless,
            self._store_writer,
            self._indexer,
            self._settings.DOCUMENT_WORKERS,
        )

    def deletion_sweep(self) -> SweepReport:
        """Prune documents deleted from Paperless — safely.

        See :func:`indexer.reconciler._sweep.run_deletion_sweep`.
        """
        return run_deletion_sweep(self._paperless, self._store_writer)
