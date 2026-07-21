# Born-digital OCR-skip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skip AI vision-OCR for born-digital PDFs (detected on the pristine *original* file with poppler), while AI-OCRing scans, images, and searchable scans — cutting vision spend with zero quality risk.

**Architecture:** A new isolated detection module (`src/ocr/born_digital.py`) turns raw PDF bytes into a skip/OCR decision using four poppler probes (`pdftotext`, `pdfinfo`, `pdfimages`, `pdffonts`). The OCR worker calls it early in `process()` (after the processing-tag claim, before rasterisation); on a born-digital verdict it does a tags-only `PRE→POST` PATCH and returns the breaker-neutral outcome, skipping the vision call entirely. Every doubt falls through to today's OCR path.

**Tech Stack:** Python 3, poppler-utils (already in the image via `pdf2image`), httpx (via the existing `PaperlessClient`), pytest + respx. React/TS/Vite for the settings UI.

**Spec:** `.claude/specs/20260721-born-digital-ocr-skip.md` (approved 2026-07-21). Read it before implementing — Decisions D1–D11 are law.

## Global Constraints

- **Detection reads the ORIGINAL** (`?original=true`), never the archive (D2). The OCR path keeps downloading the archive.
- **Rule (whole-document, D3):** SKIP ⟺ no `GlyphLessFont` **and** every page has `chars ≥ MIN_CHARS` **and** per-page **largest-image** coverage `< COVERAGE`; else OCR.
- **Coverage = single largest image ÷ page area, per page** (NOT clipped sum — D3; sum flips Doc A). `COVERAGE_THRESHOLD = 0.85` hardcoded.
- **`MIN_CHARS` config default 50**, validated `≥ 1`. **Glyphless detection = font-name match** on `GlyphLessFont` after stripping an optional `XXXXXX+` subset prefix, case-insensitive.
- **Text yield:** page count `N` from `pdfinfo`; split `pdftotext` output on `\f`; **exactly `N + 1` segments expected** (pdftotext appends a trailing `\f` after the last page); evaluate the first `N`; any other count → fail-safe OCR (D3 — never drop trailing empties).
- **Fail-CLOSED parsing:** every parser raises `ProbeError` on malformed/unexpected input (a silent "skip the bad row" would invert fail-safe into fail-open — a garbled `pdfimages` layout must NOT read as "no images"). `ProbeError` → OCR.
- **Fail-safe = every doubt → OCR** (D6): non-PDF, any probe failure/timeout/oversized-output/missing-binary, encrypted/corrupt PDF, empty ngx content.
- **Probe hardening:** `PROBE_TIMEOUT = 30`s enforced across the whole read (a `select` deadline, not just `wait()` — a poppler binary can spin without emitting output); `PROBE_MAX_OUTPUT_BYTES = 32*1024*1024` hard stdout cap (`capture_output=True` is unbounded); a missing binary warns **once per process**.
- **Skip write:** re-fetch tags via `get_latest_tags` (never the pre-claim snapshot), `clean_pipeline_tags`, add `POST_TAG_ID` + `OCR_BORN_DIGITAL_TAG_ID` if set; tags-only PATCH via `update_document_metadata(doc_id, tags=<set[int]>)` (never rewrite content); a successful skip returns `None` (breaker-neutral, and `process()` logs it as success); a permanent 4xx quarantines (`WriteBackOutcome.QUARANTINED`); a transient error re-raises.
- **No new dependencies.** No secrets/PII in fixtures or logs. British English in prose/comments; identifiers follow `OCR_*`/snake_case.
- Every task is TDD. Imports at file top (ruff E402/F811); shown code must pass `ruff format --check` and `mypy` (lenient config, no strict flags).

---

## File structure

| File | Responsibility | New? |
|---|---|---|
| `src/ocr/born_digital.py` | Pure `bytes → BornDigitalDecision`: poppler probe wrappers, fail-closed parsers, the decision rule, fail-safe. Imports `common` only. | Create |
| `src/common/paperless.py` | Add `download_original()` (`?original=true`). | Modify |
| `src/common/config/_catalogue.py` | 3 keys into `CONFIG_KEYS`. | Modify |
| `src/common/config/_settings.py` | 3 `Settings` fields + parsing. | Modify |
| `src/ocr/worker.py` | The gate branch in `OcrProcessor.process()` + `_try_skip_born_digital`. | Modify |
| `tests/helpers/factories/_core.py` | Add the 3 new fields to `make_settings_obj` defaults (gate **off** for mock-settings tests). | Modify |
| `web/src/features/settings/fieldModel/sections.ts` | New OCR `born-digital` group (2 visible fields) + marker tag in the `automation`→`tags` group. | Modify |
| `.claude/DECISIONS.md` | Decision entry citing the spec. | Modify |
| `tests/unit/ocr/test_born_digital.py` | Parser + probe + decision unit tests. | Create |
| `tests/integration/test_born_digital_poppler.py` | Real-poppler e2e (Pillow-generated PDFs), poppler-guarded. | Create |
| `tests/unit/ocr/conftest.py` | Hoist `_http_status_error` here (shared by both worker test files). | Modify |
| `tests/unit/ocr/test_worker_internals.py` | Gate-method (`_try_skip_born_digital`) unit tests. | Modify |
| `tests/unit/ocr/test_worker.py` | One `process()` integration test (skip end-to-end). | Modify |
| `tests/unit/common/test_paperless.py` | `download_original` test. | Modify |
| `tests/unit/common/test_config.py` | Rename+update the pinned key-count test (87→90) + key presence. | Modify |
| `tests/e2e/test_ocr_workflow.py` | e2e born-digital skip against the stateful mock. | Modify |
| `web/src/features/settings/fieldModel/sections.test.ts` | Pin the 3 new fields. | Create (if absent) |

## Tracks & parallelism

Four tasks are file-disjoint with no shared interface and run **in parallel** as direct background Agent dispatches (flat orchestration). Task 6 consumes Tasks 1–4 and is sequential; Task 7 follows Task 6.

| Track | Tasks | Model | Depends on |
|---|---|---|---|
| A — detection module | 1, 2 | **Opus** (untrusted-input parsing, subprocess deadline, fail-closed) | — |
| B — config keys | 3 | **Sonnet** | — |
| C — paperless client | 4 | **Sonnet** | — |
| D — settings UI | 5 | **Sonnet** | — |
| E — worker integration | 6 | **Opus** (pipeline/write-back, breaker interaction) | A, B, C |
| F — integration + KB | 7 | **Sonnet** | E (and D) |

Tasks 1→2 sequential within Track A (2 consumes 1). Task 6 also edits `tests/helpers/factories/_core.py` (Track B does **not** touch it — no conflict). The four review-team lenses in step 6 are Opus regardless (LCW).

---

### Task 1: Detection module — probe wrappers and fail-closed parsers

**Files:**
- Create: `src/ocr/born_digital.py`
- Test: `tests/unit/ocr/test_born_digital.py`

**Interfaces produced (used by Task 2 and Task 6):**
- `class ProbeError(Exception)`.
- Constants: `COVERAGE_THRESHOLD: float = 0.85`, `PROBE_TIMEOUT: int = 30`, `PROBE_MAX_OUTPUT_BYTES: int = 32 * 1024 * 1024`.
- `_run_probe(cmd: list[str], timeout: float) -> str` — deadline-enforced, output-capped subprocess; raises `ProbeError`; warns once per missing binary.
- Fail-closed parsers: `_parse_pdfinfo(text) -> tuple[int, float | None]`, `_parse_char_counts(out, page_count) -> list[int]`, `_parse_max_coverage(out, page_area) -> dict[int, float]`, `_has_glyphless(out) -> bool`.

- [ ] **Step 1: Write failing parser + probe tests** (`tests/unit/ocr/test_born_digital.py`)

```python
import pytest
import structlog.testing
from ocr.born_digital import (
    ProbeError, _run_probe, _parse_pdfinfo, _parse_char_counts,
    _parse_max_coverage, _has_glyphless,
    COVERAGE_THRESHOLD, PROBE_TIMEOUT, PROBE_MAX_OUTPUT_BYTES,
)

def test_constants_pin():  # also uses the imported constants (no F401)
    assert (COVERAGE_THRESHOLD, PROBE_TIMEOUT, PROBE_MAX_OUTPUT_BYTES) == (0.85, 30, 32 * 1024 * 1024)

PDFINFO = "Title:  x\nPages:          2\nPage size:      595.32 x 841.92 pts (A4)\n"

def test_parse_pdfinfo_pages_and_area():
    pages, area = _parse_pdfinfo(PDFINFO)
    assert pages == 2
    assert area == pytest.approx((595.32 / 72) * (841.92 / 72), rel=1e-3)

def test_parse_pdfinfo_missing_pages_raises():
    with pytest.raises(ProbeError):
        _parse_pdfinfo("Page size: 595 x 841 pts\n")

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
    area = (595.32 / 72) * (841.92 / 72)
    cov = _parse_max_coverage(PDFIMAGES, area)
    assert cov[1] == pytest.approx(1.0, abs=0.05)  # largest image ~ full page

def test_parse_max_coverage_no_images_is_empty():
    header = PDFIMAGES.split("\n", 2)[0] + "\n" + "-" * 40 + "\n"
    assert _parse_max_coverage(header, page_area=96.0) == {}

def test_parse_max_coverage_garbled_row_raises():
    bad = (PDFIMAGES.rsplit("\n", 2)[0] + "\n   1  x  image  NOTANUMBER  2339 ...\n")
    with pytest.raises(ProbeError):
        _parse_max_coverage(bad, page_area=96.0)

def test_has_glyphless_plain_subset_and_case():
    assert _has_glyphless("name type\n---\nGlyphLessFont Type3 ...\n")
    assert _has_glyphless("name type\n---\nABCDEF+glyphlessfont Type3 ...\n")

def test_has_glyphless_real_font_false():
    assert not _has_glyphless("name type\n---\nHelvetica Type1 ...\nABCDEF+Arial TrueType ...\n")

# --- _run_probe hardening (real subprocesses via coreutils; POSIX) ---
def test_run_probe_nonzero_exit_raises():
    with pytest.raises(ProbeError):
        _run_probe(["false"], timeout=5)

def test_run_probe_missing_binary_raises_and_warns_once():
    # structlog is NOT routed through stdlib logging in this repo -> use capture_logs, assert == 1.
    from ocr.born_digital import _warned_missing
    _warned_missing.discard("definitely-not-a-real-binary-xyz")  # module-global persists across tests
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
    with pytest.raises(ProbeError):
        _run_probe(["yes"], timeout=5)  # unbounded stdout -> cap trips before timeout
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/ocr/test_born_digital.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ocr.born_digital'`.

- [ ] **Step 3: Write the module** (`src/ocr/born_digital.py`) — all imports at top

```python
"""Born-digital vs scan detection on a document's *original* PDF (spec D1–D6).

Pure bytes -> BornDigitalDecision. Shells poppler-utils (pdftotext/pdfinfo/
pdfimages/pdffonts), the same trust boundary pdf2image already uses. Every probe
failure and every malformed parse raises ProbeError; classify_original turns any
ProbeError into a fail-safe "OCR" decision (spec D6). Parsers fail CLOSED — a
garbled layout must never read as "no signal".
"""
from __future__ import annotations

import os
import re
import select
import subprocess
import time

import structlog

log = structlog.get_logger(__name__)

COVERAGE_THRESHOLD: float = 0.85
PROBE_TIMEOUT: int = 30
PROBE_MAX_OUTPUT_BYTES: int = 32 * 1024 * 1024
_GLYPHLESS_NAME: str = "glyphlessfont"
_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")
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
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeError(f"{cmd[0]} timed out")
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                raise ProbeError(f"{cmd[0]} timed out")
            chunk = os.read(fd, 65536)  # select said readable -> returns >=1 byte or b'' at EOF
            if not chunk:
                break
            total += len(chunk)
            if total > PROBE_MAX_OUTPUT_BYTES:
                raise ProbeError(f"{cmd[0]} output exceeded {PROBE_MAX_OUTPUT_BYTES} bytes")
            chunks.append(chunk)
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
            proc.wait(timeout=5)


def _parse_pdfinfo(text: str) -> tuple[int, float | None]:
    m = re.search(r"^Pages:\s+(\d+)", text, re.MULTILINE)
    if not m:
        raise ProbeError("pdfinfo: no Pages field")
    pages = int(m.group(1))
    area: float | None = None
    ms = re.search(r"^Page size:\s+([\d.]+)\s+x\s+([\d.]+)\s+pts", text, re.MULTILINE)
    if ms:
        area = (float(ms.group(1)) / 72.0) * (float(ms.group(2)) / 72.0)
    return pages, area


def _parse_char_counts(pdftotext_out: str, page_count: int) -> list[int]:
    segments = pdftotext_out.split("\f")
    # pdftotext appends a trailing \f after the last page -> exactly page_count + 1 segments.
    # Anything else (embedded \f in text, truncation) is misalignment -> fail safe (D3).
    if len(segments) != page_count + 1:
        raise ProbeError(f"pdftotext: {len(segments)} segments, expected {page_count + 1}")
    return [len(re.sub(r"\s", "", seg)) for seg in segments[:page_count]]


def _parse_max_coverage(pdfimages_list_out: str, page_area: float | None) -> dict[int, float]:
    if not page_area:
        raise ProbeError("pdfimages: no page area to normalise against")
    lines = pdfimages_list_out.splitlines()
    per_page: dict[int, float] = {}
    for line in lines[2:]:  # skip the 2 header lines
        if not line.strip():
            continue
        f = line.split()
        try:
            page, w, h = int(f[0]), int(f[3]), int(f[4])
            xppi, yppi = float(f[12]), float(f[13])
        except (IndexError, ValueError) as exc:
            raise ProbeError(f"pdfimages: unparseable row: {line!r}") from exc  # fail CLOSED
        if xppi <= 0 or yppi <= 0:
            continue
        cov = min(1.0, (w / xppi) * (h / yppi) / page_area)
        per_page[page] = max(per_page.get(page, 0.0), cov)  # LARGEST image per page (spec D3)
    return per_page


def _has_glyphless(pdffonts_out: str) -> bool:
    for line in pdffonts_out.splitlines()[2:]:  # skip the 2 header lines
        f = line.split()
        if not f:
            continue
        if _SUBSET_PREFIX_RE.sub("", f[0]).lower() == _GLYPHLESS_NAME:
            return True
    return False
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/unit/ocr/test_born_digital.py -v`
Expected: PASS (parsers + `_run_probe` hardening). (`false`/`yes`/`sleep` are coreutils; on a host lacking them the two subprocess tests fail loudly — acceptable in CI Linux/macOS.)

- [ ] **Step 5: Lint + type + commit** (the shown snippets are illustrative — run `ruff format` to normalise docstring blank lines / long-line wrapping before the `--check` gate)

Run: `python -m ruff format src/ocr/born_digital.py tests/unit/ocr/test_born_digital.py && python -m ruff check --fix src/ocr/born_digital.py tests/unit/ocr/test_born_digital.py && python -m ruff format --check src/ocr && python -m mypy src/ocr/born_digital.py`
```bash
git add src/ocr/born_digital.py tests/unit/ocr/test_born_digital.py
git commit -m "feat(ocr): born-digital probe wrappers with deadline + fail-closed parsers"
```

---

### Task 2: Detection module — `classify_original` decision + fail-safe

**Files:**
- Modify: `src/ocr/born_digital.py`
- Create: `tests/integration/test_born_digital_poppler.py`; Modify: `tests/unit/ocr/test_born_digital.py`

**Interfaces produced (used by Task 6):**
- `@dataclass(frozen=True) class BornDigitalDecision:` — `skip: bool`, `reason: str`, `signals: dict[str, object]`.
- `_probe_signals(path: str, timeout: float) -> tuple[list[int], dict[int, float], bool]` — the mock seam.
- `classify_original(data: bytes, *, min_chars: int, coverage_threshold: float = COVERAGE_THRESHOLD, timeout: float = PROBE_TIMEOUT) -> BornDigitalDecision` — any `ProbeError` → `skip=False`.

- [ ] **Step 1: Write failing decision tests** (append to `tests/unit/ocr/test_born_digital.py`)

```python
from unittest.mock import patch
from ocr.born_digital import classify_original  # _probe_signals patched via string path

def _decide(page_chars, page_cov, glyphless, min_chars=50):
    with patch("ocr.born_digital._probe_signals", return_value=(page_chars, page_cov, glyphless)):
        return classify_original(b"%PDF-1.4 fake", min_chars=min_chars)

def test_born_digital_text_skips():
    d = _decide([1443, 389], {1: 0.0, 2: 0.02}, False)
    assert d.skip is True and d.reason == "born-digital"

def test_image_heavy_born_digital_max_lock_skips():
    d = _decide([1443, 1443], {1: 0.0, 2: 0.41}, False)  # largest image 0.41 < COVERAGE
    assert d.skip is True  # locks max formula against a max->sum regression

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
            return {"pdfinfo": "Pages: 1\nPage size: 595 x 841 pts\n",
                    "pdftotext": "hello world enough text here to pass\f",
                    "pdfimages": "h1\nh2\n"}[cmd[0]]
        monkeypatch.setattr("ocr.born_digital._run_probe", side_effect)
        d = classify_original(b"%PDF", min_chars=5)
        assert d.skip is False
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/ocr/test_born_digital.py -k "decide or skip or ocr or boundary or guard or probe" -v`
Expected: FAIL — `classify_original` / `_probe_signals` not defined.

- [ ] **Step 3: Implement** (append to `src/ocr/born_digital.py`; add `import tempfile` and `from dataclasses import dataclass` to the top import block — `os`/`re` are already there)

```python
@dataclass(frozen=True)
class BornDigitalDecision:
    """The gate's verdict for one document, plus the signals that produced it (for logging)."""

    skip: bool
    reason: str
    signals: dict[str, object]


def _probe_signals(path: str, timeout: float) -> tuple[list[int], dict[int, float], bool]:
    """Run the four poppler probes; return (page_char_counts, page_coverage, glyphless).

    Any probe/parse failure propagates as ProbeError.
    """
    pages, area = _parse_pdfinfo(_run_probe(["pdfinfo", path], timeout))
    if pages <= 0:
        raise ProbeError("pdfinfo: non-positive page count")
    char_counts = _parse_char_counts(_run_probe(["pdftotext", "-q", path, "-"], timeout), pages)
    coverage = _parse_max_coverage(_run_probe(["pdfimages", "-list", path], timeout), area)
    glyphless = _has_glyphless(_run_probe(["pdffonts", path], timeout))
    return char_counts, coverage, glyphless


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
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        try:
            char_counts, coverage, glyphless = _probe_signals(path, timeout)
        except ProbeError as exc:
            return BornDigitalDecision(False, f"probe-failed:{exc}", {})
        min_page_chars = min(char_counts) if char_counts else 0
        max_cov = max(coverage.values()) if coverage else 0.0
        signals: dict[str, object] = {
            "pages": len(char_counts),
            "min_page_chars": min_page_chars,
            "max_coverage": round(max_cov, 3),
            "glyphless": glyphless,
        }
        if glyphless:
            return BornDigitalDecision(False, "glyphless-ocr-layer", signals)
        if min_page_chars < min_chars:
            return BornDigitalDecision(False, "low-text-page", signals)
        if any(c >= coverage_threshold for c in coverage.values()):
            return BornDigitalDecision(False, "full-page-image", signals)
        return BornDigitalDecision(True, "born-digital", signals)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
```

- [ ] **Step 4: Run unit tests** → PASS

Run: `python -m pytest tests/unit/ocr/test_born_digital.py -v`

- [ ] **Step 5: Write poppler-guarded e2e** (`tests/integration/test_born_digital_poppler.py`)

Pillow (already a dep) makes image-only "scan" PDFs directly. A born-digital positive is covered by the mocked decision tests + parser tests (no dependency-free text-layer PDF generator exists — noted in the spec's testing section); here we exercise the real subprocess wiring on the scan + corrupt paths.

```python
import io
import shutil
import pytest
from PIL import Image, ImageDraw
from ocr.born_digital import classify_original

_POPPLER = all(shutil.which(b) for b in ("pdftotext", "pdfimages", "pdfinfo", "pdffonts"))
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
```

- [ ] **Step 6: Run integration + commit**

Run: `python -m pytest tests/integration/test_born_digital_poppler.py -v` (PASS or SKIP without poppler)
```bash
git add src/ocr/born_digital.py tests/unit/ocr/test_born_digital.py tests/integration/test_born_digital_poppler.py
git commit -m "feat(ocr): born-digital classify_original decision with fail-safe"
```

---

### Task 3: Config keys (catalogue + settings + parsing)

**Files:** Modify `src/common/config/_catalogue.py`, `src/common/config/_settings.py`; `tests/unit/common/test_config.py`.

**Interfaces produced (used by Task 6):** `Settings.OCR_SKIP_BORN_DIGITAL: bool`, `Settings.OCR_BORN_DIGITAL_MIN_CHARS: int`, `Settings.OCR_BORN_DIGITAL_TAG_ID: int | None`.

- [ ] **Step 1: Update the pinned key-count test + add parsing tests** (`tests/unit/common/test_config.py`)

The existing pin is `test_config_keys_has_eighty_seven_entries` — it carries a count-history docstring **and ~a dozen key-presence assertions** (`OPENAI_FLEX_TIER`, `SEARCH_*`, `EMBEDDING_PROVIDER`, …). **Edit it in place — do NOT replace its body:** (1) rename → `test_config_keys_has_ninety_entries`; (2) change `== 87` → `== 90`; (3) append the count-history line for +3 born-digital keys to the docstring; (4) **keep every existing presence assertion** and add one line asserting the three new keys are present:
```python
    assert {"OCR_SKIP_BORN_DIGITAL", "OCR_BORN_DIGITAL_MIN_CHARS", "OCR_BORN_DIGITAL_TAG_ID"} <= CONFIG_KEYS
```
Update the `-k` filter in Step 4 to match the renamed test (`ninety`).

Add settings-parsing tests (real `Settings` via the factory):

```python
import pytest
from tests.helpers.factories import make_settings

def test_born_digital_defaults():
    s = make_settings()
    assert s.OCR_SKIP_BORN_DIGITAL is True
    assert s.OCR_BORN_DIGITAL_MIN_CHARS == 50
    assert s.OCR_BORN_DIGITAL_TAG_ID is None

def test_min_chars_rejects_zero():
    with pytest.raises(ValueError):
        make_settings(OCR_BORN_DIGITAL_MIN_CHARS="0")

def test_tag_id_parses_positive_int():
    assert make_settings(OCR_BORN_DIGITAL_TAG_ID="17").OCR_BORN_DIGITAL_TAG_ID == 17
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/unit/common/test_config.py -k "ninety or born_digital" -v` → FAIL.

- [ ] **Step 3: Add the keys**

`_catalogue.py` — into the `CONFIG_KEYS` frozenset (near the `OCR_*` entries):
```python
        "OCR_SKIP_BORN_DIGITAL",
        "OCR_BORN_DIGITAL_MIN_CHARS",
        "OCR_BORN_DIGITAL_TAG_ID",
```
`_settings.py` — `Settings` fields (near `OCR_INCLUDE_PAGE_MODELS` / `OCR_PROCESSING_TAG_ID`):
```python
    OCR_SKIP_BORN_DIGITAL: bool
    OCR_BORN_DIGITAL_MIN_CHARS: int
    OCR_BORN_DIGITAL_TAG_ID: int | None
```
`_settings.py` — in `_build_settings(...)`, alongside the OCR fields:
```python
        OCR_SKIP_BORN_DIGITAL=_get_bool_env(source, "OCR_SKIP_BORN_DIGITAL", True),
        OCR_BORN_DIGITAL_MIN_CHARS=_require_at_least_one(
            "OCR_BORN_DIGITAL_MIN_CHARS", _get_int_env(source, "OCR_BORN_DIGITAL_MIN_CHARS", 50)
        ),
        OCR_BORN_DIGITAL_TAG_ID=_get_optional_positive_int_env(source, "OCR_BORN_DIGITAL_TAG_ID"),
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/unit/common/test_config.py -k "ninety or born_digital" -v` → PASS.

- [ ] **Step 5: Type-check + commit**
```bash
python -m mypy src/common/config/
git add src/common/config/_catalogue.py src/common/config/_settings.py tests/unit/common/test_config.py
git commit -m "feat(config): add born-digital OCR-skip settings keys"
```

---

### Task 4: `PaperlessClient.download_original`

**Files:** Modify `src/common/paperless.py`; `tests/unit/common/test_paperless.py`.

**Interface produced (used by Task 6):** `download_original(self, doc_id: int) -> tuple[bytes, str]`.

- [ ] **Step 1: Write failing test** (mirror the module's respx style — `_make_client()`, `respx.mock`, `BASE`)

```python
def test_download_original_uses_original_true():
    url = f"{BASE}/api/documents/5/download/?original=true"
    with respx.mock:
        respx.get(url__eq=url).mock(
            return_value=httpx.Response(
                200, content=b"%PDF-1.4 orig", headers={"Content-Type": "application/pdf"}
            )
        )
        client = _make_client()
        data, ct = client.download_original(5)
    assert data == b"%PDF-1.4 orig" and ct == "application/pdf"
    client.close()
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/unit/common/test_paperless.py -k download_original -v` → FAIL (`AttributeError`).

- [ ] **Step 3: Implement** (`src/common/paperless.py`, next to `download_content`)

```python
    def download_original(self, doc_id: int) -> tuple[bytes, str]:
        """Download the pristine ORIGINAL file (pre-archive/pre-OCR) bytes + content type.

        Unlike :meth:`download_content` (which serves the archive when one exists), this
        appends ``?original=true`` so a scan's original has no Tesseract text layer — the
        mode-independent signal the born-digital gate needs (spec D2).
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/download/?original=true"
        response = self._get(url)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "application/pdf")
        return response.content, content_type
```

- [ ] **Step 4: Run to verify pass + commit** — `python -m pytest tests/unit/common/test_paperless.py -k download -v` → PASS
```bash
git add src/common/paperless.py tests/unit/common/test_paperless.py
git commit -m "feat(paperless): add download_original (?original=true)"
```

---

### Task 5: Settings UI fields

**Files:** Modify `web/src/features/settings/fieldModel/sections.ts`; the field-model test (`web/src/features/settings/fieldModel/sections.test.ts` — create if absent).

**Verified layout (2026-07-21):** the OCR section (`id: 'ocr'`) has groups `model` and `imaging` (with an `advanced` fold). The `automation` section (`id: 'automation'`) has group `tags` (`fields`: `PRE_TAG_ID`/`POST_TAG_ID`/`ERROR_TAG_ID`, subtitle "Set 0 to disable a tag", every control `min: 0`) and group `workers` (whose `advanced` holds `OCR_PROCESSING_TAG_ID`). Keys must string-match the backend.

- [ ] **Step 1: Write failing test**

```ts
// vitest here uses explicit imports (no globals) — matches the repo convention (e.g. cn.test.ts).
import { describe, it, expect } from 'vitest';
import { SETTINGS_SECTIONS } from './sections';

describe("born-digital OCR-skip settings", () => {
 it("exposes born-digital OCR-skip fields", () => {
  const ocr = SETTINGS_SECTIONS.find(s => s.id === "ocr")!;
  const ocrFields = ocr.groups.flatMap(g => [...g.fields, ...(g.advanced ?? [])]);
  expect(ocrFields.find(f => f.key === "OCR_SKIP_BORN_DIGITAL")!.control.kind).toBe("toggle");
  expect(ocrFields.find(f => f.key === "OCR_BORN_DIGITAL_MIN_CHARS")!.control.kind).toBe("number");
  // master switch must be visible, not buried in an advanced fold:
  const bornGroup = ocr.groups.find(g => g.id === "born-digital")!;
  expect(bornGroup.fields.some(f => f.key === "OCR_SKIP_BORN_DIGITAL")).toBe(true);

  const automation = SETTINGS_SECTIONS.find(s => s.id === "automation")!;
  const tagsGroup = automation.groups.find(g => g.id === "tags")!;
  const tag = tagsGroup.fields.find(f => f.key === "OCR_BORN_DIGITAL_TAG_ID")!;
  expect(tag.control.kind).toBe("number");
 });
});
```

- [ ] **Step 2: Run to verify failure** — `cd web && npm test -- sections` → FAIL.

- [ ] **Step 3: Add the fields**

Add a new group to the OCR section's `groups` array (after `imaging`), master switch in **visible** `fields`:
```ts
{
  id: 'born-digital',
  title: 'Born-digital skip',
  subtitle: 'Skip AI OCR on PDFs that already have a real text layer.',
  fields: [
    {
      key: 'OCR_SKIP_BORN_DIGITAL',
      label: 'Skip AI OCR on born-digital PDFs',
      hint: 'Detect PDFs with a genuine text layer and skip the vision model. Scans, images and searchable scans still get AI OCR.',
      control: { kind: 'toggle' },
    },
    {
      key: 'OCR_BORN_DIGITAL_MIN_CHARS',
      label: 'Born-digital min characters/page',
      hint: 'A page needs at least this many characters of real text to count as born-digital.',
      control: { kind: 'number', min: 1 },
    },
  ],
},
```
Add the marker tag to the `automation` → `tags` group's `fields` (min 0 = disable, matching the group):
```ts
{
  key: 'OCR_BORN_DIGITAL_TAG_ID',
  label: 'Born-digital marker',
  hint: 'Optional. Tag applied to documents skipped as born-digital, so you can audit and force a re-OCR. 0 to disable.',
  control: { kind: 'number', min: 0 },
},
```

- [ ] **Step 4: Web checks** — `cd web && npm test -- sections && npm run typecheck && npm run lint` → PASS
- [ ] **Step 5: Commit**
```bash
git add web/src/features/settings/fieldModel/sections.ts web/src/features/settings/fieldModel/sections.test.ts
git commit -m "feat(web): expose born-digital OCR-skip settings"
```

---

### Task 6: Worker gate — the skip branch in `OcrProcessor.process()`

**Files:** Modify `src/ocr/worker.py`, `tests/helpers/factories/_core.py`, `tests/unit/ocr/conftest.py` (hoist `_http_status_error`), `tests/unit/ocr/test_worker_internals.py`, `tests/unit/ocr/test_worker.py`.

**Interfaces consumed:** `born_digital.classify_original` (T2), `PaperlessClient.download_original` (T4), the 3 `Settings` fields (T3), and existing `clean_pipeline_tags` / `get_latest_tags` / `finalise_document_with_error` / `is_permanent_paperless_error` / `update_document_metadata` / `PAPERLESS_CALL_EXCEPTIONS` / `WriteBackOutcome` (all already imported in `worker.py`).

**Control flow** — insert after the `claim_processing_tag` block, before `pages = self._download_and_convert(...)`:
```python
gate = self._try_skip_born_digital(document)
if gate is not _GateOutcome.PROCEED:
    success = gate is None          # a clean skip is a success; a quarantine is not
    return gate                     # None (skipped) or WriteBackOutcome.QUARANTINED
# else fall through to the existing OCR path unchanged
```

- [ ] **Step 0: Keep existing worker tests green.** Add to `make_settings_obj`'s `defaults` dict (`tests/helpers/factories/_core.py`) — gate **off** so mock-settings tests never enter it:
```python
        "OCR_SKIP_BORN_DIGITAL": False,
        "OCR_BORN_DIGITAL_MIN_CHARS": 50,
        "OCR_BORN_DIGITAL_TAG_ID": None,
```

- [ ] **Step 1: Write failing gate-method tests** (`tests/unit/ocr/test_worker_internals.py`) — target `_try_skip_born_digital` directly (avoids running the OCR path)

```python
# Hoist the shared HTTP-error builder to conftest so both worker test files share one copy:
#   1. Move `_http_status_error(status)` (currently a local def in test_worker.py:25) into
#      tests/unit/ocr/conftest.py, adding `import httpx` there.
#   2. In test_worker.py: delete the local def, add `_http_status_error` to its conftest import.
#   3. In test_worker_internals.py add these imports. NOTE: `patch`, `WriteBackOutcome`, and
#      `make_processor` are ALREADY imported in this module — do NOT re-import them (F811).
import pytest
from common.paperless import PAPERLESS_CALL_EXCEPTIONS
from ocr.born_digital import BornDigitalDecision
from ocr.worker import _GateOutcome
from tests.helpers.factories import make_document
from tests.unit.ocr.conftest import _http_status_error  # add to the existing conftest import line

def _skip(dec=True):
    return BornDigitalDecision(dec, "born-digital" if dec else "full-page-image", {})

def test_gate_off_returns_proceed():
    proc = make_processor(OCR_SKIP_BORN_DIGITAL=False)
    assert proc._try_skip_born_digital(make_document()) is _GateOutcome.PROCEED
    proc.paperless_client.download_original.assert_not_called()

def test_non_pdf_mime_returns_proceed_without_fetch():
    proc = make_processor(OCR_SKIP_BORN_DIGITAL=True)
    doc = make_document(mime_type="image/jpeg")
    assert proc._try_skip_born_digital(doc) is _GateOutcome.PROCEED
    proc.paperless_client.download_original.assert_not_called()

def test_empty_content_returns_proceed_without_fetch():
    proc = make_processor(OCR_SKIP_BORN_DIGITAL=True)
    doc = make_document(mime_type="application/pdf", content="   ")
    assert proc._try_skip_born_digital(doc) is _GateOutcome.PROCEED
    proc.paperless_client.download_original.assert_not_called()

def test_mime_absent_fetches_original_and_uses_content_type():
    proc = make_processor(OCR_SKIP_BORN_DIGITAL=True)
    doc = make_document(content="real text " * 50)   # make_document has NO mime_type key
    proc.paperless_client.download_original.return_value = (b"%PDF", "application/pdf")
    with patch("ocr.worker.classify_original", return_value=_skip(True)):
        assert proc._try_skip_born_digital(doc) is None
    proc.paperless_client.download_original.assert_called_once()

def test_original_non_pdf_content_type_proceeds():
    proc = make_processor(OCR_SKIP_BORN_DIGITAL=True)
    doc = make_document(content="x " * 50)
    proc.paperless_client.download_original.return_value = (b"\xff\xd8", "image/jpeg")
    assert proc._try_skip_born_digital(doc) is _GateOutcome.PROCEED

def test_original_fetch_failure_proceeds():
    proc = make_processor(OCR_SKIP_BORN_DIGITAL=True)
    doc = make_document(mime_type="application/pdf", content="x " * 50)
    proc.paperless_client.download_original.side_effect = _http_status_error(503)
    assert proc._try_skip_born_digital(doc) is _GateOutcome.PROCEED

def test_born_digital_skips_tags_only_no_content_rewrite():
    proc = make_processor(OCR_SKIP_BORN_DIGITAL=True)
    doc = make_document(mime_type="application/pdf", content="real text " * 50)
    proc.paperless_client.download_original.return_value = (b"%PDF", "application/pdf")
    with patch("ocr.worker.classify_original", return_value=_skip(True)), \
         patch("ocr.worker.get_latest_tags", return_value={proc.settings.PRE_TAG_ID}):
        assert proc._try_skip_born_digital(doc) is None
    proc.paperless_client.update_document_metadata.assert_called_once()
    proc.paperless_client.update_document.assert_not_called()          # no content write
    _, kwargs = proc.paperless_client.update_document_metadata.call_args
    assert proc.settings.POST_TAG_ID in kwargs["tags"]
    assert proc.settings.PRE_TAG_ID not in kwargs["tags"]

def test_marker_tag_applied_when_configured():
    proc = make_processor(OCR_SKIP_BORN_DIGITAL=True, OCR_BORN_DIGITAL_TAG_ID=77)
    doc = make_document(mime_type="application/pdf", content="real text " * 50)
    proc.paperless_client.download_original.return_value = (b"%PDF", "application/pdf")
    with patch("ocr.worker.classify_original", return_value=_skip(True)), \
         patch("ocr.worker.get_latest_tags", return_value={proc.settings.PRE_TAG_ID}):
        proc._try_skip_born_digital(doc)
    _, kwargs = proc.paperless_client.update_document_metadata.call_args
    assert 77 in kwargs["tags"]

def test_not_born_digital_proceeds():
    proc = make_processor(OCR_SKIP_BORN_DIGITAL=True)
    doc = make_document(mime_type="application/pdf", content="x " * 50)
    proc.paperless_client.download_original.return_value = (b"%PDF", "application/pdf")
    with patch("ocr.worker.classify_original", return_value=_skip(False)):
        assert proc._try_skip_born_digital(doc) is _GateOutcome.PROCEED

def test_permanent_skip_write_quarantines():
    proc = make_processor(OCR_SKIP_BORN_DIGITAL=True)
    doc = make_document(mime_type="application/pdf", content="x " * 50)
    proc.paperless_client.download_original.return_value = (b"%PDF", "application/pdf")
    proc.paperless_client.update_document_metadata.side_effect = _http_status_error(400)
    with patch("ocr.worker.classify_original", return_value=_skip(True)), \
         patch("ocr.worker.get_latest_tags", return_value={proc.settings.PRE_TAG_ID}):
        assert proc._try_skip_born_digital(doc) is WriteBackOutcome.QUARANTINED

def test_transient_skip_write_reraises():
    proc = make_processor(OCR_SKIP_BORN_DIGITAL=True)
    doc = make_document(mime_type="application/pdf", content="x " * 50)
    proc.paperless_client.download_original.return_value = (b"%PDF", "application/pdf")
    proc.paperless_client.update_document_metadata.side_effect = _http_status_error(503)
    with patch("ocr.worker.classify_original", return_value=_skip(True)), \
         patch("ocr.worker.get_latest_tags", return_value={proc.settings.PRE_TAG_ID}):
        with pytest.raises(PAPERLESS_CALL_EXCEPTIONS):
            proc._try_skip_born_digital(doc)
```

Also add a **`process()`-level** test (`tests/unit/ocr/test_worker.py`) asserting a skip returns `None`, runs no vision, and releases the processing tag. (`test_worker.py` already imports `make_processor`, `make_document`, `patch`; add `from ocr.born_digital import BornDigitalDecision`.)

```python
def test_process_skips_born_digital_end_to_end():
    proc = make_processor(OCR_SKIP_BORN_DIGITAL=True, OCR_PROCESSING_TAG_ID=999)
    proc.paperless_client.get_document.return_value = make_document(
        mime_type="application/pdf", content="real text " * 50, tags=[proc.settings.PRE_TAG_ID])
    proc.paperless_client.download_original.return_value = (b"%PDF", "application/pdf")
    with patch("ocr.worker.classify_original",
               return_value=BornDigitalDecision(True, "born-digital", {})), \
         patch("ocr.worker.get_latest_tags", return_value={proc.settings.PRE_TAG_ID}), \
         patch("ocr.worker.claim_processing_tag", return_value=True), \
         patch("ocr.worker.release_processing_tag") as release:
        outcome = proc.process()
    assert outcome is None                              # breaker-neutral
    assert proc.ocr_provider.transcribe_image.call_count == 0
    release.assert_called_once()                        # processing tag released
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/unit/ocr/test_worker_internals.py -k gate -v` → FAIL (`_GateOutcome`/method absent).

- [ ] **Step 3: Implement the gate** (`src/ocr/worker.py`)

Add at the top of the file (with the existing imports — do NOT re-import `clean_pipeline_tags`, already present):
```python
from enum import Enum

from .born_digital import BornDigitalDecision, classify_original


class _GateOutcome(Enum):
    """Sentinel for the born-digital gate: PROCEED means 'not skipped, run OCR'."""
    PROCEED = 1
```
Add the method to `OcrProcessor`:
```python
    def _try_skip_born_digital(
        self, document: dict
    ) -> WriteBackOutcome | None | _GateOutcome:
        """Born-digital gate (spec D1–D6). None on a clean skip, WriteBackOutcome.QUARANTINED
        on a permanent skip-write failure, or _GateOutcome.PROCEED to fall through to OCR.
        Transient write errors re-raise for the daemon loop to retry."""
        s = self.settings
        if not s.OCR_SKIP_BORN_DIGITAL:
            return _GateOutcome.PROCEED
        mime = document.get("mime_type") or ""
        if mime and "pdf" not in mime.lower():
            return _GateOutcome.PROCEED                      # image upload -> scan -> OCR
        if not (document.get("content") or "").strip():
            return _GateOutcome.PROCEED                      # empty ngx content guard (D5)
        try:
            data, content_type = self.paperless_client.download_original(self.doc_id)
        except PAPERLESS_CALL_EXCEPTIONS:
            log.warning("born_digital.original_fetch_failed", doc_id=self.doc_id)
            return _GateOutcome.PROCEED                      # fail-safe -> OCR
        if "pdf" not in (content_type or "").lower():
            return _GateOutcome.PROCEED
        decision = classify_original(data, min_chars=s.OCR_BORN_DIGITAL_MIN_CHARS)
        log.info("born_digital.decision", doc_id=self.doc_id, skip=decision.skip,
                 reason=decision.reason, **decision.signals)
        if not decision.skip:
            return _GateOutcome.PROCEED
        tags = clean_pipeline_tags(
            get_latest_tags(self.paperless_client, self.doc_id, fallback_doc=self.doc), s
        )
        tags.add(s.POST_TAG_ID)
        if s.OCR_BORN_DIGITAL_TAG_ID is not None:
            tags.add(s.OCR_BORN_DIGITAL_TAG_ID)
        try:
            self.paperless_client.update_document_metadata(self.doc_id, tags=tags)
        except PAPERLESS_CALL_EXCEPTIONS as exc:
            if not is_permanent_paperless_error(exc):
                raise                                        # transient -> loop retries
            log.error("born_digital.skip_write_rejected", doc_id=self.doc_id, error=str(exc))
            finalise_document_with_error(
                self.paperless_client, self.doc_id,
                get_latest_tags(self.paperless_client, self.doc_id, fallback_doc=self.doc), s,
            )
            return WriteBackOutcome.QUARANTINED
        log.info("born_digital.skipped", doc_id=self.doc_id, added_tag=s.POST_TAG_ID)
        return None
```
Wire it into `process()` after the claim per **Control flow** above (set `success = gate is None` before the early return).

- [ ] **Step 4: Run to verify pass + no regression**

Run: `python -m pytest tests/unit/ocr/ -q && python -m mypy src/ocr/`
Expected: green (new gate tests + all existing worker tests unaffected — gate off by default in `make_settings_obj`).

- [ ] **Step 5: Lint + commit** (format the files you changed first, then the gate checks)
```bash
python -m ruff format src/ocr/worker.py tests/helpers/factories/_core.py tests/unit/ocr/
python -m ruff check --fix src/ocr tests && python -m ruff format --check src/ocr tests
git add src/ocr/worker.py tests/helpers/factories/_core.py tests/unit/ocr/
git commit -m "feat(ocr): skip AI OCR for born-digital PDFs in the worker gate"
```

---

### Task 7: End-to-end integration test + DECISIONS entry

**Files:** Modify `tests/e2e/test_ocr_workflow.py`, `.claude/DECISIONS.md`.

- [ ] **Step 1: Write the e2e skip test** (`tests/e2e/test_ocr_workflow.py`) against the stateful mock (`make_stateful_paperless` stubs `download_content`; the gate path needs `download_original` stubbed + `classify_original` patched, since no real text-layer PDF generator exists)

```python
def test_e2e_born_digital_skips_and_advances_tag():
    from unittest.mock import patch
    from ocr.born_digital import BornDigitalDecision
    from tests.helpers.factories import make_settings_obj
    from tests.helpers.mocks import make_stateful_paperless

    doc = make_document(mime_type="application/pdf", content="real born-digital text " * 40, tags=[443])
    client, state = make_stateful_paperless(doc)
    client.download_original.return_value = (b"%PDF", "application/pdf")
    settings = make_settings_obj(OCR_SKIP_BORN_DIGITAL=True, PRE_TAG_ID=443, POST_TAG_ID=444,
                                 OCR_BORN_DIGITAL_TAG_ID=555)
    proc = OcrProcessor(doc, client, make_mock_ocr_provider(), settings)
    with patch("ocr.worker.classify_original",
               return_value=BornDigitalDecision(True, "born-digital", {})):
        outcome = proc.process()
    assert outcome is None
    assert 444 in state["tags"] and 443 not in state["tags"]     # PRE -> POST
    assert 555 in state["tags"]                                  # marker applied
    client.update_document.assert_not_called()                  # content untouched
```

- [ ] **Step 2: Run it, then the whole suite**

Run: `python -m pytest tests/e2e/test_ocr_workflow.py -k born_digital -v` → PASS
Run: `python -m pytest -q && cd web && npm test` → green

- [ ] **Step 3: DECISIONS entry** (`.claude/DECISIONS.md`, append per its format)
```markdown
## 2026-07-21 — Skip AI OCR on born-digital PDFs
**Decision:** A deterministic poppler gate in the OCR worker skips vision-OCR for PDFs already
born-digital — detected on the original (pdftotext text yield + pdfimages largest-image coverage
+ pdffonts GlyphLessFont) — while AI-OCRing scans, images and searchable scans. Default on,
whole-doc, three UI config keys, fail-safe to OCR on any doubt.
**Why:** Cuts vision spend on the majority-born-digital ingest stream with zero quality risk —
every doubt falls through to OCR; default-on is the operator's explicit choice.
**Spec:** .claude/specs/20260721-born-digital-ocr-skip.md
**Affects:** src/ocr/born_digital.py (new), src/ocr/worker.py, src/common/paperless.py,
src/common/config/*, web settings.
```

- [ ] **Step 4: Commit**
```bash
git add tests/e2e/test_ocr_workflow.py .claude/DECISIONS.md
git commit -m "test(ocr): e2e born-digital skip; docs: DECISIONS entry"
```

---

## Post-implementation (orchestrator, not a task)

- **Human doc:** `docs/ocr-pipeline.md` describes "OCR everything tagged" — now wrong. Flag to the operator; update only on their go-ahead (human doc).
- **KB:** the push gate spawns kb-updater (diff mode) for `docs/PIPELINES.md`, `docs/modules/ocr.md`, `docs/CONFIGURATION.md`.
- **Gates:** `.claude/GATES.md` green (pytest, mypy, `ruff check`, `ruff format --check`, bandit, web typecheck/lint/test/build) before the review-team gate.
- **Acceptance:** the spec's acceptance probe (`scratchpad/` is uncommitted/PII) must be **regenerated** from the spec's signal definitions (max-coverage formula) and run against the live instance post-deploy; confirm the decision log + marker-tag filter.

## Self-review (author; verified against code 2026-07-21)

- **Spec coverage:** D1 (T6 gate), D2 (T4 + T6 fetch), D3 (T1–T2 signals/rule incl. `!= N+1` segmentation, largest-image coverage, `GlyphLessFont` subset-prefix), D4 (T3 config + T1 constant), D5 (T6 tags-only PATCH via `get_latest_tags`, guard, `None`/`QUARANTINED`), D6 (T1 deadline+cap+missing-binary-warning + fail-closed parsers; T2 fail-safe; T6 fall-throughs), D7 (T3 + T5 visible master switch + marker in tags group), D8 (whole-doc rule), D9 (T1 subprocess), D10 (T6 mime + Content-Type fallback), D11 (nothing touches flex). Testing reqs: probe hardening (T1), per-probe incl. pdffonts (T2), D10 (T6), release-on-skip (T6), fail-closed parse (T1). ✓
- **Placeholders:** none — every code step shows runnable code; `_probe_signals`/`_run_probe` are the mock seams, both defined.
- **Verified against code:** `make_processor(**setting_overrides)` (a function, splat overrides); `make_document` has `content`+`tags`, **no** `mime_type` (tests pass it explicitly); `make_mock_paperless` stubs `download_content`/`update_document_metadata` but NOT `download_original` (tests set its `return_value`); `_http_status_error(status)` is a **local def in `test_worker.py` (line 25), `tests/unit/common/test_tags.py`, and `tests/unit/classifier/test_worker.py` (not exhaustive) — NOT in `test_worker_internals.py`** — Task 6 hoists it into `tests/unit/ocr/conftest.py` (add `import httpx` there) and imports it in both ocr worker test files; `test_worker_internals.py` already imports `patch`/`WriteBackOutcome`/`make_processor` (do not re-import); respx via `_make_client()`+`respx.get(url__eq=...).mock(httpx.Response(...))`+`BASE`; `sections.ts` groups `ocr`→{model,imaging}, `automation`→{tags(fields: PRE/POST/ERROR, min:0),workers(advanced holds OCR_PROCESSING_TAG_ID)}; pinned test is `test_config_keys_has_eighty_seven_entries` (renamed to ninety); `worker.py` already imports `clean_pipeline_tags`/`get_latest_tags`/`finalise_document_with_error`/`is_permanent_paperless_error`; `DocumentMetadataUpdate.tags: set[int]` (pass a set). Correction to the previous draft: `OCR_PROCESSING_TAG_ID` lives in the `workers` group's `advanced`, **not** the `tags` group.
- **Type consistency:** `classify_original`/`BornDigitalDecision`/`_probe_signals(path, timeout)`/`download_original`/`_try_skip_born_digital(document) -> WriteBackOutcome | None | _GateOutcome` consistent across tasks; `_GateOutcome.PROCEED` the single sentinel; `_run_probe(cmd, timeout)` threaded from `classify_original(timeout=...)`.
