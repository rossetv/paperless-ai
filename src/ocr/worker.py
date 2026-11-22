"""Per-document OCR processing orchestrator."""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import structlog

from common.claims import claim_processing_tag
from common.config import Settings
from common.paperless import (
    PAPERLESS_CALL_EXCEPTIONS,
    PaperlessClient,
    is_permanent_paperless_error,
)
from common.per_document import WriteBackOutcome
from common.shutdown import is_shutdown_requested
from common.tags import (
    clean_pipeline_tags,
    extract_tags,
    finalise_document_with_error,
    get_latest_tags,
    release_processing_tag,
)
from common.content_checks import contains_redacted_marker
from .born_digital import classify_original
from .image_converter import ImageConversionError, PageSource, open_page_source
from .provider import OcrProvider, is_model_refusal
from .text_assembly import OCR_ERROR_MARKER, PageResult, assemble_full_text

log = structlog.get_logger(__name__)


class OcrProcessor:
    """OCRs one Paperless document and reports its write-back outcome."""

    def __init__(
        self,
        doc: dict,
        paperless_client: PaperlessClient,
        ocr_provider: OcrProvider,
        settings: Settings,
    ) -> None:
        self.doc = doc
        self.paperless_client = paperless_client
        self.ocr_provider = ocr_provider
        self.settings = settings
        self.doc_id: int = doc["id"]
        self.title: str = doc.get("title") or "<untitled>"

    def process(self) -> WriteBackOutcome | None:
        """Run the OCR workflow for one document.

        Returns ``SAVED``, ``QUARANTINED`` on a permanent Paperless rejection,
        or ``None`` when no transcription was saved.
        """
        log.info("Processing document", doc_id=self.doc_id, title=self.title)
        self.ocr_provider.reset_stats()
        start_time = dt.datetime.now()
        claimed = False
        success = False
        try:
            document = self.paperless_client.get_document(self.doc_id)
            self.doc = document
            current_tags = extract_tags(
                document, doc_id=self.doc_id, context="ocr-process"
            )

            if (
                self.settings.ERROR_TAG_ID is not None
                and self.settings.ERROR_TAG_ID in current_tags
            ):
                log.warning("Document has error tag; skipping OCR", doc_id=self.doc_id)
                finalise_document_with_error(
                    self.paperless_client, self.doc_id, current_tags, self.settings
                )
                return None

            claimed = claim_processing_tag(
                client=self.paperless_client,
                doc_id=self.doc_id,
                tag_id=self.settings.OCR_PROCESSING_TAG_ID,
                purpose="ocr",
            )
            if not claimed:
                return None

            stop, outcome = self._try_skip_born_digital(document)
            if stop:
                # A clean skip is a success; a quarantine is not.
                success = outcome is None
                return outcome

            pages = self._download_and_convert(current_tags)
            if pages is None:
                return None

            try:
                page_count = len(pages)
                page_results, failed_pages = self._ocr_pages_in_parallel(pages)
            finally:
                pages.close()

            if failed_pages:
                log.warning(
                    "OCR failed on some pages; marking document as error",
                    doc_id=self.doc_id,
                    failed_pages=failed_pages,
                )

            full_text, models_used = assemble_full_text(
                page_count,
                page_results,
                include_page_models=self.settings.OCR_INCLUDE_PAGE_MODELS,
            )
            try:
                outcome = self._update_paperless_document(full_text, models_used)
                success = outcome is WriteBackOutcome.SAVED
                return outcome
            except PAPERLESS_CALL_EXCEPTIONS as exc:
                # A 4xx is permanent: re-queuing would re-OCR the whole document,
                # and spend the tokens, on every poll. Quarantine it with the
                # transcription we have. Transient errors re-raise for a retry.
                if not is_permanent_paperless_error(exc):
                    raise
                log.error(
                    "Paperless rejected OCR write; quarantining document to "
                    "break the re-OCR loop",
                    doc_id=self.doc_id,
                    error=str(exc),
                )
                finalise_document_with_error(
                    self.paperless_client,
                    self.doc_id,
                    get_latest_tags(
                        self.paperless_client, self.doc_id, fallback_doc=self.doc
                    ),
                    self.settings,
                    content=full_text,
                )
                return WriteBackOutcome.QUARANTINED
        finally:
            if claimed:
                release_processing_tag(
                    self.paperless_client,
                    self.doc_id,
                    self.settings.OCR_PROCESSING_TAG_ID,
                    purpose="ocr",
                )
            self._log_ocr_stats()
            elapsed = (dt.datetime.now() - start_time).total_seconds()
            log.info(
                "Finished processing document",
                doc_id=self.doc_id,
                elapsed_time=f"{elapsed:.2f}s",
                success=success,
            )

    def _try_skip_born_digital(
        self, document: dict
    ) -> tuple[bool, WriteBackOutcome | None]:
        """Skip OCR for a born-digital PDF, tagging it done.

        Returns ``(True, None)`` on a clean skip, ``(True, QUARANTINED)`` on a
        permanent skip-write failure, or ``(False, None)`` to run OCR.
        Transient write errors re-raise.
        """
        if not self.settings.OCR_SKIP_BORN_DIGITAL:
            return (False, None)
        mime = document.get("mime_type") or ""
        if mime and "pdf" not in mime.lower():
            return (False, None)  # image upload -> scan -> OCR
        if not (document.get("content") or "").strip():
            return (False, None)  # no Paperless text layer to keep
        try:
            data, content_type = self.paperless_client.download_original(self.doc_id)
        except PAPERLESS_CALL_EXCEPTIONS:
            log.warning("born_digital.original_fetch_failed", doc_id=self.doc_id)
            return (False, None)  # fail-safe -> OCR
        if "pdf" not in (content_type or "").lower():
            return (False, None)
        decision = classify_original(
            data, min_chars=self.settings.OCR_BORN_DIGITAL_MIN_CHARS
        )
        log.info(
            "born_digital.decision",
            doc_id=self.doc_id,
            skip=decision.skip,
            reason=decision.reason,
            **decision.signals,
        )
        if not decision.skip:
            return (False, None)
        tags = clean_pipeline_tags(
            get_latest_tags(self.paperless_client, self.doc_id, fallback_doc=self.doc),
            self.settings,
        )
        tags.add(self.settings.POST_TAG_ID)
        if self.settings.OCR_BORN_DIGITAL_TAG_ID is not None:
            tags.add(self.settings.OCR_BORN_DIGITAL_TAG_ID)
        try:
            self.paperless_client.update_document_metadata(self.doc_id, tags=tags)
        except PAPERLESS_CALL_EXCEPTIONS as exc:
            if not is_permanent_paperless_error(exc):
                raise
            log.exception("born_digital.skip_write_rejected", doc_id=self.doc_id)
            finalise_document_with_error(
                self.paperless_client,
                self.doc_id,
                get_latest_tags(
                    self.paperless_client, self.doc_id, fallback_doc=self.doc
                ),
                self.settings,
            )
            return (True, WriteBackOutcome.QUARANTINED)
        log.info(
            "born_digital.skipped",
            doc_id=self.doc_id,
            added_tag=self.settings.POST_TAG_ID,
        )
        return (True, None)

    def _download_and_convert(self, current_tags: set[int]) -> PageSource | None:
        """Download the document as a :class:`PageSource`.

        Returns ``None`` when it cannot be decoded (error-tagging it) or has no
        pages.
        """
        content, content_type = self.paperless_client.download_content(self.doc_id)
        try:
            pages = open_page_source(
                content,
                content_type,
                dpi=self.settings.OCR_DPI,
                max_side=self.settings.OCR_MAX_SIDE,
                timeout=self.settings.REQUEST_TIMEOUT,
            )
        except ImageConversionError:
            log.exception(
                "Unable to convert document to images; marking error",
                doc_id=self.doc_id,
            )
            finalise_document_with_error(
                self.paperless_client, self.doc_id, current_tags, self.settings
            )
            return None

        if len(pages) == 0:
            log.warning("Document has no pages to process", doc_id=self.doc_id)
            pages.close()
            return None
        return pages

    def _ocr_pages_in_parallel(
        self, pages: PageSource
    ) -> tuple[list[PageResult], list[int]]:
        """OCR all pages concurrently; return the results and failed page numbers."""
        page_count = len(pages)
        with ThreadPoolExecutor(
            max_workers=self.settings.PAGE_WORKERS,
            thread_name_prefix="ocr-page",
        ) as executor:
            future_to_index = {
                executor.submit(self._ocr_one_page, pages, i): i
                for i in range(page_count)
            }
            results: list[PageResult] = [PageResult(text="", model="")] * page_count
            failed_pages: list[int] = []
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    results[index] = future.result()
                except Exception:
                    # One page's failure becomes an error-marked page so the
                    # rest still assemble.
                    log.exception("OCR failed on page", page_num=index + 1)
                    failed_pages.append(index + 1)
                    results[index] = PageResult(
                        text=f"{OCR_ERROR_MARKER} Failed to OCR page {index + 1}.",
                        model="",
                    )
            return results, failed_pages

    def _ocr_one_page(self, pages: PageSource, index: int) -> PageResult:
        """Load page *index*, transcribe it, and free its bitmap.

        Loading inside the worker thread bounds resident pages to the pool size.
        """
        image = pages.load_page(index)
        try:
            return self.ocr_provider.transcribe_image(
                image, doc_id=self.doc_id, page_num=index + 1
            )
        finally:
            try:
                image.close()
            except OSError:
                log.warning("Failed to close image", doc_id=self.doc_id, exc_info=True)

    def _update_paperless_document(
        self, full_text: str, models_used: set[str]
    ) -> WriteBackOutcome | None:
        """Write *full_text* back to Paperless and swap the pipeline tags.

        Returns ``None`` for bad content (empty, refusal, OCR error marker),
        which the circuit breaker must not count as a success.
        """
        if (
            not full_text.strip()
            or OCR_ERROR_MARKER in full_text
            or contains_redacted_marker(full_text)
            or is_model_refusal(
                full_text,
                self.settings.OCR_REFUSAL_MARKERS,
                self.settings.REFUSAL_MARK,
            )
        ):
            if is_shutdown_requested():
                # A shutdown-aborted flex-capacity wait fills pages with the
                # refusal sentinel; error-tagging would quarantine a healthy
                # document on a routine deploy. Leave it queued for the next boot.
                log.warning(
                    "OCR error content during shutdown; leaving document queued",
                    doc_id=self.doc_id,
                )
                return None
            reason = (
                "no text" if not full_text.strip() else "error/refusal/redacted markers"
            )
            log.warning(
                "OCR produced error content; marking error",
                doc_id=self.doc_id,
                reason=reason,
            )
            finalise_document_with_error(
                self.paperless_client,
                self.doc_id,
                get_latest_tags(
                    self.paperless_client, self.doc_id, fallback_doc=self.doc
                ),
                self.settings,
                content=full_text,
            )
            return None

        current_tags = get_latest_tags(
            self.paperless_client, self.doc_id, fallback_doc=self.doc
        )
        current_tags = clean_pipeline_tags(current_tags, self.settings)
        current_tags.add(self.settings.POST_TAG_ID)

        self.paperless_client.update_document(self.doc_id, full_text, current_tags)
        log.info(
            "Updated document tags",
            doc_id=self.doc_id,
            removed_tag=self.settings.PRE_TAG_ID,
            added_tag=self.settings.POST_TAG_ID,
        )
        return WriteBackOutcome.SAVED

    def _log_ocr_stats(self) -> None:
        stats = self.ocr_provider.get_stats()
        if not stats or not stats.get("attempts"):
            return
        log.info("OCR stats", doc_id=self.doc_id, **stats)
