"""Turns document bytes (PDF, PNG, TIFF, ...) into a streamable page source.

Memory is the binding constraint for the OCR daemon: it runs
``DOCUMENT_WORKERS`` documents at once, each fanning pages across
``PAGE_WORKERS``, on a memory-capped arm64 container. Two properties of this
module keep peak RSS bounded:

- **Rasterise at the target size, not full DPI.** A PDF page rendered at
  300 DPI is ~2480x3509 (~26 MB decoded); the provider immediately shrinks it
  to ``OCR_MAX_SIDE`` (default 1600) before sending it to the model, so the
  full-resolution raster exists only to be thrown away. We ask poppler to scale
  the long side to ``OCR_MAX_SIDE`` up front (``size=max_side`` ->
  ``pdftoppm -scale-to``), so the bitmap that ever reaches RAM is ~1133x1600
  (~5 MB) — roughly a quarter of the bytes for a portrait A4 page.

- **Stream pages instead of holding the whole document.** Decoding every page
  of a 50-page scan into one in-memory list is what OOM-kills the container.
  For PDFs we hand poppler an *output folder* and take back file *paths*
  (``paths_only=True``); the worker opens, OCRs, and deletes one page at a time,
  so at most ~``PAGE_WORKERS`` page bitmaps are ever resident. The folder's
  lifetime is owned by the caller via :class:`PageSource`'s context-manager
  protocol.

The non-PDF formats (PNG/JPEG/TIFF) are small and already decoded by Pillow in
one shot, so they stay an in-memory list behind the same :class:`PageSource`
interface — the worker consumes both the streamed and the in-memory case
identically.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from io import BytesIO
from types import TracebackType
from typing import Any, cast

from PIL import Image, ImageSequence, UnidentifiedImageError
from pdf2image import convert_from_bytes

# pdf2image renders PDF pages to this raster format when streaming to a folder.
# PNG is lossless (no OCR-quality loss versus the default PPM) and far smaller
# on disk, which matters when a large scan's pages sit in the temp dir waiting
# their turn.
_PDF_PAGE_FORMAT = "png"


class ImageConversionError(Exception):
    """Raised when raw document bytes cannot be decoded into images.

    The OCR daemon's domain error for an undecodable download — Pillow could
    not identify the bytes, or the file is truncated/corrupt. The worker
    catches this to mark the document as errored rather than letting a generic
    exception escape (CODE_GUIDELINES §6.1).
    """


class PageSource:
    """A sized, page-at-a-time view over a document's pages.

    The OCR worker needs three things from a converted document: the page
    *count* up front (for page numbering and assembly), each page *loaded* only
    when it is about to be transcribed, and the backing storage *released*
    afterwards. :class:`PageSource` provides exactly those and nothing more.

    Two backings hide behind one interface:

    - **PDF**: a list of temp-file paths plus the temp directory that owns them.
      :meth:`load_page` opens a path, fully decodes it into a standalone image,
      and deletes the file; the temp directory is removed on context exit. This
      keeps at most as many page bitmaps resident as there are concurrent
      callers.
    - **Non-PDF (PNG/JPEG/TIFF)**: a list of already-decoded :class:`PIL.Image`
      objects. :meth:`load_page` hands one out and forgets it; the images are
      closed on context exit.

    Use it as a context manager so the backing storage is always released::

        with open_page_source(content, content_type, ...) as pages:
            for i in range(len(pages)):
                with pages.load_page(i) as image:
                    ...  # transcribe; the image is independent of any file

    Every image returned by :meth:`load_page` is fully loaded into memory and
    depends on no open file handle, so it stays valid after the source — or the
    individual page file — is gone.
    """

    def __init__(
        self,
        *,
        paths: list[str] | None = None,
        temp_dir: str | None = None,
        images: list[Image.Image] | None = None,
    ) -> None:
        # Exactly one backing is populated; the other stays empty. ``temp_dir``
        # is only set for the PDF backing and is the single thing we must clean.
        self._paths = paths or []
        self._temp_dir = temp_dir
        self._images = images or []

    def __len__(self) -> int:
        """Return the number of pages, known before any page is loaded."""
        return len(self._images) if self._images else len(self._paths)

    def load_page(self, index: int) -> Image.Image:
        """Load page *index* (0-based) as a fully in-memory image.

        For the PDF backing the page file is decoded and then deleted, so the
        temp directory drains as the document is processed and a crash partway
        through still frees the pages already consumed. For the in-memory
        backing the pre-decoded image is returned as-is.

        The returned image owns its pixels outright — no open file handle — so
        the caller may use it after this :class:`PageSource` is closed. The
        caller is responsible for closing the returned image.
        """
        if self._images:
            # Hand back a copy, not the retained object: the worker closes
            # every image it loads in a finally block (CODE_GUIDELINES §1.4),
            # and closing the stored copy would invalidate the source's own
            # reference — corrupting any subsequent load_page of the same index
            # and the double-close in close(). The PDF path copies for the same
            # reason; the in-memory path must match.
            return self._images[index].copy()

        path = self._paths[index]
        try:
            with Image.open(path) as handle:
                # load() forces the full decode into RAM; copy() detaches the
                # result from the file object so deleting the file below cannot
                # invalidate it (CODE_GUIDELINES §1.4 — the no-open-handle
                # contract is designed, not hoped for).
                handle.load()
                image = handle.copy()
        finally:
            # Delete eagerly so peak disk usage tracks the unprocessed tail,
            # not the whole document. A missing file is fine — context exit
            # would only have removed it anyway.
            try:
                os.remove(path)
            except OSError:
                pass
        return image

    def close(self) -> None:
        """Release all backing storage: the temp directory or the held images.

        Idempotent and exception-safe — called from the worker's ``finally`` and
        from :meth:`__exit__`, so it must never raise on a partially consumed or
        already-closed source.
        """
        if self._temp_dir is not None:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
            self._paths = []
        for image in self._images:
            try:
                image.close()
            except OSError:
                pass
        self._images = []

    def __enter__(self) -> PageSource:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def open_page_source(
    content: bytes,
    content_type: str,
    *,
    dpi: int = 300,
    max_side: int | None = None,
) -> PageSource:
    """Decode raw document bytes into a streamable :class:`PageSource`.

    - PDFs are rasterised one image per page and streamed via temp files (see
      the module docstring) so the whole document never sits in RAM at once.
    - Image formats (PNG/JPEG/TIFF/...) are loaded via Pillow into memory.
    - Multi-frame images (e.g. TIFF) are expanded into one image per frame.

    Args:
        content: The raw file bytes.
        content_type: MIME type (e.g. ``"application/pdf"``, ``"image/tiff"``).
        dpi: Rendering resolution for PDF rasterisation (default 300). Ignored
            when *max_side* drives the output size, but still passed to poppler
            so DPI-dependent hinting stays sensible.
        max_side: If set, scale each rasterised PDF page so its longer side is
            this many pixels (``pdftoppm -scale-to``). This is the long-side
            cap, not a width cap — ``size=(max_side, None)`` would only fix the
            *width* and leave a portrait page taller than intended, so an int is
            used deliberately. Leaves non-PDF inputs untouched; the provider
            still clamps every page to ``OCR_MAX_SIDE`` as a backstop.

    Returns:
        A :class:`PageSource`; use it as a context manager so its backing
        storage (temp directory or in-memory images) is released.

    Raises:
        ImageConversionError: If the image bytes cannot be identified by Pillow
            or the file is truncated/corrupt.
    """
    if "pdf" in content_type.lower():
        return _pdf_to_page_source(content, dpi=dpi, max_side=max_side)

    try:
        img = Image.open(BytesIO(content))
        img.load()
        if getattr(img, "n_frames", 1) > 1:
            frames = [frame.copy() for frame in ImageSequence.Iterator(img)]
            img.close()
            return PageSource(images=frames)
        # Copy the frame so the backing BytesIO can be released immediately.
        single = img.copy()
        img.close()
        return PageSource(images=[single])
    except (UnidentifiedImageError, OSError) as e:
        # OSError covers a truncated or otherwise corrupt image — Pillow
        # identifies the format but fails partway through Image.load().
        raise ImageConversionError(f"Unable to open image: {e}") from e


def _pdf_to_page_source(
    content: bytes, *, dpi: int, max_side: int | None
) -> PageSource:
    """Rasterise a PDF to per-page temp files and wrap them in a PageSource.

    poppler writes one image file per page into a freshly created temp
    directory and we take back the paths (``paths_only=True``); the directory's
    lifetime then belongs to the returned :class:`PageSource`. On any failure
    the directory is removed before propagating, so a half-written render never
    leaks a temp dir.
    """
    temp_dir = tempfile.mkdtemp(prefix="paperless-ocr-")
    # Omit ``size`` entirely when no cap is requested: poppler's runtime default
    # is ``None`` but the published type rejects it, and an absent kwarg is the
    # honest way to say "render at the natural DPI".
    kwargs: dict[str, Any] = {
        "dpi": dpi,
        "output_folder": temp_dir,
        "paths_only": True,
        "fmt": _PDF_PAGE_FORMAT,
    }
    if max_side is not None:
        kwargs["size"] = max_side
    try:
        result = convert_from_bytes(content, **kwargs)
    except Exception:
        # rationale: rasterisation-boundary cleanup — any failure inside poppler
        # (corrupt PDF, OOM, missing binary) must not strand the temp directory.
        # The error itself is re-raised unchanged for the worker to handle.
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    # paths_only=True makes convert_from_bytes yield str paths (the published
    # type only models the in-memory list[Image]); they are sorted by zero-padded
    # page number, so lexical order is page order even past page 9.
    paths = cast("list[str]", result)
    return PageSource(paths=paths, temp_dir=temp_dir)
