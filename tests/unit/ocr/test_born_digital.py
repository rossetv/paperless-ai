import os
from unittest.mock import patch

import pytest
import structlog.testing
from ocr.born_digital import (
    ProbeError,
    _ProbeSignals,
    _has_glyphless,
    _parse_char_counts,
    _parse_max_coverage,
    _parse_pdfinfo,
    _run_probe,
    classify_original,
)

# A4 page area in square inches (595.32 x 841.92 pts / 72), the fixture PDFs' size.
_A4_AREA_SQ_IN = (595.32 / 72) * (841.92 / 72)


PDFINFO = "Title:  x\nPages:          2\nPage size:      595.32 x 841.92 pts (A4)\n"


def test_parse_pdfinfo_pages_and_area():
    pages, area = _parse_pdfinfo(PDFINFO)
    assert pages == 2
    assert area == pytest.approx(_A4_AREA_SQ_IN, rel=1e-3)


def test_parse_pdfinfo_missing_pages_raises():
    with pytest.raises(ProbeError):
        _parse_pdfinfo("Page size: 595 x 841 pts\n")


def test_parse_pdfinfo_garbled_page_size_raises_probe_error():
    # "1.2.3" matches the [\d.]+ regex but float() rejects it -> must not
    # escape as an uncaught ValueError; fail CLOSED via ProbeError.
    with pytest.raises(ProbeError):
        _parse_pdfinfo("Pages:          2\nPage size:      1.2.3 x 841.92 pts (A4)\n")


def test_char_counts_expect_n_plus_one_segments():
    # pdftotext appends a trailing \f -> 2 pages -> "aaa\fbbbbb\f" -> 3 segments
    assert _parse_char_counts("aaa\fbbbbb\f", 2) == [3, 5]


def test_char_counts_textless_last_page_is_zero():
    assert _parse_char_counts("aaa\f\f", 2) == [3, 0]  # page 2 textless, not dropped


def test_char_counts_too_few_segments_raises():
    with pytest.raises(ProbeError):
        _parse_char_counts("one page\f", 3)


def test_char_counts_embedded_formfeed_raises():
    # a \f inside extracted text yields > N+1 segments -> misalignment -> fail safe
    with pytest.raises(ProbeError):
        _parse_char_counts("a\fb\fc\f", 2)  # 4 segments, expected 3


PDFIMAGES = (
    "page   num  type   width height color comp bpc  enc interp  object ID x-ppi y-ppi size ratio\n"
    "--------------------------------------------------------------------------------\n"
    "   1     0 image    1654  2339  gray    1   8  image  no        10  0   200   200 1.2M 12%\n"
    "   1     1 image     300   300  rgb     3   8  image  no        11  0   200   200  12K  5%\n"
)


def test_parse_max_coverage_takes_largest_image_per_page():
    area = _A4_AREA_SQ_IN
    cov = _parse_max_coverage(PDFIMAGES, area)
    assert cov[1] == pytest.approx(1.0, abs=0.05)  # largest image ~ full page


# PDFIMAGES above saturates to 1.0 on its very first row, so it can't tell max
# from sum (both clip to 1.0). This fixture uses two page-1 images that each
# cover ~0.5 of the page: under the correct `max` formula, coverage stays
# ~0.5; under a `max -> sum` regression it would be ~1.0 (or clipped to 1.0),
# and the assertion below would fail.
PDFIMAGES_TWO_HALF_COVERAGE_IMAGES = (
    "page   num  type   width height color comp bpc  enc interp  object ID x-ppi y-ppi size ratio\n"
    "--------------------------------------------------------------------------------\n"
    "   1     0 image    1654  1170  gray    1   8  image  no        10  0   200   200 1.2M 12%\n"
    "   1     1 image    1654  1170  gray    1   8  image  no        11  0   200   200 1.2M 12%\n"
)


def test_parse_max_coverage_is_max_not_sum():
    area = _A4_AREA_SQ_IN
    cov = _parse_max_coverage(PDFIMAGES_TWO_HALF_COVERAGE_IMAGES, area)
    assert cov[1] == pytest.approx(0.5, abs=0.05)


def test_parse_max_coverage_no_images_is_empty():
    header = PDFIMAGES.split("\n", 2)[0] + "\n" + "-" * 40 + "\n"
    assert _parse_max_coverage(header, page_area=96.0) == {}


def test_parse_max_coverage_garbled_row_raises():
    bad = PDFIMAGES.rsplit("\n", 2)[0] + "\n   1  x  image  NOTANUMBER  2339 ...\n"
    with pytest.raises(ProbeError):
        _parse_max_coverage(bad, page_area=96.0)


def test_has_glyphless_plain_subset_and_case():
    assert _has_glyphless("name type\n---\nGlyphLessFont Type3 ...\n")
    assert _has_glyphless("name type\n---\nABCDEF+glyphlessfont Type3 ...\n")


def test_has_glyphless_real_font_false():
    assert not _has_glyphless(
        "name type\n---\nHelvetica Type1 ...\nABCDEF+Arial TrueType ...\n"
    )


# --- _run_probe hardening (real subprocesses via coreutils; POSIX) ---
def test_run_probe_nonzero_exit_raises():
    with pytest.raises(ProbeError):
        _run_probe(["false"], timeout=5)


def test_run_probe_missing_binary_raises_and_warns_once():
    # structlog is NOT routed through stdlib logging in this repo -> use capture_logs, assert == 1.
    from ocr.born_digital import _warned_missing

    _warned_missing.discard(
        "definitely-not-a-real-binary-xyz"
    )  # module-global persists across tests
    with structlog.testing.capture_logs() as logs:
        for _ in range(2):
            with pytest.raises(ProbeError):
                _run_probe(["definitely-not-a-real-binary-xyz"], timeout=1)
    warns = [e for e in logs if e.get("event") == "born_digital.poppler_missing"]
    assert len(warns) == 1


def test_run_probe_timeout_kills_a_spinner():
    # sleep emits no output; the deadline must fire in the read loop, not only at wait()
    with pytest.raises(ProbeError):
        _run_probe(["sleep", "10"], timeout=0.3)


def test_run_probe_output_cap_trips_on_a_flood():
    # timeout is large so ONLY PROBE_MAX_OUTPUT_BYTES can raise within the
    # test's runtime -- isolates the cap from the timeout path (with a small
    # timeout like 5s, deleting the cap check would still pass via timeout).
    # `yes` floods stdout, so the cap trips near-instantly regardless.
    with pytest.raises(ProbeError, match="exceeded"):
        _run_probe(["yes"], timeout=60)


def _decide(page_chars, page_cov, glyphless, min_chars=50):
    with patch(
        "ocr.born_digital._probe_signals",
        return_value=_ProbeSignals(page_chars, page_cov, glyphless),
    ):
        return classify_original(b"%PDF-1.4 fake", min_chars=min_chars)


def test_born_digital_text_skips():
    d = _decide([1443, 389], {1: 0.0, 2: 0.02}, False)
    assert d.skip is True and d.reason == "born-digital"


def test_image_heavy_born_digital_max_lock_skips():
    # Decision-level only: at this layer coverage is a pre-computed per-page dict
    # (via the _probe_signals mock), so this does NOT exercise _parse_max_coverage's
    # max-vs-sum behaviour -- see test_parse_max_coverage_is_max_not_sum for that.
    # This locks that a page whose largest image is 0.41 (< COVERAGE_THRESHOLD)
    # still skips, i.e. classify_original itself doesn't sum coverage across images.
    d = _decide([1443, 1443], {1: 0.0, 2: 0.41}, False)  # largest image 0.41 < COVERAGE
    assert d.skip is True


def test_pure_scan_ocrs():
    assert _decide([0, 0], {1: 1.0, 2: 1.0}, False).skip is False


def test_full_page_searchable_scan_ocrs_via_coverage():
    assert _decide([800], {1: 0.99}, False).skip is False


def test_inset_glyphless_scan_ocrs_via_glyphless():
    assert _decide([800, 800], {1: 0.4, 2: 0.4}, True).skip is False


def test_mixed_textless_last_page_ocrs():
    assert _decide([1443, 0], {1: 0.0, 2: 1.0}, False).skip is False


def test_min_chars_boundary():
    assert _decide([50], {1: 0.0}, False).skip is True
    assert _decide([49], {1: 0.0}, False).skip is False


def test_coverage_boundary():
    assert _decide([500], {1: 0.84}, False).skip is True
    assert _decide([500], {1: 0.86}, False).skip is False


def test_probe_failure_fails_safe_to_ocr():
    with patch("ocr.born_digital._probe_signals", side_effect=ProbeError("boom")):
        d = classify_original(b"%PDF junk", min_chars=50)
    assert d.skip is False and d.reason.startswith("probe-failed")


def test_per_probe_failure_including_pdffonts(monkeypatch):
    # each of the four probes failing in turn -> fail-safe OCR (D6 "including pdffonts")
    for failing in ("pdfinfo", "pdftotext", "pdfimages", "pdffonts"):

        def side_effect(cmd, timeout, _f=failing):
            if cmd[0] == _f:
                raise ProbeError(f"{_f} boom")
            return {
                "pdfinfo": "Pages: 1\nPage size: 595 x 841 pts\n",
                "pdftotext": "hello world enough text here to pass\f",
                "pdfimages": "h1\nh2\n",
            }[cmd[0]]

        monkeypatch.setattr("ocr.born_digital._run_probe", side_effect)
        d = classify_original(b"%PDF", min_chars=5)
        assert d.skip is False


def test_run_probe_read_oserror_raises_probe_error(monkeypatch):
    # An OSError from the read loop (os.read) must surface as ProbeError, not
    # escape raw (the module's fail-safe contract). Spy on Popen to learn the
    # probe's stdout fd, then raise only for reads on THAT fd -- so Popen's own
    # internal errpipe read during construction is untouched and the failure
    # lands in the read loop, not the "could not start" path.
    import ocr.born_digital as bd

    real_read = os.read
    real_popen = bd.subprocess.Popen
    captured: dict[str, int] = {}

    def spy_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        captured["fd"] = proc.stdout.fileno()
        return proc

    def fake_read(fd, n):
        if fd == captured.get("fd"):
            raise OSError("simulated read failure")
        return real_read(fd, n)

    monkeypatch.setattr(bd.subprocess, "Popen", spy_popen)
    monkeypatch.setattr(bd.os, "read", fake_read)
    # `yes` floods stdout so select() reports readable and the loop reaches read.
    with pytest.raises(ProbeError, match="read failed"):
        _run_probe(["yes"], timeout=30)


def test_classify_original_temp_write_oserror_fails_safe(monkeypatch):
    # A temp-file write failure (e.g. ENOSPC) must fail safe to OCR (skip=False),
    # not crash -- the write/probe block is guarded against OSError, narrowly.
    import ocr.born_digital as bd

    class _RaisingWriter:
        def __init__(self, fd):
            os.close(fd)  # release the real fd mkstemp opened; we never use it

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def write(self, _data):
            raise OSError("ENOSPC")

    monkeypatch.setattr(bd.os, "fdopen", lambda fd, *a, **k: _RaisingWriter(fd))
    d = classify_original(b"%PDF fake data", min_chars=50)
    assert d.skip is False
    assert d.reason.startswith("probe-failed")
