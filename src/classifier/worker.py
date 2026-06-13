"""Per-document classification orchestrator."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from common.claims import claim_processing_tag
from common.config import Settings
from common.paperless import (
    PAPERLESS_CALL_EXCEPTIONS,
    PaperlessClient,
    is_permanent_paperless_error,
)
from common.per_document import WriteBackOutcome
from common.tags import (
    clean_pipeline_tags,
    extract_tags,
    finalise_document_with_error,
    release_processing_tag,
)
from .content_prep import (
    truncate_content_by_chars,
    truncate_content_by_pages,
    max_char_truncation_note,
)
from .metadata import (
    is_empty_classification,
    normalise_language,
    parse_document_date,
    resolve_date_for_tags,
    update_custom_fields,
)
from .provider import ClassificationProvider
from .result import ClassificationResult
from .quality_gates import is_generic_document_type, needs_error_tag
from .tag_filters import (
    enrich_tags,
    filter_blacklisted_tags,
    filter_redundant_tags,
)
from .taxonomy import TaxonomyCache

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _PrepareOutcome:
    """Carries pre-LLM screening results back to :meth:`ClassificationProcessor.process`.

    ``content`` is the raw OCR text when screening passes; ``None`` means the
    document was diverted (error-tagged, requeued, refused, or unclaimed) and
    ``process()`` should return ``None`` immediately.  ``claimed`` records
    whether the processing-lock tag was acquired so the ``finally`` block can
    release it regardless of outcome.
    """

    content: str | None
    claimed: bool
    document: dict[str, object]  # re-used by _apply_classification
    current_tags: set[int]  # extracted once, shared across screening and apply steps


@dataclass(frozen=True, slots=True)
class _ResolvedTaxonomyIds:
    """The Paperless ids resolved from a classification result.

    A named shape rather than a 3-tuple so the call site reads by field, not by
    position (CODE_GUIDELINES §5.8). ``tag_ids`` is a tuple to keep the shape
    fully immutable.
    """

    tag_ids: tuple[int, ...]
    correspondent_id: int | None
    document_type_id: int | None


class ClassificationProcessor:
    """
    Orchestrates the classification of a single Paperless document.

    Instantiated per-document by the daemon's thread pool.  Each instance
    gets its own :class:`PaperlessClient` (HTTP session) and a shared
    :class:`TaxonomyCache`.
    """

    def __init__(
        self,
        doc: dict[str, object],
        paperless_client: PaperlessClient,
        classifier: ClassificationProvider,
        taxonomy_cache: TaxonomyCache,
        settings: Settings,
    ):
        self.paperless_client = paperless_client
        self.classifier = classifier
        self.taxonomy_cache = taxonomy_cache
        self.settings = settings
        self.document_id: int = doc["id"]  # type: ignore[assignment]
        self.title: str = doc.get("title") or "<untitled>"  # type: ignore[assignment]

    def process(self) -> WriteBackOutcome | None:
        """
        Run the full classification workflow.

        Steps:
        1. Pre-LLM screening via :meth:`_prepare_or_divert` (fetch, error-tag
           check, claim, empty-content requeue, refusal check).
        2. Truncate content (by pages, then by characters).
        3. Call the classification LLM.
        4. Validate the result (non-empty, non-generic).
        5. Apply metadata to Paperless (tags, correspondent, type, etc.).
        6. Release the processing-lock tag.

        Returns the write-back outcome the daemon feeds to the circuit breaker:
        :attr:`WriteBackOutcome.SAVED` when the metadata was applied,
        :attr:`WriteBackOutcome.QUARANTINED` when a permanent Paperless
        rejection error-tagged the document, or ``None`` for a cycle that wrote
        back nothing (skipped, requeued, or already-errored).
        """
        log.info("Classifying document", doc_id=self.document_id, title=self.title)
        self.classifier.reset_stats()
        # Initialise with a safe "not claimed, no content" sentinel so the
        # finally block is always safe to read, even if _prepare_or_divert raises.
        prepare = _PrepareOutcome(
            content=None, claimed=False, document={}, current_tags=set()
        )
        try:
            prepare = self._prepare_or_divert()
            if prepare.content is None:
                return None

            input_text, truncation_notes = self._truncate_content(prepare.content)
            truncation_note = "\n".join(truncation_notes) if truncation_notes else None
            result, model = self.classifier.classify_text(
                input_text,
                self.taxonomy_cache.taxonomy_context(),
                truncation_note=truncation_note,
            )

            usable = self._usable_result(result, prepare.current_tags)
            if usable is None:
                return None
            try:
                self._apply_classification(
                    prepare.document,
                    prepare.current_tags,
                    prepare.content,
                    usable,
                    model,
                )
                return WriteBackOutcome.SAVED
            except PAPERLESS_CALL_EXCEPTIONS as exc:
                # The LLM tokens for this document are already spent. A 4xx here
                # (a rejected metadata PATCH, a stale taxonomy pk) is permanent:
                # leaving the document queued would re-classify it every poll and
                # burn tokens forever. Quarantine it with the error tag so it
                # leaves the queue. Transient errors (5xx/network) re-raise so the
                # daemon loop retries them once Paperless recovers.
                if not is_permanent_paperless_error(exc):
                    raise
                log.error(
                    "Paperless rejected classification write; quarantining "
                    "document to break the reprocessing loop",
                    doc_id=self.document_id,
                    error=str(exc),
                )
                finalise_document_with_error(
                    self.paperless_client,
                    self.document_id,
                    prepare.current_tags,
                    self.settings,
                )
                return WriteBackOutcome.QUARANTINED
        finally:
            if prepare.claimed:
                release_processing_tag(
                    self.paperless_client,
                    self.document_id,
                    self.settings.CLASSIFY_PROCESSING_TAG_ID,
                    purpose="classification",
                )
            self._log_classification_stats()

    def _prepare_or_divert(self) -> _PrepareOutcome:
        """
        Fetch the document and run pre-LLM screening checks.

        Returns a :class:`_PrepareOutcome` whose ``content`` is the raw OCR
        text when the document should proceed to classification, or ``None``
        when the document was diverted (error-tagged, unclaimed, empty-content
        requeued, or contained refusal markers).  ``claimed`` records whether
        the processing-lock tag was acquired; ``document`` is the refreshed
        Paperless document dict.
        """
        document = self.paperless_client.get_document(self.document_id)
        content: str = document.get("content", "") or ""  # type: ignore[assignment]
        current_tags = extract_tags(
            document, doc_id=self.document_id, context="classify-process"
        )

        def _divert(claimed: bool) -> _PrepareOutcome:
            return _PrepareOutcome(
                content=None,
                claimed=claimed,
                document=document,
                current_tags=current_tags,
            )

        if (
            self.settings.ERROR_TAG_ID is not None
            and self.settings.ERROR_TAG_ID in current_tags
        ):
            log.warning(
                "Document has error tag; skipping classification",
                doc_id=self.document_id,
            )
            # Strip only the classify pre-tag so the document leaves the queue.
            # ERROR_TAG_ID is already present — no need to re-finalise, which
            # would make a redundant Paperless write on every poll until the
            # pre-tag is removed.
            stripped = clean_pipeline_tags(current_tags, self.settings)
            try:
                self.paperless_client.update_document_metadata(
                    self.document_id, tags=stripped
                )
            except PAPERLESS_CALL_EXCEPTIONS:
                log.exception(
                    "Failed to remove classify pre-tag from errored document",
                    doc_id=self.document_id,
                )
            return _divert(claimed=False)

        claimed = claim_processing_tag(
            client=self.paperless_client,
            doc_id=self.document_id,
            tag_id=self.settings.CLASSIFY_PROCESSING_TAG_ID,
            purpose="classification",
        )
        if not claimed:
            return _divert(claimed=False)

        if not content.strip():
            log.warning(
                "Document has no OCR content; requeueing", doc_id=self.document_id
            )
            self._requeue_for_ocr(current_tags)
            return _divert(claimed=True)

        if needs_error_tag(content):
            log.warning(
                "OCR content contains refusal markers; marking error",
                doc_id=self.document_id,
            )
            finalise_document_with_error(
                self.paperless_client, self.document_id, current_tags, self.settings
            )
            return _divert(claimed=True)

        return _PrepareOutcome(
            content=content,
            claimed=True,
            document=document,
            current_tags=current_tags,
        )

    def _usable_result(
        self, result: ClassificationResult | None, current_tags: set[int]
    ) -> ClassificationResult | None:
        """
        Return the classifier output when it is fit to apply, else ``None``.

        An empty result or a vague document type is unusable: the document is
        finalised with an error tag and ``None`` is returned so the caller
        stops before applying metadata. ``None`` here is a handled outcome —
        the error has already been recorded — not a swallowed failure.
        """
        if not result or is_empty_classification(result):
            log.warning("Classification returned empty result", doc_id=self.document_id)
            finalise_document_with_error(
                self.paperless_client, self.document_id, current_tags, self.settings
            )
            return None

        if is_generic_document_type(result.document_type):
            log.warning(
                "Classification returned generic document type",
                doc_id=self.document_id,
                document_type=result.document_type,
            )
            finalise_document_with_error(
                self.paperless_client, self.document_id, current_tags, self.settings
            )
            return None
        return result

    def _truncate_content(self, content: str) -> tuple[str, list[str]]:
        """
        Apply page-based and character-based truncation in sequence.

        Returns ``(truncated_text, list_of_truncation_notes)``.
        """
        input_text = content
        truncation_notes: list[str] = []

        if self.settings.CLASSIFY_MAX_PAGES > 0:
            truncated, note = truncate_content_by_pages(
                content,
                self.settings.CLASSIFY_MAX_PAGES,
                self.settings.CLASSIFY_TAIL_PAGES,
                self.settings.CLASSIFY_HEADERLESS_CHAR_LIMIT,
            )
            if truncated != content:
                input_text = truncated
                if note:
                    truncation_notes.append(note)
                log.info(
                    "Truncated document content by pages",
                    doc_id=self.document_id,
                    max_pages=self.settings.CLASSIFY_MAX_PAGES,
                    tail_pages=self.settings.CLASSIFY_TAIL_PAGES,
                )

        # The character cap is a hard ceiling applied after page truncation;
        # it preserves the model footer so model tags survive.
        if (
            self.settings.CLASSIFY_MAX_CHARS > 0
            and len(input_text) > self.settings.CLASSIFY_MAX_CHARS
        ):
            input_text = truncate_content_by_chars(
                input_text, self.settings.CLASSIFY_MAX_CHARS
            )
            truncation_notes.append(
                max_char_truncation_note(self.settings.CLASSIFY_MAX_CHARS)
            )
            log.info(
                "Truncated document content by characters",
                doc_id=self.document_id,
                max_chars=self.settings.CLASSIFY_MAX_CHARS,
            )

        return input_text, truncation_notes

    def _requeue_for_ocr(self, tags: set[int]) -> None:
        """Move the document back to the OCR queue (content was empty)."""
        updated = clean_pipeline_tags(tags, self.settings)
        updated.add(self.settings.PRE_TAG_ID)
        try:
            self.paperless_client.update_document_metadata(
                self.document_id, tags=updated
            )
        except PAPERLESS_CALL_EXCEPTIONS:
            log.exception(
                "Failed to requeue document for OCR; marking error",
                doc_id=self.document_id,
            )
            finalise_document_with_error(
                self.paperless_client, self.document_id, tags, self.settings
            )
            return
        log.info("Requeued document for OCR", doc_id=self.document_id)

    def _build_tag_names(
        self,
        result: ClassificationResult,
        content: str,
        date_for_tags: str,
    ) -> list[str]:
        """Build the filtered and enriched tag name list from classification output."""
        base_tags = filter_blacklisted_tags(result.tags)
        base_tags = filter_redundant_tags(
            base_tags,
            result.correspondent,
            result.document_type,
            result.person,
        )
        return enrich_tags(
            base_tags,
            content,
            date_for_tags,
            self.settings.CLASSIFY_DEFAULT_COUNTRY_TAG,
            self.settings.CLASSIFY_TAG_LIMIT,
        )

    def _resolve_taxonomy_ids(
        self, result: ClassificationResult, tag_names: list[str]
    ) -> _ResolvedTaxonomyIds:
        """Resolve tag names and classification fields to Paperless IDs."""
        tag_ids = self.taxonomy_cache.get_or_create_tag_ids(tag_names)
        correspondent_id = (
            self.taxonomy_cache.get_or_create_correspondent_id(result.correspondent)
            if result.correspondent
            else None
        )
        document_type_id = (
            self.taxonomy_cache.get_or_create_document_type_id(result.document_type)
            if result.document_type
            else None
        )
        return _ResolvedTaxonomyIds(
            tag_ids=tuple(tag_ids),
            correspondent_id=correspondent_id,
            document_type_id=document_type_id,
        )

    def _apply_classification(
        self,
        document: dict[str, object],
        current_tags: set[int],
        content: str,
        result: ClassificationResult,
        model: str,
    ) -> None:
        """Apply the classifier's output to Paperless metadata and tags."""
        parsed_date = parse_document_date(result.document_date)
        date_for_tags = resolve_date_for_tags(parsed_date, document.get("created"))  # type: ignore[arg-type]

        tag_names = self._build_tag_names(result, content, date_for_tags)
        resolved = self._resolve_taxonomy_ids(result, tag_names)

        current_tags = clean_pipeline_tags(current_tags, self.settings)
        if self.settings.CLASSIFY_POST_TAG_ID is not None:
            current_tags.add(self.settings.CLASSIFY_POST_TAG_ID)
        current_tags.update(resolved.tag_ids)

        custom_fields = None
        if self.settings.CLASSIFY_PERSON_FIELD_ID and result.person:
            custom_fields = update_custom_fields(
                document.get("custom_fields"),  # type: ignore[arg-type]
                self.settings.CLASSIFY_PERSON_FIELD_ID,
                result.person,
            )

        language = normalise_language(result.language)
        title = result.title.strip() if result.title else ""

        # why: Paperless treats an empty-string title identically to None (no
        # update), so collapse "" → None at this API boundary to make the intent
        # explicit and avoid a redundant PATCH field.
        self.paperless_client.update_document_metadata(
            self.document_id,
            title=title or None,
            correspondent_id=resolved.correspondent_id,
            document_type_id=resolved.document_type_id,
            document_date=parsed_date,
            tags=current_tags,
            language=language,
            custom_fields=custom_fields,
        )

        log.info(
            "Document classification applied",
            doc_id=self.document_id,
            model=model,
            tags_added=len(resolved.tag_ids),
        )

    def _log_classification_stats(self) -> None:
        stats = self.classifier.get_stats()
        if not stats or not stats.get("attempts"):
            return
        log.info("Classification stats", doc_id=self.document_id, **stats)
