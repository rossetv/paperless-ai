"""Per-document classification orchestrator."""

from __future__ import annotations

import structlog

from common.claims import claim_processing_tag
from common.config import Settings
from common.paperless import PaperlessClient
from common.tags import (
    clean_pipeline_tags,
    extract_tags,
    finalize_document_with_error,
    release_processing_tag,
)
from .content_prep import (
    truncate_content_by_chars,
    truncate_content_by_pages,
    max_char_truncation_note,
)
from .metadata import (
    is_empty_classification,
    normalize_language,
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


class ClassificationProcessor:
    """
    Orchestrates the classification of a single Paperless document.

    Instantiated per-document by the daemon's thread pool.  Each instance
    gets its own :class:`PaperlessClient` (HTTP session) and a shared
    :class:`TaxonomyCache`.
    """

    def __init__(
        self,
        doc: dict,
        paperless_client: PaperlessClient,
        classifier: ClassificationProvider,
        taxonomy_cache: TaxonomyCache,
        settings: Settings,
    ):
        self.doc = doc
        self.paperless_client = paperless_client
        self.classifier = classifier
        self.taxonomy_cache = taxonomy_cache
        self.settings = settings
        self.doc_id: int = doc["id"]
        self.title: str = doc.get("title") or "<untitled>"

    def process(self) -> None:
        """
        Run the full classification workflow.

        Steps:
        1. Refresh the document from Paperless.
        2. Bail out early if the document already has an error tag.
        3. Claim the processing-lock tag.
        4. Requeue if the document has no OCR content yet.
        5. Truncate content (by pages, then by characters).
        6. Call the classification LLM.
        7. Validate the result (non-empty, non-generic).
        8. Apply metadata to Paperless (tags, correspondent, type, etc.).
        9. Release the processing-lock tag.
        """
        log.info("Classifying document", doc_id=self.doc_id, title=self.title)
        claimed = False
        try:
            document = self.paperless_client.get_document(self.doc_id)
            content = document.get("content", "") or ""
            current_tags = extract_tags(document, doc_id=self.doc_id, context="classify-process")

            if self.settings.ERROR_TAG_ID and self.settings.ERROR_TAG_ID in current_tags:
                log.warning(
                    "Document has error tag; skipping classification",
                    doc_id=self.doc_id,
                )
                self._finalize_with_error(current_tags)
                return

            claimed = claim_processing_tag(
                paperless_client=self.paperless_client,
                doc_id=self.doc_id,
                tag_id=self.settings.CLASSIFY_PROCESSING_TAG_ID,
                purpose="classification",
            )
            if not claimed:
                return

            if not content.strip():
                log.warning("Document has no OCR content; requeueing", doc_id=self.doc_id)
                self._requeue_for_ocr(current_tags)
                return

            input_text, truncation_notes = self._truncate_content(content)

            result, model = self.classifier.classify_text(
                input_text,
                self.taxonomy_cache.correspondent_names(),
                self.taxonomy_cache.document_type_names(),
                self.taxonomy_cache.tag_names(),
                truncation_note="\n".join(truncation_notes) if truncation_notes else None,
            )

            if not result or is_empty_classification(result):
                log.warning("Classification returned empty result", doc_id=self.doc_id)
                self._finalize_with_error(current_tags)
                return

            if is_generic_document_type(result.document_type):
                log.warning(
                    "Classification returned generic document type",
                    doc_id=self.doc_id,
                    document_type=result.document_type,
                )
                self._finalize_with_error(current_tags)
                return

            self._apply_classification(document, current_tags, content, result, model)
        finally:
            if claimed:
                release_processing_tag(
                    self.paperless_client,
                    self.doc_id,
                    self.settings.CLASSIFY_PROCESSING_TAG_ID,
                    purpose="classification",
                )
            self._log_classification_stats()

    def _truncate_content(self, content: str) -> tuple[str, list[str]]:
        """
        Apply page-based and character-based truncation in sequence.

        Returns ``(truncated_text, list_of_truncation_notes)``.
        """
        input_text = content
        truncation_notes: list[str] = []

        # Page-based truncation
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
                    doc_id=self.doc_id,
                    max_pages=self.settings.CLASSIFY_MAX_PAGES,
                    tail_pages=self.settings.CLASSIFY_TAIL_PAGES,
                )

        # Character-based truncation (hard cap, preserves footer)
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
                doc_id=self.doc_id,
                max_chars=self.settings.CLASSIFY_MAX_CHARS,
            )

        return input_text, truncation_notes

    def _requeue_for_ocr(self, tags: set[int]) -> None:
        """Move the document back to the OCR queue (content was empty)."""
        updated = clean_pipeline_tags(tags, self.settings)
        updated.add(self.settings.PRE_TAG_ID)
        self.paperless_client.update_document_metadata(self.doc_id, tags=list(updated))
        log.info("Requeued document for OCR", doc_id=self.doc_id)

    def _finalize_with_error(self, tags: set[int]) -> None:
        """
        Mark the document with an error tag and clear pipeline tags.

        Delegates to :func:`common.tags.finalize_document_with_error`.
        """
        finalize_document_with_error(
            self.paperless_client,
            self.doc_id,
            tags,
            self.settings,
        )

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
    ) -> tuple[list[int], int | None, int | None]:
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
        return tag_ids, correspondent_id, document_type_id

    def _apply_classification(
        self,
        document: dict,
        current_tags: set[int],
        content: str,
        result: ClassificationResult,
        model: str,
    ) -> None:
        """Apply the classifier's output to Paperless metadata and tags."""
        if needs_error_tag(content):
            log.warning(
                "OCR content contains refusal markers; marking error",
                doc_id=self.doc_id,
            )
            self._finalize_with_error(current_tags)
            return

        parsed_date = parse_document_date(result.document_date)
        date_for_tags = resolve_date_for_tags(parsed_date, document.get("created"))

        tag_names = self._build_tag_names(result, content, date_for_tags)
        tag_ids, correspondent_id, document_type_id = self._resolve_taxonomy_ids(
            result, tag_names
        )

        # Merge new tag IDs with cleaned existing tags
        current_tags = clean_pipeline_tags(current_tags, self.settings)
        if self.settings.CLASSIFY_POST_TAG_ID:
            current_tags.add(self.settings.CLASSIFY_POST_TAG_ID)
        current_tags.update(tag_ids)

        custom_fields = None
        if self.settings.CLASSIFY_PERSON_FIELD_ID and result.person:
            custom_fields = update_custom_fields(
                document.get("custom_fields"),
                self.settings.CLASSIFY_PERSON_FIELD_ID,
                result.person,
            )

        language = normalize_language(result.language)
        title = result.title.strip() if result.title else ""

        self.paperless_client.update_document_metadata(
            self.doc_id,
            title=title or None,
            correspondent_id=correspondent_id,
            document_type_id=document_type_id,
            document_date=parsed_date,
            tags=list(current_tags),
            language=language,
            custom_fields=custom_fields,
        )

        log.info(
            "Document classification applied",
            doc_id=self.doc_id,
            model=model,
            tags_added=len(tag_ids),
        )

    def _log_classification_stats(self) -> None:
        stats = self.classifier.get_stats()
        if not stats or not stats.get("attempts"):
            return
        log.info("Classification stats", doc_id=self.doc_id, **stats)
