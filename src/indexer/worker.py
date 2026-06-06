"""Per-document indexing worker for the semantic-search reconciler.

Implements the per-document indexing steps described in SPEC §5.3:
1. Gate — skip empty content or error-tagged documents.
2. Hash — SHA-256 of the OCR content.
3. Hash gate — if unchanged, call update_metadata only (no re-embed).
4. Full path — chunk, embed, upsert_document.

``DocumentIndexer`` is instantiated once per reconciliation cycle and shared
across worker threads.  It holds NO per-document mutable state; all state is
passed through method arguments so it is safe to call ``index_document`` from
multiple threads concurrently.

Allowed deps: indexer.chunker, store.models, store.writer,
    common.clock, common.config, common.embeddings, common.paperless.
Forbidden: sqlite3, httpx, openai direct calls, imports from search/.
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
        SKIPPED: Document was not indexed — empty content or error tag.
        METADATA_ONLY: Content hash unchanged; only metadata columns updated.
        INDEXED: Full chunk + embed + upsert cycle completed.
    """

    SKIPPED = "skipped"
    METADATA_ONLY = "metadata_only"
    INDEXED = "indexed"


class DocumentIndexer:
    """Stateless per-document indexing worker.

    One instance is created per reconciliation cycle and shared across the
    :class:`~concurrent.futures.ThreadPoolExecutor` worker threads.  No
    per-document mutable state is held on ``self``; every operation is passed
    through method arguments.

    Args:
        settings: Application settings.  ``ERROR_TAG_ID``, ``CHUNK_SIZE``,
            and ``CHUNK_OVERLAP`` are read during ``index_document``.
        store_writer: The write-side store API.  A single instance is shared
            across threads; its internal lock serialises transactions.
        embedding_client: The batched embedding client.  Thread-safe.
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
        """Index one Paperless document according to SPEC §5.3.

        Args:
            doc: A Paperless document as returned by the API — see
                :class:`~common.paperless.PaperlessDocument` for the shape.
            existing: The document's current state in the store, or ``None``
                if this is a first-time index.

        Returns:
            ``SKIPPED`` — content empty or error tag present.
            ``METADATA_ONLY`` — content hash unchanged; metadata updated.
            ``INDEXED`` — full chunk + embed + upsert completed.

        Raises:
            Any exception from :class:`~store.writer.StoreWriter` or
            :class:`~common.embeddings.EmbeddingClient` propagates to the
            caller.  The reconciler isolates per-document failures (SPEC §5.7).
        """
        document_id: int = doc["id"]

        # --- Step 1: Gate ---
        # _indexable_content returns the OCR text when the document is
        # indexable, or None when it must be skipped (empty content or error
        # tag); the gate and the content extraction are one operation so the
        # type checker sees a concrete str on the indexing path.
        content = _indexable_content(doc, self._settings.ERROR_TAG_ID)
        if content is None:
            # A document that was previously indexed but has since become
            # un-indexable (its OCR content was cleared, or an operator applied
            # the error tag) must have its stale rows pruned — otherwise search
            # keeps serving chunks for content that no longer exists, and the
            # deletion sweep cannot reach it because the document still exists in
            # Paperless (IDX-01). A document that was never indexed (no existing
            # row) is a pure no-op skip. The prune is one transaction in the
            # StoreWriter; a crash mid-delete rolls back to the prior version.
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

        # --- Step 2: Hash ---
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        # --- Step 3: Hash gate ---
        meta = _build_meta(doc, content_hash)

        if existing is not None and existing.content_hash == content_hash:
            # Content unchanged — only metadata columns need updating.
            self._store_writer.update_metadata(meta)
            log.debug(
                "worker.metadata_only",
                document_id=document_id,
            )
            return IndexOutcome.METADATA_ONLY

        # --- Step 4: Chunk + embed + upsert ---
        text_chunks = chunk_text(
            content,
            chunk_size=self._settings.CHUNK_SIZE,
            overlap=self._settings.CHUNK_OVERLAP,
        )

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


# ---------------------------------------------------------------------------
# Module-level helpers (private)
# ---------------------------------------------------------------------------


def _indexable_content(doc: PaperlessDocument, error_tag_id: int | None) -> str | None:
    """Return the OCR content to index, or ``None`` if the document is skipped.

    Applies the SPEC §5.3 step-1 gate: a document is skipped when its
    ``content`` is absent, ``None``, or whitespace-only (not yet OCR'd), or
    when *error_tag_id* is set and applied to the document.

    Returning the content rather than a bare boolean lets the caller extract
    the OCR text in the same step it checks the gate, so the indexing path
    works with a concrete ``str``.
    """
    content = doc.get("content")
    if not content or not content.strip():
        return None
    if error_tag_id is not None and error_tag_id in (doc.get("tags") or []):
        return None
    return content


def _normalise_date(value: str | None, *, document_id: int, field: str) -> str | None:
    """Normalise a Paperless ``created`` / ``modified`` value to UTC ISO-8601.

    Delegates to :func:`common.clock.normalise_paperless_timestamp` — the
    single Paperless-timestamp normaliser.  When the value is present but
    unparseable the normaliser returns it verbatim; that anomaly is logged
    here at WARNING before the verbatim value is stored, matching how the
    reconciler's watermark advance logs the same upstream quirk (SPEC §4.1).
    """
    normalised = normalise_paperless_timestamp(value)
    if value is not None and parse_paperless_timestamp(value) is None:
        # Present but not an ISO-8601 timestamp — an upstream anomaly.  It is
        # stored verbatim rather than dropped, but the operator must see it.
        log.warning(
            "worker.unparseable_date",
            document_id=document_id,
            field=field,
            value=value,
        )
    return normalised


def _build_meta(doc: PaperlessDocument, content_hash: str) -> DocumentMeta:
    """Build a :class:`~store.models.DocumentMeta` from a Paperless document.

    Normalises ``created`` and ``modified`` to UTC ISO-8601 (SPEC §4.1).
    ``correspondent`` and ``document_type`` in the Paperless API are integer
    ids (or None); they map directly to ``correspondent_id`` / ``document_type_id``.
    """
    document_id = doc["id"]
    tags = doc.get("tags") or []
    # An empty string is the store's sentinel for an absent ``modified``: the
    # documents.modified column is NOT NULL, and Paperless practically always
    # supplies the field, so a missing value is degenerate rather than expected.
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
