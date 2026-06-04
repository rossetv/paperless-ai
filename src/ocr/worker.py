"""Per-document OCR processing orchestrator."""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import structlog

from common.claims import claim_processing_tag
from common.config import Settings
from common.paperless import PaperlessClient
from common.tags import (
    ErrorFinaliserMixin,
    clean_pipeline_tags,
    extract_tags,
    get_latest_tags,
    release_processing_tag,
)
from common.content_checks import is_error_content
from .image_converter import ImageConversionError, PageSource, open_page_source
from .provider import OcrProvider
from .text_assembly import OCR_ERROR_MARKER, PageResult, assemble_full_text

log = structlog.get_logger(__name__)


class OcrProcessor(ErrorFinaliserMixin):
    """
    Orchestrates the OCR processing of a single Paperless document.

    Instantiated per-document by the daemon's thread pool.
    """

    def __init__(
        self,
        doc: dict,
        paperless_client: PaperlessClient,
        ocr_provider: OcrProvider,
        settings: Settings,
    ):
        self.doc = doc
        self.paperless_client = paperless_client
        self.ocr_provider = ocr_provider
        self.settings = settings
        self.doc_id: int = doc["id"]
        self.title: str = doc.get("title") or "<untitled>"

    def process(self) -> None:
        """
        Execute the end-to-end OCR workflow for this document.

        Steps: refresh → check error tag → claim lock → download →
        convert to images → OCR pages → assemble text → update Paperless →
        release lock.
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
                self._finalise_with_error(current_tags)
                return

            claimed = claim_processing_tag(
                client=self.paperless_client,
                doc_id=self.doc_id,
                tag_id=self.settings.OCR_PROCESSING_TAG_ID,
                purpose="ocr",
            )
            if not claimed:
                return

            pages = self._download_and_convert(current_tags)
            if pages is None:
                return

            try:
                page_count = len(pages)
                page_results, failed_pages = self._ocr_pages_in_parallel(pages)
            finally:
                # Owns the page source's whole lifetime: this releases the PDF
                # temp directory (or the in-memory images) even if OCR raised.
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
            self._update_paperless_document(full_text, models_used)
            success = True
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

    def _download_and_convert(self, current_tags: set[int]) -> PageSource | None:
        """
        Download the document and open it as a streamable page source.

        For PDFs the pages are rasterised to temp files and loaded one at a time
        during OCR, so the whole document never sits in RAM; the returned
        :class:`PageSource` owns that temp storage and is closed by the caller.

        Returns the page source, or ``None`` when processing should stop: an
        undecodable download finalises the document with an error tag, and a
        document with no pages is logged and skipped.
        """
        content, content_type = self.paperless_client.download_content(self.doc_id)
        try:
            pages = open_page_source(
                content,
                content_type,
                dpi=self.settings.OCR_DPI,
                max_side=self.settings.OCR_MAX_SIDE,
            )
        except ImageConversionError:
            log.exception(
                "Unable to convert document to images; marking error",
                doc_id=self.doc_id,
            )
            self._finalise_with_error(current_tags)
            return None

        if len(pages) == 0:
            log.warning("Document has no pages to process", doc_id=self.doc_id)
            pages.close()
            return None
        return pages

    def _ocr_pages_in_parallel(
        self, pages: PageSource
    ) -> tuple[list[PageResult], list[int]]:
        """
        Run OCR on each page concurrently and preserve the original order.

        Each task loads its page only when it starts and closes the bitmap the
        moment transcription returns, so at most ``PAGE_WORKERS`` page images
        are resident at once — the document is streamed, never fully unpacked.

        Returns ``(page_results, failed_page_numbers)``.
        """
        page_count = len(pages)
        with ThreadPoolExecutor(max_workers=self.settings.PAGE_WORKERS) as executor:
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
                    # rationale: per-page worker-dispatch boundary
                    # (CODE_GUIDELINES §6.4, site 2) — one page's failure is
                    # logged with its traceback and isolated as an error-marked
                    # PageResult so the remaining pages still assemble.
                    log.exception("OCR failed on page", page_num=index + 1)
                    failed_pages.append(index + 1)
                    results[index] = PageResult(
                        text=f"{OCR_ERROR_MARKER} Failed to OCR page {index + 1}.",
                        model="",
                    )
            return results, failed_pages

    def _ocr_one_page(self, pages: PageSource, index: int) -> PageResult:
        """Load page *index*, transcribe it, and free its bitmap.

        The load is the memory-heavy step, so it happens inside the worker
        thread (bounding resident pages to the pool size) and the image is
        closed in a ``finally`` so a transcription failure cannot leak it.
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

    def _has_ocr_errors(self, text: str) -> bool:
        """Return True if the OCR output contains error/refusal/redacted markers."""
        return OCR_ERROR_MARKER in text or is_error_content(
            text, self.settings.OCR_REFUSAL_MARKERS
        )

    def _update_paperless_document(self, full_text: str, models_used: set[str]) -> None:
        """
        Upload OCR text and update tags in Paperless.

        Detects error conditions (empty text, refusal markers, OCR errors)
        and routes to :meth:`_finalise_with_error` instead of the happy path.
        """
        if not full_text.strip() or self._has_ocr_errors(full_text):
            reason = (
                "no text" if not full_text.strip() else "error/refusal/redacted markers"
            )
            log.warning(
                "OCR produced error content; marking error",
                doc_id=self.doc_id,
                reason=reason,
            )
            self._finalise_with_error(
                get_latest_tags(
                    self.paperless_client, self.doc_id, fallback_doc=self.doc
                ),
                content=full_text,
            )
            return

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

    def _log_ocr_stats(self) -> None:
        stats = self.ocr_provider.get_stats()
        if not stats or not stats.get("attempts"):
            return
        log.info("OCR stats", doc_id=self.doc_id, **stats)
