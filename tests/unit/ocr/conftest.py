"""Shared builders for the ocr.worker unit tests."""

from __future__ import annotations

from typing import Any

import httpx
from PIL import Image

from ocr.image_converter import PageSource
from ocr.worker import OcrProcessor
from tests.helpers.factories import make_document, make_settings_obj
from tests.helpers.mocks import make_mock_ocr_provider, make_mock_paperless


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    """Build an ``httpx.HTTPStatusError`` carrying *status*."""
    request = httpx.Request("PATCH", "http://paperless:8000/api/documents/1/")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"{status}", request=request, response=response)


def make_processor(
    doc: Any = None,
    paperless: Any = None,
    ocr_provider: Any = None,
    settings: Any = None,
    **setting_overrides: Any,
) -> OcrProcessor:
    """Create an OcrProcessor with mocked dependencies.

    Any dependency left as ``None`` is built from the shared factories; extra
    keyword arguments become Settings field overrides.
    """
    if doc is None:
        doc = make_document()
    if settings is None:
        settings = make_settings_obj(**setting_overrides)
    if paperless is None:
        paperless = make_mock_paperless()
    if ocr_provider is None:
        ocr_provider = make_mock_ocr_provider()
    return OcrProcessor(doc, paperless, ocr_provider, settings)


def make_image() -> Image.Image:
    """Create a small non-blank test image."""
    return Image.new("RGB", (10, 10), color="red")


def make_page_source(images: list[Image.Image]) -> PageSource:
    """Wrap in-memory images in a PageSource, the backing non-PDF documents use.

    PDFs and non-PDFs share the :class:`PageSource` interface, so the tests use
    the real in-memory backing rather than mocking the type.
    """
    return PageSource(images=list(images))
