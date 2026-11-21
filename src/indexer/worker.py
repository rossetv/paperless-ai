"""Per-document indexing worker: gate, hash, then metadata-only update or re-embed.

``DocumentIndexer`` holds no per-document state, so one instance is shared
across the worker threads.
"""

from __future__ import annotations

import enum
import hashlib
from typing import TYPE_CHECKING

import structlog

from common.clock import normalise_paperless_timestamp, parse_paperless_timestamp
from indexer.chunker import chunk_text
from store.models import ChunkInput, DocumentMeta

if TYPE_CHECKING:
    from common.config import Settings
    from common.embeddings import EmbeddingClient
    from common.paperless import PaperlessDocument
    from store.models import IndexState
    from store.writer import StoreWriter

log = structlog.get_logger(__name__)


class IndexOutcome(enum.Enum):
    """Result of a single call to :meth:`DocumentIndexer.index_document`.

    Attributes:
        SKIPPED: Document was not indexed — empty content, error tag, or
            content that produced zero chunks after chunking (e.g. OCR page
            markers with no surrounding text).  No ``content_hash`` is stored,
            so a future cycle can retry the document once its content changes.
        METADATA_ONLY: Content hash unchanged; only metadata columns updated.
        INDEXED: Full chunk + embed + upsert cycle completed.
    """

    SKIPPED = "skipped"
    METADATA_ONLY = "metadata_only"
    INDEXED = "indexed"


class DocumentIndexer:
    """Stateless per-document indexing worker, safe to share across threads.

    The shared *store_writer* serialises transactions with its own lock.
    """

    def __init__(
        self,
        settings: Settings,
        store_writer: StoreWriter,
        embedding_client: EmbeddingClient,
    ) -> None:
        self._settings = settings
        self._store_writer = store_writer
        self._embedding_client = embedding_client

    def index_document(
        self,
        doc: PaperlessDocument,
        existing: IndexState | None,
    ) -> IndexOutcome:
        """Index one Paperless document; *existing* is ``None`` on first index.

        Store and embedding errors propagate; the reconciler isolates them per
        document.
        """
        document_id: int = doc["id"]

        content = _indexable_content(doc, self._settings.ERROR_TAG_ID)
        if content is None:
            # A previously indexed document that became un-indexable (content
            # cleared, error tag applied) must be pruned: it still exists in
            # Paperless, so the deletion sweep would never remove its chunks.
            # Both paths return SKIPPED; the log event tells them apart.
            if existing is not None:
                self._store_writer.delete_documents((document_id,))
                log.info(
                    "worker.stale_document_pruned",
                    document_id=document_id,
                    reason="empty_content_or_error_tag",
                )
                return IndexOutcome.SKIPPED
            log.warning(
                "worker.document_skipped",
                document_id=document_id,
                reason="empty_content_or_error_tag",
            )
            return IndexOutcome.SKIPPED

        content_hash = hashlib.sha256(content.encode()).hexdigest()

        meta = _build_meta(doc, content_hash)

        if existing is not None and existing.content_hash == content_hash:
            self._store_writer.update_metadata(meta)
            log.debug(
                "worker.metadata_only",
                document_id=document_id,
            )
            return IndexOutcome.METADATA_ONLY

        return self._index_full(document_id, meta, content, existing)

    def _index_full(
        self,
        document_id: int,
        meta: DocumentMeta,
        content: str,
        existing: IndexState | None,
    ) -> IndexOutcome:
        """Chunk, embed, and upsert a document whose content hash has changed.

        Content that chunks to nothing (e.g. only OCR page markers) must not be
        upserted: the stored hash would make every later cycle treat it as
        ``METADATA_ONLY``, hiding the document from search for good.
        """
        text_chunks = chunk_text(
            content,
            chunk_size=self._settings.CHUNK_SIZE,
            overlap=self._settings.CHUNK_OVERLAP,
        )

        if not text_chunks:
            # Skip without a stored hash so a later content change is indexed.
            if existing is not None:
                self._store_writer.delete_documents((document_id,))
                log.info(
                    "worker.stale_document_pruned",
                    document_id=document_id,
                    reason="zero_chunks_after_chunking",
                )
            else:
                log.warning(
                    "worker.document_skipped",
                    document_id=document_id,
                    reason="indexed_content_produced_zero_chunks",
                )
            return IndexOutcome.SKIPPED

        texts = [chunk.text for chunk in text_chunks]
        vectors = self._embedding_client.embed(texts)

        chunk_inputs = [
            ChunkInput(
                chunk_index=text_chunks[i].chunk_index,
                text=text_chunks[i].text,
                page_hint=text_chunks[i].page_hint,
                embedding=tuple(vectors[i]),
            )
            for i in range(len(text_chunks))
        ]

        self._store_writer.upsert_document(meta, chunk_inputs)
        log.info(
            "worker.document_indexed",
            document_id=document_id,
            chunk_count=len(chunk_inputs),
        )
        return IndexOutcome.INDEXED


def _indexable_content(doc: PaperlessDocument, error_tag_id: int | None) -> str | None:
    """Return the OCR content to index, or ``None`` if it is blank or error-tagged."""
    content = doc.get("content")
    if not content or not content.strip():
        return None
    if error_tag_id is not None and error_tag_id in (doc.get("tags") or []):
        return None
    return content


def _normalise_date(value: str | None, *, document_id: int, field: str) -> str | None:
    """Normalise a Paperless ``created`` / ``modified`` value to UTC ISO-8601.

    An unparseable value is stored verbatim, but logged so the operator sees it.
    """
    normalised = normalise_paperless_timestamp(value)
    if value is not None and parse_paperless_timestamp(value) is None:
        log.warning(
            "worker.unparseable_date",
            document_id=document_id,
            field=field,
            value=value,
        )
    return normalised


def _build_meta(doc: PaperlessDocument, content_hash: str) -> DocumentMeta:
    """Build a :class:`~store.models.DocumentMeta` from a Paperless document."""
    document_id = doc["id"]
    tags = doc.get("tags") or []
    # documents.modified is NOT NULL, so "" stands in for a missing value.
    modified = _normalise_date(
        doc.get("modified"), document_id=document_id, field="modified"
    )
    return DocumentMeta(
        id=document_id,
        title=doc.get("title"),
        correspondent_id=doc.get("correspondent"),
        document_type_id=doc.get("document_type"),
        tag_ids=tuple(tags),
        created=_normalise_date(
            doc.get("created"), document_id=document_id, field="created"
        ),
        modified=modified or "",
        content_hash=content_hash,
        page_count=doc.get("page_count"),
    )
