import io
import shutil
import pytest
from PIL import Image, ImageDraw
from ocr.born_digital import classify_original

_POPPLER = all(
    shutil.which(b) for b in ("pdftotext", "pdfimages", "pdfinfo", "pdffonts")
)
pytestmark = pytest.mark.skipif(not _POPPLER, reason="poppler-utils not installed")


def _scan_pdf(pages: int = 1) -> bytes:
    imgs = []
    for _ in range(pages):
        im = Image.new("RGB", (1654, 2339), "white")
        ImageDraw.Draw(im).rectangle([40, 40, 1610, 2300], fill=(225, 225, 225))
        imgs.append(im)
    buf = io.BytesIO()
    imgs[0].save(buf, "PDF", save_all=True, append_images=imgs[1:], resolution=200.0)
    return buf.getvalue()


def test_real_pure_image_scan_ocrs():
    d = classify_original(_scan_pdf(2), min_chars=50)
    assert d.skip is False and d.reason in {"low-text-page", "full-page-image"}


def test_real_corrupt_pdf_fails_safe():
    d = classify_original(b"%PDF-1.4 not a real pdf", min_chars=50)
    assert d.skip is False and d.reason.startswith("probe-failed")
