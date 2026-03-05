"""Per-document OCR processing orchestrator."""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import structlog
from PIL import Image

from common.claims import claim_processing_tag
from common.config import Settings
from common.paperless import PaperlessClient
from common.tags import (
    extract_tags,
    finalize_document_with_error,
    get_latest_tags,
    release_processing_tag,
)
from common.utils import is_error_content
from .image_converter import bytes_to_images
from .provider import OcrProvider
from .text_assembly import OCR_ERROR_MARKER, assemble_full_text

log = structlog.get_logger(__name__)


class DocumentProcessor:
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
        start_time = dt.datetime.now()
        claimed = False
        try:
            document = self.paperless_client.get_document(self.doc_id)
            self.doc = document
            current_tags = extract_tags(document, doc_id=self.doc_id, context="ocr-process")

            if self.settings.ERROR_TAG_ID and self.settings.ERROR_TAG_ID in current_tags:
                log.warning("Document has error tag; skipping OCR", doc_id=self.doc_id)
                self._finalize_with_error(current_tags)
                return

            claimed = claim_processing_tag(
                paperless_client=self.paperless_client,
                doc_id=self.doc_id,
                tag_id=self.settings.OCR_PROCESSING_TAG_ID,
                purpose="ocr",
            )
            if not claimed:
                return

            content, content_type = self.paperless_client.download_content(self.doc_id)
            try:
                images = bytes_to_images(content, content_type, dpi=self.settings.OCR_DPI)
            except RuntimeError:
                log.exception(
                    "Unable to convert document to images; marking error",
                    doc_id=self.doc_id,
                )
                self._finalize_with_error(current_tags)
                return

            if not images:
                log.warning("Document has no pages to process", doc_id=self.doc_id)
                return

            try:
                page_results, failed_pages = self._ocr_pages_in_parallel(images)
            finally:
                for image in images:
                    try:
                        image.close()
                    except OSError:
                        log.warning("Failed to close image", doc_id=self.doc_id, exc_info=True)

            if failed_pages:
                log.warning(
                    "OCR failed on some pages; marking document as error",
                    doc_id=self.doc_id,
                    failed_pages=failed_pages,
                )

            full_text, models_used = assemble_full_text(
                len(images),
                page_results,
                include_page_models=self.settings.OCR_INCLUDE_PAGE_MODELS,
            )
            self._update_paperless_document(full_text, models_used)
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
        )

    def _ocr_pages_in_parallel(
        self, images: list[Image.Image]
    ) -> tuple[list[tuple[str, str]], list[int]]:
        """
        Run OCR on each page concurrently and preserve the original order.

        Returns ``(page_results, failed_page_numbers)`` where each page result
        is a ``(text, model_used)`` tuple.
        """
        with ThreadPoolExecutor(max_workers=self.settings.PAGE_WORKERS) as executor:
            future_to_index = {
                executor.submit(
                    self.ocr_provider.transcribe_image,
                    img,
                    doc_id=self.doc_id,
                    page_num=i + 1,
                ): i
                for i, img in enumerate(images)
            }
            results: list[tuple[str, str]] = [("", "")] * len(images)
            failed_pages: list[int] = []
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    results[index] = future.result()
                except Exception:
                    log.exception("OCR failed on page", page_num=index + 1)
                    failed_pages.append(index + 1)
                    results[index] = (
                        f"{OCR_ERROR_MARKER} Failed to OCR page {index + 1}.",
                        "",
                    )
            return results, failed_pages

    def _has_ocr_errors(self, text: str) -> bool:
        """Return True if the OCR output contains error/refusal/redacted markers."""
        return OCR_ERROR_MARKER in text or is_error_content(
            text, (self.settings.REFUSAL_MARK,)
        )

    def _update_paperless_document(self, full_text: str, models_used: set[str]) -> None:
        """
        Upload OCR text and update tags in Paperless.

        Detects error conditions (empty text, refusal markers, OCR errors)
        and routes to :meth:`_finalize_with_error` instead of the happy path.
        """
        if not full_text.strip() or self._has_ocr_errors(full_text):
            reason = "no text" if not full_text.strip() else "error/refusal/redacted markers"
            log.warning("OCR produced error content; marking error", doc_id=self.doc_id, reason=reason)
            self._finalize_with_error(
                get_latest_tags(
                    self.paperless_client, self.doc_id, fallback_doc=self.doc
                ),
                content=full_text,
            )
            return

        current_tags = get_latest_tags(
            self.paperless_client, self.doc_id, fallback_doc=self.doc
        )
        current_tags.discard(self.settings.PRE_TAG_ID)
        if self.settings.OCR_PROCESSING_TAG_ID:
            current_tags.discard(self.settings.OCR_PROCESSING_TAG_ID)
        current_tags.add(self.settings.POST_TAG_ID)

        self.paperless_client.update_document(
            self.doc_id, full_text, list(current_tags)
        )
        log.info(
            "Updated document tags",
            doc_id=self.doc_id,
            removed_tag=self.settings.PRE_TAG_ID,
            added_tag=self.settings.POST_TAG_ID,
        )

    def _finalize_with_error(self, tags: set[int], *, content: str | None = None) -> None:
        """
        Mark the document as errored and remove all pipeline tags.

        Delegates to :func:`common.tags.finalize_document_with_error`.
        """
        finalize_document_with_error(
            self.paperless_client,
            self.doc_id,
            tags,
            self.settings,
            content=content,
        )

    def _log_ocr_stats(self) -> None:
        stats = self.ocr_provider.get_stats()
        if not stats or not stats.get("attempts"):
            return
        log.info("OCR stats", doc_id=self.doc_id, **stats)
