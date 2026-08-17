"""Born-digital vs scan detection on a document's *original* PDF (spec D1–D6).

Pure bytes -> BornDigitalDecision. Shells poppler-utils (pdftotext/pdfinfo/
pdfimages/pdffonts), the same trust boundary pdf2image already uses. Every probe
failure and every malformed parse raises ProbeError; classify_original turns any
ProbeError -- or an OSError from the temp-file write -- into a fail-safe "OCR"
decision (spec D6). Parsers fail CLOSED — a garbled layout must never read as
"no signal".
"""

from __future__ import annotations

import os
import re
import select
import subprocess
import tempfile
import time
from dataclasses import dataclass

import structlog

log = structlog.get_logger(__name__)

COVERAGE_THRESHOLD: float = 0.85
PROBE_TIMEOUT: int = 30
PROBE_MAX_OUTPUT_BYTES: int = 32 * 1024 * 1024
_GLYPHLESS_NAME: str = "glyphlessfont"
_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")
# A semicolon glued between two letters never occurs in prose; it is the
# fingerprint of a text layer whose ToUnicode maps the "ti" ligature glyph to
# ";" ("mee;ng", "informa;on") -- macOS Quartz PDFContext does this on
# Calibri/Aptos, alongside "tt" -> "5", "ft" -> "C", "ffi" -> "m". Only the
# "ti" mapping is detected, and only intra-word: a document mangled solely
# in the other ligatures, or with word-initial "ti" only, passes. Semicolon-
# delimited data, minified CSS/JS and ";"-joined URLs trip it (over-OCR, the
# safe direction). Such a text layer is not worth keeping.
_MANGLED_LIGATURE_RE = re.compile(r"[A-Za-z];[A-Za-z]")
_warned_missing: set[str] = set()  # binaries warned about, once per process


class ProbeError(Exception):
    """A poppler probe failed (non-zero exit, timeout, oversized output, missing binary, unparseable)."""


def _run_probe(cmd: list[str], timeout: float) -> str:
    """Run a poppler command with a real deadline and a hard stdout cap.

    The deadline is enforced across the whole read via select() — a binary that
    spins WITHOUT emitting output (a malformed xref loop) would hang a plain
    read(); the timeout must not live only on wait(). stderr -> DEVNULL so it
    cannot fill a pipe and deadlock. POSIX (Linux container + macOS dev).
    """
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        if cmd[0] not in _warned_missing:
            _warned_missing.add(cmd[0])
            log.warning("born_digital.poppler_missing", binary=cmd[0])
        raise ProbeError(f"{cmd[0]} not found") from exc
    except (OSError, ValueError) as exc:
        raise ProbeError(f"could not start {cmd[0]}: {exc}") from exc
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    deadline = time.monotonic() + timeout
    chunks: list[bytes] = []
    total = 0
    try:
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProbeError(f"{cmd[0]} timed out")
                ready, _, _ = select.select([fd], [], [], remaining)
                if not ready:
                    raise ProbeError(f"{cmd[0]} timed out")
                chunk = os.read(
                    fd, 65536
                )  # select said readable -> returns >=1 byte or b'' at EOF
                if not chunk:
                    break
                total += len(chunk)
                if total > PROBE_MAX_OUTPUT_BYTES:
                    raise ProbeError(
                        f"{cmd[0]} output exceeded {PROBE_MAX_OUTPUT_BYTES} bytes"
                    )
                chunks.append(chunk)
        except OSError as exc:
            # select()/read() can fail (EBADF, EINTR-storm, device error); the
            # module contract is any probe failure -> fail-safe OCR, so a raw
            # OSError must not escape.
            raise ProbeError(f"{cmd[0]} read failed: {exc}") from exc
        try:
            rc = proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise ProbeError(f"{cmd[0]} timed out") from exc
        if rc != 0:
            raise ProbeError(f"{cmd[0]} exited {rc}")
        return b"".join(chunks).decode("utf-8", "replace")
    finally:
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # A D-state child can outlive the kill; don't let the reap mask
                # the real error being propagated out of the try block.
                pass


def _parse_pdfinfo(text: str) -> tuple[int, float | None]:
    m = re.search(r"^Pages:\s+(\d+)", text, re.MULTILINE)
    if not m:
        raise ProbeError("pdfinfo: no Pages field")
    pages = int(m.group(1))
    area: float | None = None
    ms = re.search(r"^Page size:\s+([\d.]+)\s+x\s+([\d.]+)\s+pts", text, re.MULTILINE)
    if ms:
        try:
            area = (float(ms.group(1)) / 72.0) * (float(ms.group(2)) / 72.0)
        except ValueError as exc:
            raise ProbeError(
                f"pdfinfo: unparseable page size: {ms.group(0)!r}"
            ) from exc  # fail CLOSED, same contract as _parse_max_coverage
    return pages, area


def _parse_char_counts(pdftotext_out: str, page_count: int) -> list[int]:
    segments = pdftotext_out.split("\f")
    # pdftotext appends a trailing \f after the last page -> exactly page_count + 1 segments.
    # Anything else (embedded \f in text, truncation) is misalignment -> fail safe (D3).
    if len(segments) != page_count + 1:
        raise ProbeError(
            f"pdftotext: {len(segments)} segments, expected {page_count + 1}"
        )
    return [len(re.sub(r"\s", "", seg)) for seg in segments[:page_count]]


def _count_mangled_ligatures(pdftotext_out: str) -> int:
    # finditer, not findall: the input can be the full PROBE_MAX_OUTPUT_BYTES
    # and a semicolon flood materialised as a list is ~15x its size in RSS.
    return sum(1 for _ in _MANGLED_LIGATURE_RE.finditer(pdftotext_out))


def _parse_max_coverage(
    pdfimages_list_out: str, page_area: float | None
) -> dict[int, float]:
    if not page_area:
        raise ProbeError("pdfimages: no page area to normalise against")
    lines = pdfimages_list_out.splitlines()
    per_page: dict[int, float] = {}
    for line in lines[2:]:  # skip the 2 header lines
        if not line.strip():
            continue
        f = line.split()
        # Columns from the LEFT are stable up to height; the "object ID" column
        # is two tokens ("10  0") for an XObject but ONE for an inline image
        # ("[inline]") or a non-Ref image object ("[none]"), so the ppi columns
        # are addressed from the RIGHT: ... x-ppi y-ppi size ratio.
        try:
            page, w, h = int(f[0]), int(f[3]), int(f[4])
            xppi, yppi = float(f[-4]), float(f[-3])
        except (IndexError, ValueError) as exc:
            raise ProbeError(
                f"pdfimages: unparseable row: {line!r}"
            ) from exc  # fail CLOSED
        # A degenerate-CTM raster (ppi 0) has no measurable coverage but the
        # page still carries an image -- keep it in the map at 0.0 so
        # classify_original's blank-page exemption cannot mistake it for blank.
        cov = 0.0
        if xppi > 0 and yppi > 0:
            cov = min(1.0, (w / xppi) * (h / yppi) / page_area)
        per_page[page] = max(
            per_page.get(page, 0.0), cov
        )  # LARGEST image per page (spec D3)
    return per_page


def _has_glyphless(pdffonts_out: str) -> bool:
    for line in pdffonts_out.splitlines()[2:]:  # skip the 2 header lines
        f = line.split()
        if not f:
            continue
        if _SUBSET_PREFIX_RE.sub("", f[0]).lower() == _GLYPHLESS_NAME:
            return True
    return False


@dataclass(frozen=True)
class BornDigitalDecision:
    """The gate's verdict for one document, plus the signals that produced it (for logging)."""

    skip: bool
    reason: str
    signals: dict[str, object]


@dataclass(frozen=True)
class _ProbeSignals:
    """The four poppler probes' parsed outputs for one document (spec D3)."""

    char_counts: list[int]
    coverage: dict[int, float]
    glyphless: bool
    mangled_hits: int


def _probe_signals(path: str, timeout: float) -> _ProbeSignals:
    """Run the four poppler probes into a :class:`_ProbeSignals`.

    Any probe/parse failure propagates as ProbeError.
    """
    pages, area = _parse_pdfinfo(_run_probe(["pdfinfo", path], timeout))
    if pages <= 0:
        raise ProbeError("pdfinfo: non-positive page count")
    text = _run_probe(["pdftotext", "-q", path, "-"], timeout)
    char_counts = _parse_char_counts(text, pages)
    mangled_hits = _count_mangled_ligatures(text)
    coverage = _parse_max_coverage(
        _run_probe(["pdfimages", "-list", path], timeout), area
    )
    glyphless = _has_glyphless(_run_probe(["pdffonts", path], timeout))
    return _ProbeSignals(char_counts, coverage, glyphless, mangled_hits)


def classify_original(
    data: bytes,
    *,
    min_chars: int,
    coverage_threshold: float = COVERAGE_THRESHOLD,
    timeout: float = PROBE_TIMEOUT,
) -> BornDigitalDecision:
    """Decide skip (born-digital) vs OCR from a document's ORIGINAL PDF bytes (spec D3, D6)."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)  # can raise OSError (e.g. ENOSPC)
            probe = _probe_signals(path, timeout)
        except (OSError, ProbeError) as exc:
            return BornDigitalDecision(False, f"probe-failed:{exc}", {})
        char_counts = probe.char_counts
        coverage = probe.coverage
        glyphless = probe.glyphless
        min_page_chars = min(char_counts)  # _probe_signals guarantees >=1 page
        max_cov = max(coverage.values()) if coverage else 0.0
        signals: dict[str, object] = {
            "pages": len(char_counts),
            "min_page_chars": min_page_chars,
            "max_coverage": round(max_cov, 3),
            "glyphless": glyphless,
            "mangled_hits": probe.mangled_hits,
        }
        if glyphless:
            return BornDigitalDecision(False, "glyphless-ocr-layer", signals)
        # Presence is not enough when the text layer itself is garbage: a
        # broken ligature ToUnicode passes every presence signal yet leaves
        # ngx with "mee;ng" for "meeting". One hit routes to OCR -- over-OCR
        # on doubt is the safe direction (spec D6).
        if probe.mangled_hits:
            return BornDigitalDecision(False, "mangled-text-layer", signals)
        # The text floor only bites on a page that also carries a raster: a
        # textless, imageless page is a blank verso, a divider or (rarely) a
        # vector-outline page -- not a scan (spec D3, blank-page clause; the
        # outline case is an accepted residual, spec risk 4b). The offending
        # page is named because min_page_chars may belong to an exempted page.
        low_text_page = next(
            (
                page
                for page, chars in enumerate(char_counts, 1)
                if chars < min_chars and page in coverage
            ),
            None,
        )
        if low_text_page is not None:
            return BornDigitalDecision(
                False, "low-text-page", {**signals, "low_text_page": low_text_page}
            )
        if any(c >= coverage_threshold for c in coverage.values()):
            return BornDigitalDecision(False, "full-page-image", signals)
        return BornDigitalDecision(True, "born-digital", signals)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
