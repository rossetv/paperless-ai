"""Turns document bytes (PDF, PNG, TIFF, ...) into a streamable page source.

Memory is the binding constraint: the daemon runs several documents at once,
each fanning pages across workers, on a memory-capped container. So PDFs are
rasterised straight at ``OCR_MAX_SIDE`` (a quarter of the bytes of a 300 DPI
A4 page) and streamed as temp files, one page loaded at a time; decoding a
50-page scan into one list is what OOM-kills the container.
"""

from __future__ import annotations

import os
import shutil
import struct
import tempfile
from io import BytesIO
from types import TracebackType
from typing import Any, cast

from PIL import Image, ImageSequence, UnidentifiedImageError
from pdf2image import convert_from_bytes
from pdf2image.exceptions import (
    PDFPageCountError,
    PDFPopplerTimeoutError,
    PDFSyntaxError,
    PopplerNotInstalledError,
)

# Lossless like the default PPM but far smaller on disk, which matters while a
# large scan's pages wait in the temp dir.
_PDF_PAGE_FORMAT = "png"

# Modes the provider can thumbnail and PNG-encode as-is.
_PAGE_SAFE_MODES = frozenset({"1", "L", "LA", "P", "RGB", "RGBA"})

# Target mode for the modes PNG cannot hold. Integer greyscale (I, I;16*) is
# rescaled separately in _to_page_mode: a plain convert("L") clips every value
# above 255 to white. F is a best-effort clip; no document scanner emits it.
_PAGE_MODE_TARGETS = {
    "CMYK": "RGB",
    "YCbCr": "RGB",
    "LAB": "RGB",
    "HSV": "RGB",
    "PA": "RGBA",
    "RGBa": "RGBA",
    "La": "LA",
    "F": "L",
}

_EXIF_ORIENTATION = 0x0112
# Orientation value -> the transpose that makes the pixels upright.
_ORIENTATION_TRANSPOSE = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}

# Rows converted at a time for 16-bit greyscale, which Pillow cannot resize:
# the 32-bit intermediate then stays a strip, not the whole page.
_STRIP_ROWS = 256

# Errors that mean Pillow cannot (or must not) decode the bytes. The bomb
# error is not an OSError; uncaught it escapes the worker, the pre-tag stays,
# and the document is re-downloaded and re-decoded every poll.
_UNDECODABLE = (UnidentifiedImageError, OSError, Image.DecompressionBombError)


class ImageConversionError(Exception):
    """Raised when raw document bytes cannot be decoded into images."""


class PageSource:
    """A sized, page-at-a-time view over a document's pages.

    Backed either by temp-file paths (PDF, multi-frame images), each decoded
    and deleted on load, or by already-decoded images. Use it as a context
    manager so the backing storage is released::

        with open_page_source(content, content_type, ...) as pages:
            for i in range(len(pages)):
                with pages.load_page(i) as image:
                    ...

    Every loaded page is fully in memory, 8-bit, and in a mode the provider can
    resize and PNG-encode. When the source was opened with ``max_side``, no page
    is longer than that on either side.
    """

    def __init__(
        self,
        *,
        paths: list[str] | None = None,
        temp_dir: str | None = None,
        images: list[Image.Image] | None = None,
    ) -> None:
        # Exactly one backing is populated.
        self._paths = paths or []
        self._temp_dir = temp_dir
        self._images = images or []

    def __len__(self) -> int:
        """Return the number of pages, known before any page is loaded."""
        return len(self._images) if self._images else len(self._paths)

    def load_page(self, index: int) -> Image.Image:
        """Load page *index* (0-based) as an image the caller owns and closes.

        A page file is deleted once decoded, so the temp directory drains as
        the document is processed.
        """
        if self._images:
            # A copy, because the caller closes what it loads and the stored
            # image must stay valid.
            return self._images[index].copy()

        path = self._paths[index]
        try:
            with Image.open(path) as handle:
                # copy() detaches the decoded pixels from the file, which is
                # deleted below.
                handle.load()
                image = handle.copy()
        finally:
            # Delete eagerly so disk usage tracks only the unprocessed pages.
            try:
                os.remove(path)
            except OSError:
                pass
        return image

    def close(self) -> None:
        """Release the temp directory or the held images; idempotent, never raises."""
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
    timeout: int | None = None,
) -> PageSource:
    """Decode raw document bytes into a streamable :class:`PageSource`.

    PDFs are rasterised one temp file per page and multi-frame images are
    split into frames; other images are decoded in memory.

    Args:
        dpi: PDF rendering resolution; still passed to poppler when *max_side*
            sets the output size.
        max_side: Scale each page so its longer side is at most this many pixels
            (PDFs via ``pdftoppm -scale-to``, an int because
            ``size=(max_side, None)`` would only fix the width; images are only
            ever shrunk). ``None`` leaves images at their size.
        timeout: Seconds before ``pdftoppm`` is killed; ``None`` means no limit.

    Raises:
        ImageConversionError: The bytes cannot be decoded or rasterised, or an
            image is larger than Pillow's pixel cap.
    """
    if "pdf" in content_type.lower():
        return _pdf_to_page_source(content, dpi=dpi, max_side=max_side, timeout=timeout)

    try:
        img = Image.open(BytesIO(content))
        _check_pixel_cap(img)
        if getattr(img, "n_frames", 1) > 1:
            # Stream frames like PDF pages: decoding all of a 100-page 300-DPI
            # TIFF at once is ~2.6 GB.
            img.close()
            return _multiframe_to_page_source(content, max_side)
        if max_side is not None:
            # JPEG decodes at a reduced size; a no-op for other formats.
            img.draft(None, (max_side, max_side))
        upright = _apply_exif_orientation(img)
        page = _normalise(upright, max_side)
        page.load()
        for source in (upright, img):
            if page is not source:
                source.close()
        return PageSource(images=[page])
    except _UNDECODABLE as e:
        raise ImageConversionError(f"Unable to open image: {e}") from e


def _check_pixel_cap(image: Image.Image) -> None:
    """Refuse an image above Pillow's pixel cap, judged from its header alone.

    Pillow itself only refuses above twice the cap and warns below that, which
    still leaves room for a decode too large for the container.
    """
    limit = Image.MAX_IMAGE_PIXELS
    width, height = image.size
    if limit is not None and width * height > limit:
        raise ImageConversionError(
            f"Unable to open image: {width}x{height} pixels is too large (limit {limit})"
        )


def _apply_exif_orientation(image: Image.Image) -> Image.Image:
    """Return *image* itself, or a rotated/flipped copy when EXIF says it is not upright."""
    try:
        orientation = image.getexif().get(_EXIF_ORIENTATION, 1)
    except (SyntaxError, ValueError, struct.error):
        # A junk EXIF block means "upright", not an undecodable image.
        return image
    method = _ORIENTATION_TRANSPOSE.get(orientation)
    # Not ImageOps.exif_transpose: it re-writes the EXIF block, which a damaged tag breaks.
    return image.transpose(method) if method is not None else image


def _to_page_mode(image: Image.Image) -> Image.Image:
    """Return *image* itself when it is page-safe, else a converted new image.

    16- and 32-bit greyscale is rescaled to 8 bits (65535 → 255) rather than
    clipped; colour spaces PNG cannot hold become RGB/RGBA/LA. The caller closes
    the result only when it is not *image*.
    """
    mode = image.mode
    if mode in _PAGE_SAFE_MODES:
        return image
    if mode == "I" or mode.startswith("I;16"):
        # point() only accepts I and native I;16 — widen I;16B/L/N first.
        return _sixteen_bit_to_l(image)
    return image.convert(_PAGE_MODE_TARGETS.get(mode, "RGB"))


def _sixteen_bit_to_l(image: Image.Image) -> Image.Image:
    """Rescale integer greyscale to 8 bits a strip of rows at a time."""
    result = Image.new("L", image.size)
    for top in range(0, image.height, _STRIP_ROWS):
        box = (0, top, image.width, min(top + _STRIP_ROWS, image.height))
        with image.crop(box) as strip:
            wide = strip.convert("I")
            with wide, wide.point(lambda v: v / 257) as scaled:
                with scaled.convert("L") as narrow:
                    result.paste(narrow, (0, top))
    return result


def _fit_to_side(image: Image.Image, max_side: int | None) -> Image.Image:
    """Return *image* itself, or a shrunk new image if a side exceeds *max_side*."""
    if max_side is None or max(image.size) <= max_side:
        return image
    scale = max_side / max(image.size)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    source = image
    # Nearest sampling would drop the thin strokes of a bilevel or palette scan.
    if image.mode == "1":
        source = image.convert("L")
    elif image.mode == "P":
        source = image.convert("RGBA" if "transparency" in image.info else "RGB")
    try:
        # reducing_gap does most of the shrink with a cheap integer reduce, as
        # Image.thumbnail does.
        return source.resize(size, reducing_gap=2.0)
    finally:
        if source is not image:
            source.close()


def _normalise(image: Image.Image, max_side: int | None) -> Image.Image:
    """Convert *image* to a page-safe mode and fit it to *max_side*.

    May return *image* itself; any intermediate bitmap is closed.
    """
    if image.mode in ("I", "F"):
        # These resize fine, so shrink before the 8-bit conversion, not after.
        shrunk = _fit_to_side(image, max_side)
        page = _to_page_mode(shrunk)
        if shrunk is not image and shrunk is not page:
            shrunk.close()
        return page
    page = _to_page_mode(image)
    fitted = _fit_to_side(page, max_side)
    if page is not image and fitted is not page:
        page.close()
    return fitted


def _multiframe_to_page_source(content: bytes, max_side: int | None) -> PageSource:
    """Write each frame of a multi-frame image to a temp PNG for on-demand loading.

    The returned :class:`PageSource` owns the temp directory; on failure it is
    removed before the error propagates.
    """
    temp_dir = tempfile.mkdtemp(prefix="paperless-ocr-tiff-")
    paths: list[str] = []
    try:
        with Image.open(BytesIO(content)) as img:
            for frame_index, frame in enumerate(ImageSequence.Iterator(img)):
                _check_pixel_cap(frame)
                page = _normalise(frame, max_side)
                path = os.path.join(temp_dir, f"frame-{frame_index:04d}.png")
                page.save(path, format="PNG")
                if page is not frame:
                    page.close()
                paths.append(path)
    except _UNDECODABLE as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise ImageConversionError(f"Unable to open image: {exc}") from exc
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return PageSource(paths=paths, temp_dir=temp_dir)


def _pdf_to_page_source(
    content: bytes, *, dpi: int, max_side: int | None, timeout: int | None
) -> PageSource:
    """Rasterise a PDF to per-page temp files and wrap them in a PageSource.

    The returned :class:`PageSource` owns the temp directory; on failure it is
    removed before the error propagates.

    Raises:
        ImageConversionError: Any pdf2image / Poppler failure.
    """
    temp_dir = tempfile.mkdtemp(prefix="paperless-ocr-")
    # ``size`` is omitted rather than passed as None, which the published type
    # rejects. pdf2image publishes no TypedDict for these mixed kwargs.
    kwargs: dict[str, Any] = {
        "dpi": dpi,
        "output_folder": temp_dir,
        "paths_only": True,
        "fmt": _PDF_PAGE_FORMAT,
    }
    if max_side is not None:
        kwargs["size"] = max_side
    if timeout is not None:
        kwargs["timeout"] = timeout
    try:
        raw_paths = convert_from_bytes(content, **kwargs)
    except (
        PDFSyntaxError,
        PDFPageCountError,
        PDFPopplerTimeoutError,
        PopplerNotInstalledError,
    ) as exc:
        # Wrapped so the worker error-tags the document and it leaves the queue.
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise ImageConversionError(f"PDF rasterisation failed: {exc}") from exc
    except Exception:
        # Any other failure must not strand the temp directory.
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    # paths_only=True yields str paths, which the published type does not model.
    # They are named by zero-padded page number, so lexical order is page order.
    paths = cast("list[str]", raw_paths)
    return PageSource(paths=paths, temp_dir=temp_dir)
