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


def _text_plus_blank_pdf() -> bytes:
    """A hand-built born-digital PDF: page 1 Helvetica text, page 2 blank.

    Base-14 Helvetica needs no embedding, so pdftotext yields real text and
    pdffonts lists a real font; page 2 has no content stream at all -- 0 chars,
    0 rasters -- the blank verso a duplex booklet carries.
    """
    text = b"BT /F1 12 Tf 72 770 Td (Your Motor Insurance Policy, born-digital text page) Tj ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>",
        b"<< /Length %d >>\nstream\n" % len(text) + text + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref,
    )
    return bytes(out)


def test_real_born_digital_with_blank_page_skips():
    # Regression: under the pre-2026-08-15 rule the blank page (0 chars) tripped
    # the text floor and sent the whole document to vision OCR.
    d = classify_original(_text_plus_blank_pdf(), min_chars=1)
    assert d.skip is True and d.reason == "born-digital", d
    assert d.signals["pages"] == 2 and d.signals["min_page_chars"] == 0


def test_real_pure_image_scan_ocrs():
    d = classify_original(_scan_pdf(2), min_chars=50)
    assert d.skip is False and d.reason in {"low-text-page", "full-page-image"}


def test_real_corrupt_pdf_fails_safe():
    d = classify_original(b"%PDF-1.4 not a real pdf", min_chars=50)
    assert d.skip is False and d.reason.startswith("probe-failed")
