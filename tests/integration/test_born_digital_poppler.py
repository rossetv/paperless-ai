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


_TEXT = b"BT /F1 12 Tf 72 770 Td (Your Motor Insurance Policy, born-digital text page) Tj ET"
# A 4x4 8-bit grey inline image (BI...EI) drawn at 40x40 pt -- a small logo.
_INLINE_LOGO = (
    b"q 40 0 0 40 72 700 cm BI /W 4 /H 4 /CS /G /BPC 8 ID "
    + bytes([0x00, 0xFF] * 8)
    + b" EI Q"
)


# A ToUnicode CMap that maps code 0x59 ("Y") to U+003B (";") -- the shape of
# the macOS Quartz PDFContext bug on Calibri/Aptos, where the "ti" ligature
# glyph's code is mapped to a semicolon. pdftotext honours ToUnicode over the
# base encoding, so "meeYng" in the content stream extracts as "mee;ng".
_BROKEN_TOUNICODE = (
    b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
    b"/CMapName /Adobe-Identity-UCS def /CMapType 2 def\n"
    b"1 begincodespacerange <00> <FF> endcodespacerange\n"
    b"1 beginbfrange <59> <59> <003B> endbfrange\n"
    b"endcmap CMapName currentdict /CMap defineresource pop end end"
)


def _build_pdf(pages: list[bytes | None], *, tounicode: bytes | None = None) -> bytes:
    """Hand-build a born-digital PDF, one content stream per page (None = no
    /Contents at all: a truly blank page). Base-14 Helvetica needs no
    embedding, so pdftotext yields real text and pdffonts lists a real font.
    ``tounicode`` attaches a CMap stream to the font (object 4), so a
    deliberately wrong map can be exercised end to end through poppler.
    """
    font_obj = 3
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica"
    objs: list[bytes] = [
        b"",  # 1: catalogue (filled below)
        b"",  # 2: pages (filled below)
        font + (b" /ToUnicode 4 0 R >>" if tounicode is not None else b" >>"),
    ]
    if tounicode is not None:
        objs.append(
            b"<< /Length %d >>\nstream\n" % len(tounicode) + tounicode + b"\nendstream"
        )
    kids: list[bytes] = []
    for content in pages:
        page_num = len(objs) + 1
        kids.append(b"%d 0 R" % page_num)
        page = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 %d 0 R >> >>" % font_obj
        )
        if content is None:
            objs.append(page + b" >>")
        else:
            objs.append(page + b" /Contents %d 0 R >>" % (page_num + 1))
            objs.append(
                b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"
            )
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = (
        b"<< /Type /Pages /Kids [" + b" ".join(kids) + b"] /Count %d >>" % len(pages)
    )
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
    d = classify_original(_build_pdf([_TEXT, None]), min_chars=1)
    assert d.skip is True and d.reason == "born-digital", d
    assert d.signals["pages"] == 2 and d.signals["min_page_chars"] == 0


def test_real_born_digital_with_inline_logo_skips():
    # Regression: pdfimages prints an inline image as `[inline]` (and a non-Ref
    # image object as `[none]`) -- one token where an XObject has two -- which
    # the fixed-index ppi parse read as the size column -> ProbeError -> every
    # such PDF fell to vision OCR. A text page with a small inline logo is
    # born-digital and must skip.
    d = classify_original(_build_pdf([_TEXT + b" " + _INLINE_LOGO]), min_chars=1)
    assert d.skip is True and d.reason == "born-digital", d
    assert 0.0 < d.signals["max_coverage"] < 0.05


def test_real_inline_image_only_page_still_ocrs():
    # ...while an inline raster with no text is scan-like and still OCRs.
    d = classify_original(_build_pdf([_TEXT, _INLINE_LOGO]), min_chars=1)
    assert d.skip is False and d.reason == "low-text-page", d
    assert d.signals["low_text_page"] == 2


def test_real_mangled_ligature_text_layer_ocrs():
    # Regression (prod, 2026-08-07): an Outlook-for-Mac print-to-PDF carried
    # a Quartz-written ToUnicode that mapped the Calibri "ti" ligature to ";"
    # -- pdftotext read "mee;ng" for "meeting", every presence signal said
    # born-digital, and the garbage text layer was kept. Through real poppler:
    # a broken CMap must send the document to vision OCR.
    text = b"BT /F1 12 Tf 72 770 Td (Minutes of the meeYng held on Monday) Tj ET"
    d = classify_original(_build_pdf([text], tounicode=_BROKEN_TOUNICODE), min_chars=1)
    assert d.skip is False and d.reason == "mangled-text-layer", d
    assert d.signals["mangled_hits"] == 1
    # The same page with an honest map is still born-digital.
    d = classify_original(_build_pdf([text]), min_chars=1)
    assert d.skip is True and d.reason == "born-digital", d


def test_real_pure_image_scan_ocrs():
    d = classify_original(_scan_pdf(2), min_chars=50)
    assert d.skip is False and d.reason in {"low-text-page", "full-page-image"}


def test_real_corrupt_pdf_fails_safe():
    d = classify_original(b"%PDF-1.4 not a real pdf", min_chars=50)
    assert d.skip is False and d.reason.startswith("probe-failed")
