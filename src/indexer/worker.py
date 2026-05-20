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
    common.config, common.embeddings.
Forbidden: sqlite3, httpx, openai direct calls, imports from search/.
"""

from __future__ import annotations

import enum
import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

from indexer.chunker import chunk_text
from store.models import ChunkInput, DocumentMeta

if TYPE_CHECKING:
    from common.config import Settings
    from common.embeddings import EmbeddingClient
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
        doc: dict,
        existing: IndexState | None,
    ) -> IndexOutcome:
        """Index one Paperless document according to SPEC §5.3.

        Args:
            doc: A Paperless document dict as returned by the API.  Expected
                fields: ``id``, ``content``, ``tags``, ``correspondent``,
                ``document_type``, ``created``, ``modified``, ``title``.
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
        if _should_skip(doc, self._settings.ERROR_TAG_ID):
            log.warning(
                "worker.document_skipped",
                document_id=document_id,
                reason="empty_content_or_error_tag",
            )
            return IndexOutcome.SKIPPED

        content: str = doc["content"]

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


def _should_skip(doc: dict, error_tag_id: int | None) -> bool:
    """Return True if the document must be skipped per SPEC §5.3 step 1.

    Skipped when:
    - ``content`` is absent, None, or whitespace-only (not yet OCR'd).
    - ``error_tag_id`` is set and present in the document's tags.
    """
    content = doc.get("content")
    if not content or not content.strip():
        return True
    if error_tag_id is not None:
        tags: list[int] = doc.get("tags") or []
        if error_tag_id in tags:
            return True
    return False


def _normalise_date(value: str | None) -> str | None:
    """Normalise a Paperless date or datetime string to a UTC ISO-8601 string.

    The store uses lexicographic date comparison, so all dates must be
    normalised to UTC ISO-8601 at the store boundary (SPEC §4.1).

    Handles:
    - ``None`` → ``None``
    - ``"YYYY-MM-DD"`` → midnight UTC ISO-8601
    - Any ISO-8601 datetime (with or without timezone) → UTC ISO-8601
    """
    if value is None:
        return None
    # Try parsing as full datetime first; fall back to date-only.
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        # Malformed value — store as-is and let the store handle it.
        return value
    # If no timezone info, assume UTC (Paperless stores UTC).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def _build_meta(doc: dict, content_hash: str) -> DocumentMeta:
    """Build a :class:`~store.models.DocumentMeta` from a Paperless document dict.

    Normalises ``created`` and ``modified`` to UTC ISO-8601 (SPEC §4.1).
    ``correspondent`` and ``document_type`` in the Paperless API are integer
    ids (or None); they map directly to ``correspondent_id`` / ``document_type_id``.
    """
    tags: list[int] = doc.get("tags") or []
    return DocumentMeta(
        id=doc["id"],
        title=doc.get("title"),
        correspondent_id=doc.get("correspondent"),
        document_type_id=doc.get("document_type"),
        tag_ids=tuple(tags),
        created=_normalise_date(doc.get("created")),
        modified=_normalise_date(doc.get("modified")) or "",  # modified is non-nullable
        content_hash=content_hash,
        page_count=doc.get("page_count"),
    )
