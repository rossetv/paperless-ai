# Spec — skip AI OCR on born-digital PDFs

**Date:** 2026-07-21 · **Session slug:** born-digital-ocr-skip · **Status:** draft (awaiting operator approval)

## Goal

Stop burning vision-OCR tokens on documents that already carry a real embedded text layer
(born-digital PDFs — invoices, statements, letters exported straight from software). Today the
OCR daemon rasterises and vision-transcribes **every** document tagged `PRE_TAG_ID`, with no
check for existing text. Add a deterministic, free, poppler-only gate that skips AI OCR for a
document **only** when every page is genuine born-digital text, and AI-OCRs everything else —
scans, images, and "searchable scans" (a scanned image with the scanner's own baked-in OCR
text). Fail-safe: any doubt → OCR. Forward-looking only (new ingestions); no retroactive sweep.

## Background and evidence

### How the pipeline works today (verified against code)

- `OcrProcessor.process()` (`src/ocr/worker.py`) unconditionally: re-fetches the document,
  claims the processing tag, `_download_and_convert` (rasterise), `_ocr_pages_in_parallel`
  (vision), `assemble_full_text`, writes back swapping `PRE_TAG_ID`→`POST_TAG_ID`. There is
  **no** existing-content / text-layer / born-digital check anywhere.
- `get_document()` (`src/common/paperless.py`) returns the full Paperless JSON, which
  **includes the `content` field** (paperless-ngx's own extracted text) and `mime_type`. The
  worker already fetches this for free and ignores `content`.
- `download_content()` hits `/api/documents/{id}/download/` with **no** `?original=true` — so
  it downloads the **archive** (OCR-processed) file, not the pristine original.

### Paperless-ngx behaviour (verified live against docs.paperless-ngx.com, 2026-07-21)

- `PAPERLESS_OCR_MODE=skip` (the operator's setting) does **not** mean "no OCR": OCRmyPDF still
  Tesseract-OCRs pages that have **no** text layer (scans), and leaves already-textual pages
  (born-digital) untouched. So a scan's `content` is Tesseract output.
- **The original uploaded file is always preserved, separate from the archive, in every OCR
  mode.** `?original=true` on the download endpoint returns that pristine original; the default
  serves the archive when one exists. This is the linchpin: the original of a scan has **no**
  Tesseract text layer, so it is a clean, mode-independent signal.

### Empirical probe (2026-07-21, run in-container against the operator's live instance, 9 real documents)

A probe script (`scratchpad/probe.py`, **not committed** — carries doc ids/filenames) fetched
each document's original via the API from inside `paperless-ocr` and measured the signals with
the poppler binaries already in the image. Operator confirmed **9/9 verdicts correct**.

| id | class | pages | min chars/page | max image coverage | verdict |
|---|---|---|---|---|---|
| Doc A | born-digital + 41% embedded image | 2 | 1443 | **0.41** | SKIP |
| Doc B | born-digital text | 3 | 389 | 0.00 | SKIP |
| Doc C | born-digital text | 1 | 2052 | 0.02 | SKIP |
| Doc D | born-digital text | 5 | 1508 | 0.00 | SKIP |
| Doc E | born-digital text | 3 | 729 | 0.01 | SKIP |
| Doc F | pure image scan (0 text in original; ngx has 4718 Tesseract chars) | 2 | **0** | 1.00 | OCR |
| Doc G | pure image scan | 6 | **0** | 1.05 | OCR |
| Doc H | mixed: text pages + scanned pages | 4 | **0** | 0.995 | OCR |
| Doc I | mixed: translation text + scanned cert images | 6 | **0** | 1.004 | OCR |

**What the data proves:** (a) the signal is effectively binary — born-digital pages 389–2052
chars, scan pages exactly 0; image coverage born-digital ≤0.41, scans 0.99–1.05, both with a
wide dead-space margin. (b) Coverage-over-size is required: Doc A's 41% embedded image is
correctly skipped where a crude "any big raster → OCR" rule would wrongly OCR it. (c) The
operator's requirement holds: Doc F has ngx Tesseract `content` but its **original** is a pure
image → correctly AI-OCR'd, never skipped on the strength of Tesseract text. (d) This operator's
scanner emits **pure-image** originals (0 text, 0 fonts) — so the text-floor alone separates
everything in this sample; the coverage and glyphless-font signals are the insurance that catch a
*searchable scan* (image + baked-in OCR text), which the operator explicitly requires and which
foreign PDFs may be.

### Config → Settings-UI wiring (verified)

The Settings UI is **not** auto-generated from the backend catalogue. Exposing a key is a
two-sided declarative change: backend `CONFIG_KEYS` (`_catalogue.py`) + a `Settings` field &
parse-with-default (`_settings.py`), and a frontend `SettingsField` entry in
`web/src/features/settings/fieldModel/sections.ts`. The control kinds already exist
(`ToggleControl`, `NumberControl`) — no new React components.

## Decisions

### D1 — An in-worker gate, philosophy A: skip only TRUE born-digital

The decision lives inside `OcrProcessor.process()`, evaluated after the processing-tag claim
and before `_download_and_convert`. It reuses the existing claim/release and write-back
machinery. Philosophy A: skip AI OCR **only** when a document is confidently born-digital on
every page; AI-OCR everything else (scans, images, searchable scans). Skipping is on the
*presence and structure* of a real text layer, never on a guess about text *quality*.
**Rejected:** a cheap-LLM "is the OCR good enough" judge (operator's first idea) — it spends a
call per document, coherence ≠ correctness (misses mangled numbers/tables), and it cannot tell
born-digital from a scanner's shitty-but-coherent OCR; a separate triage daemon (new process,
new tags — overkill); gating before the pre-tag (paperless-ai does not control pre-tagging).

### D2 — Detect on the ORIGINAL file (`?original=true`), never the archive

The gate downloads the **original** via a new `PaperlessClient` method (mirrors
`download_content` but appends `?original=true`). In `skip` mode the archive of a scan carries
a Tesseract text layer, so "the downloaded PDF has text" cannot distinguish born-digital from
scanned — but the **original** scan has no text layer at all. Reading the original makes the
signal mode-independent and pristine (verified: Doc F/Doc G originals have 0 text, 0 fonts).
The OCR path (when not skipped) keeps using `download_content` (the archive) unchanged, so any
OCRmyPDF image-cleaning a future operator enables is preserved. **Rejected:** reusing the
archive for detection (contaminated by Tesseract text in skip mode); trusting `content` as the
signal (populated for scans too); rasterising the original on the OCR path (would drop
OCRmyPDF cleaning for operators who enable it — out of scope, deployment-agnostic risk).

### D3 — Three signals, whole-document decision

From the original PDF:
- **Text yield** (per page) — `pdftotext -q <file> -`. pdftotext emits a form feed (`\f`) at the
  **end of each page**, so a literal `split("\f")` yields a trailing empty segment (and any
  genuinely-textless page is its own empty segment). Do **not** naively drop trailing empties —
  that would conflate the artefact with a real textless *last* page and could wrongly skip a mixed
  document whose final page is a scan. Instead: take the page count `N` from `pdfinfo`, split on
  `\f`, and evaluate **exactly the first `N` segments** (non-whitespace char count each); a
  segment-count vs `N` mismatch → fail-safe OCR.
- **Image coverage** (per page) — `pdfimages -list` (per-image pixel dims ÷ x/y-ppi → physical
  area) ÷ page area from `pdfinfo` (`Page size: W x H pts`, pts/72 → inches). Coverage = the
  **single largest image**'s area ÷ page area, per page. **Empirically decided max over sum**
  (both measured on the 9 docs, 2026-07-21): a *clipped-sum* variant is safer against banded scans
  in theory, but it **flips Doc A** — an operator-confirmed born-digital document with an
  image-heavy page 2 — from SKIP to OCR (its largest image is 0.41, correctly < `COVERAGE`, but
  its page-2 image *sum* is **0.874**, over the line), and it compresses the born-digital-vs-scan
  margin from 0.41-vs-0.99 (max) to 0.874-vs-0.995. Max keeps the wide margin and the operator's
  ground truth. The cost is a rare residual — a *banded/strip-encoded* searchable scan whose
  strips are each < `COVERAGE` evades the ceiling — caught by the glyphless check when it is
  Tesseract-family and by the text floor when it has no real text layer; only a real-font banded
  searchable scan slips (Risk 3).
- **Glyphless font** (whole document) — `pdffonts <file>`. pdffonts has **no** "glyphless" column
  or flag; the workable detector is a **font-name match**. Tesseract-family OCR layers (Tesseract,
  OCRmyPDF, and therefore paperless-ngx itself, NAPS2) embed a font literally named
  `GlyphLessFont` — a glyphless font whose only job is to position invisible OCR text over a
  scanned image; born-digital authoring never emits it. Detection rule: a font whose name, **after
  stripping an optional `XXXXXX+` subset prefix**, equals `GlyphLessFont` (case-insensitive) →
  the document carries an OCR text layer → not born-digital. Whole-document is a deliberate choice
  (pdffonts supports `-f`/`-l` but the whole-doc skip decision needs only "any OCR-layer font
  present"). **Scope, stated honestly (correction to the operator's 2026-07-21 decision — see
  Risk 3):** this closes only the **Tesseract-family** subclass. ABBYY FineReader (ScanSnap and
  much consumer scanner software), Adobe Acrobat and Apple Vision draw their invisible OCR layer
  with **real fonts**, so they are *not* caught by the glyphless check — they fall to the coverage
  ceiling (near-always full-page for a scan) or the reserved `Tr 3` check.

Rule (whole-document): **SKIP ⟺ the document has no `GlyphLessFont` AND every page has
`chars ≥ MIN_CHARS` AND `coverage < COVERAGE`; otherwise OCR.** Three signals because each
catches a distinct class:
- the **text floor** catches pure-image scans (0 chars) and the scanned pages of a mixed
  document (Doc F/Doc G, and the scan pages of Doc H/Doc I);
- the **coverage ceiling** catches *searchable scans* whose scanned image fills the page (text
  present **and** a single full-page raster), while `coverage < COVERAGE` spares a born-digital document
  with a *partial* embedded image (Doc A at 0.41);
- the **glyphless check** catches Tesseract-family searchable scans that evade coverage — a
  foreign scan with an *inset/margined* image (< `COVERAGE`) whose baked Tesseract/OCRmyPDF text
  would otherwise pass both other gates (operator's decision, 2026-07-21: close this subclass in
  v1). No threshold; near-zero false positives (born-digital never carries `GlyphLessFont`).

Whole-document: any failing page (or a `GlyphLessFont` anywhere) sends the whole document to OCR.
**Rejected:** text-yield only (cannot catch searchable scans — the operator's explicit
requirement); size-based image gate ("any big raster") — taxes branded/watermarked/letterhead
docs whose logos are partial, the advisor's rejected form; per-page routing (deferred, see D8);
**clipped-sum coverage** (safer against banded scans in theory, but empirically flips Doc A — a
confirmed born-digital doc — to OCR and compresses the margin; see the coverage bullet).

Reserved (not implemented): the invisible text-render-mode (`Tr 3`) discriminator — needs
content-stream parsing. It is the general form that would also catch **real-font** OCR layers
(ABBYY/Acrobat/Apple), the class the glyphless check does *not* close. Kept as the escalation
path if an inset real-font searchable scan ever appears.

### D4 — Thresholds: `MIN_CHARS` configurable (default 50), `COVERAGE` hardcoded (0.85)

`OCR_BORN_DIGITAL_MIN_CHARS` is a config key (default **50**), because "how much extractable
text counts as a real text layer" is the more deployment-variable knob and the operator asked
to expose it. It is validated `≥ 1` (via `_require_at_least_one`, which **raises** on `< 1`) so
it cannot be set to 0. (0 would disable only the text floor — the coverage ceiling still gates —
not literally skip everything; the validation is belt-and-braces.) `COVERAGE` is a **hardcoded
constant = 0.85** in the detection
module — the wide **max-coverage** margin measured 2026-07-21 (born-digital ≤ 0.41 vs scans
≥ 0.99, the shipped formula per D3) supports hardcoding: 0.85 sits in dead space with no plausible
tuning need, and a config key for a value with one correct setting is an overengineering smell.
**Rejected:** exposing `COVERAGE` as a fourth key (no tuning need shown by the data);
hardcoding `MIN_CHARS` (operator asked for it in the UI, and it is the more variable of the
two). Threshold semantics: `MIN_CHARS` is a per-page floor separating "has a text layer" from
"none"; it is not a "useful amount of text" gate.

### D5 — Skip action: tags-only PATCH, trust ngx content, empty-content guard, optional marker tag

On SKIP: advance `PRE_TAG_ID`→`POST_TAG_ID` via a **tags-only** PATCH
(`update_document_metadata`), reusing `clean_pipeline_tags`; do **not** rewrite `content`
(paperless-ngx already holds the born-digital text). If `OCR_BORN_DIGITAL_TAG_ID` is configured,
add it to the tag set in the same PATCH. **Guard:** if the document's ngx `content` is empty
(extraction anomaly), do **not** skip → fall through to OCR, so a document can never reach the
classifier with no text. The skip write **reuses the existing quarantine primitives**
(`finalise_document_with_error`, `is_permanent_paperless_error`, `PAPERLESS_CALL_EXCEPTIONS`):
transient → re-raise for retry; permanent 4xx → quarantine. The skip-PATCH try/except *wiring*
is new (the OCR path's try/except is inline around `_update_paperless_document` and cannot be
shared literally) but small. **A successful skip returns `None`** — the neutral write-back
outcome, leaving the circuit breaker untouched (a skip spends no LLM tokens, so there is no
failure streak to protect); a *failed* skip PATCH still quarantines (permanent 4xx →
`WriteBackOutcome.QUARANTINED` → the breaker records it), so the breaker is never blinded.
Downstream is unchanged: the
classifier picks the document up via `CLASSIFY_PRE_TAG_ID` (=POST) and its **headerless**
truncation path (`truncate_content_by_pages` → `truncate_content_by_chars(content,
CLASSIFY_HEADERLESS_CHAR_LIMIT)` when `PAGE_HEADER_RE` finds no `--- Page N ---` headers)
handles content without OCR page headers; the indexer indexes the text. A skipped document is
indistinguishable downstream and gets *pristine* text for classification. **One accepted delta:**
an OCR'd document is sampled head+tail-pages by the classifier (`CLASSIFY_TAIL_PAGES`, via the
`--- Page N ---` path), whereas a skipped document takes the flat headerless first-`CLASSIFY_HEADERLESS_CHAR_LIMIT`
cut (no tail) — a long born-digital document loses its trailing pages from the *classifier's*
view only (the full text is still indexed and searchable). Quality-only, uses pre-existing
machinery, accepted.
**Rejected:** writing our own `pdftotext` extraction on skip (a larger PATCH, a second source
of truth vs ngx, no benefit when ngx content is present); adding `--- Page N ---` headers to
match OCR output (the classifier's headerless path already handles it).

### D6 — Fail-safe: every doubt → OCR

The gate degrades to today's behaviour (AI OCR) on any of: `mime_type`/content-type not PDF;
original fetch fails; `pdftotext`/`pdfinfo`/`pdfimages`/`pdffonts` non-zero exit, timeout, or
unparseable output; encrypted/corrupt PDF; a poppler binary missing on `PATH` (log a warning once); ngx
`content` empty (D5 guard). This honours the operator's priority — never wrongly skip a scan —
and means the feature can only ever *reduce* work, never break a document that OCR handles
today. Probe subprocesses carry a **short dedicated timeout** (`PROBE_TIMEOUT`, ~30s — not
`REQUEST_TIMEOUT`'s 180s, which across four sequential probes would let a pathological/corrupt
PDF block a document worker for ~720s before the fail-safe fires; poppler text/info extraction
is sub-second on normal input) and a **hard stdout cap** (`PROBE_MAX_OUTPUT_BYTES`, e.g. 32 MiB):
each probe's stdout is read only up to the cap and a probe that would exceed it is treated as a
failure → OCR. This is load-bearing, not a platitude — `subprocess.run(capture_output=True)`
buffers stdout **unbounded**, so without an explicit cap a decompression-bomb PDF can make
`pdftotext` emit hundreds of MB well inside `PROBE_TIMEOUT`; the cap (not the timeout) is the
decompression-bomb defence.

### D7 — Config surface: three keys, all in the Settings UI, feature default ON

| Key | Type / control | Default | Settings section |
|---|---|---|---|
| `OCR_SKIP_BORN_DIGITAL` | `bool` / toggle | **ON** (`True`) | OCR |
| `OCR_BORN_DIGITAL_MIN_CHARS` | `int` (≥1) / number | **50** | OCR |
| `OCR_BORN_DIGITAL_TAG_ID` | `int \| None` / number | **unset** (`None`) | Tags |

Backend: add all three to `CONFIG_KEYS`; add `Settings` fields with parsing —
`_get_bool_env(..., default=True)`, `_require_at_least_one("OCR_BORN_DIGITAL_MIN_CHARS",
_get_int_env(..., 50))`, and `_get_optional_positive_int_env(..., "OCR_BORN_DIGITAL_TAG_ID")`
(mirrors `OCR_PROCESSING_TAG_ID`). Frontend: add two `SettingsField` rows to the OCR section
and one to the Tags section of `sections.ts` (toggle + two numbers; existing control kinds).
Default **ON** is the operator's explicit choice for the public code default; a behaviour
change for downstream upgraders, mitigated by loud decision-logging, the master switch, and a
release note (see Rollout — no CHANGELOG file exists yet). **Rejected:** default OFF + opt-in
(operator chose ON); env-var-only (operator manages config in the UI).

### D8 — Whole-document granularity (per-page deferred to v2)

A document is skipped only if *every* page is born-digital; one scanned page → OCR the whole
document (Doc I, Doc H in the probe). Per-page routing (OCR only the scanned pages of a mixed
PDF) is a real future optimisation but a large complexity jump (partial-document assembly,
per-page tag/state) with no present requirement. **Rejected:** per-page in v1 (scope);
skip-if-any-page-born-digital (would skip documents with scanned content — unsafe).

### D9 — Poppler via subprocess, no new dependency

Detection shells out to `pdftotext` / `pdfinfo` / `pdfimages` / `pdffonts` — the same poppler-utils
suite `pdf2image` already shells to (`pdftoppm`), present in the Dockerfile (build + runtime) and
confirmed in the running image. Same trust boundary as today (untrusted PDF bytes → poppler),
mitigated the same way: write bytes to a temp file with guaranteed cleanup, a short per-probe
subprocess timeout (`PROBE_TIMEOUT`), and a hard stdout cap (`PROBE_MAX_OUTPUT_BYTES`, D6). The
detection logic lives in a new isolated module
`src/ocr/born_digital.py` — a pure `bytes → decision + signals` function, unit-testable
without the network, importing `common` only (respects the `ocr` layering boundary).
**Rejected:** adding `pypdf`/`pdfminer.six` (a new dependency for what poppler already does);
in-process rendering (heavier, no benefit).

### D10 — `mime_type` short-circuit

If the document's ngx `mime_type` (already in the fetched JSON) is a non-PDF type, the gate skips
the original fetch entirely and goes straight to OCR (an image upload is always a scan) — saving a
download per image-scan document. `mime_type` is an **optimisation, not the gate**: when it is
absent or unknown (an older ngx that doesn't serve the field), the gate does **not** no-op — it
fetches the original and decides PDF-ness from the download's `Content-Type` (the true gate;
`download_original` returns it), so the feature still works, just without the short-circuit
saving. A non-PDF discovered at that point still falls to OCR via D6.

### D11 — Left alone, deliberately

- **The Flex / patient-429 path (prior spec `20260715-flex-and-56-models.md` D5)** — untouched.
  The born-digital gate runs *before* any LLM call, so a skip never reaches the flex retry
  loop; the OCR path (when not skipped) keeps its exact current behaviour, including the
  shutdown carve-out and circuit breaker.
- **Embeddings, the classifier, the indexer, search** — untouched (a skipped document flows
  through them exactly as an AI-OCR'd one does).
- **The archive-download OCR path** — unchanged (D2); only a new *additional* original fetch
  for detection is introduced.

## Non-goals (explicitly out of scope)

1. **Per-page OCR of mixed documents** — v2 (D8). A mostly-digital document with one scanned
   page is fully OCR'd.
2. **Retroactive sweep** — the feature affects only documents entering the pipeline after
   deploy; the existing archive (already past POST) is not re-evaluated.
3. **Quality-judging an existing text layer** — a born-digital PDF with genuinely bad
   embedded text (mangled CID fonts, scrambled reading order) is skipped (philosophy A skips on
   presence, not quality). Over-OCR on genuine doubt (full-page-background born-digital PDFs,
   un-extractable fonts) is accepted as the safe direction.
4. **Dashboard metric of skips saved** — per-document decision logging only; an aggregate
   heartbeat counter is a fast-follow.
5. **Rescuing `.txt`/`.docx`** that currently fail image conversion — out of scope; PDF only.

## Touch points

Python (`src/`):
- `ocr/born_digital.py` — **new module.** `classify_original(data: bytes, *, min_chars: int,
  coverage_threshold: float, timeout: float) -> BornDigitalDecision` (decision enum + measured
  signals for logging). `COVERAGE_THRESHOLD = 0.85`, `PROBE_TIMEOUT = 30` (seconds),
  `PROBE_MAX_OUTPUT_BYTES = 32 * 1024 * 1024` constants. Poppler subprocess wrappers
  (`pdftotext`/`pdfinfo`/`pdfimages`/`pdffonts`) with temp-file lifecycle, per-probe timeout,
  a hard stdout cap (`PROBE_MAX_OUTPUT_BYTES`), and parse guards (the `\f` page-segmentation of
  D3, the `GlyphLessFont` subset-prefix-stripped name match of D3); any failure → "needs OCR".
- `ocr/worker.py` — `OcrProcessor.process()`: the gate branch after `claim_processing_tag`,
  before `_download_and_convert` — `mime_type` short-circuit (D10), original fetch (D2),
  `classify_original`, and on SKIP the tags-only advance (D5) with the optional marker tag,
  reusing the quarantine primitives (the skip-PATCH try/except wiring is new — D5); returns the
  breaker-neutral `None`; loud structured decision log.
- `common/paperless.py` — new `download_original(doc_id) -> tuple[bytes, str]` (mirrors
  `download_content`, `?original=true`).
- `common/config/_catalogue.py` — three keys into `CONFIG_KEYS`.
- `common/config/_settings.py` — three `Settings` fields (`OCR_SKIP_BORN_DIGITAL: bool`,
  `OCR_BORN_DIGITAL_MIN_CHARS: int`, `OCR_BORN_DIGITAL_TAG_ID: int | None`) + parsing/defaults
  (D7).

Web (`web/src/features/settings/`):
- `fieldModel/sections.ts` — OCR-section toggle + number rows for `OCR_SKIP_BORN_DIGITAL` /
  `OCR_BORN_DIGITAL_MIN_CHARS`; Tags-section number row for `OCR_BORN_DIGITAL_TAG_ID`.

KB / docs (`.claude/` + human docs):
- `.claude/DECISIONS.md` — entry citing this spec.
- KB docs (`docs/PIPELINES.md`, `docs/modules/ocr.md`, `docs/CONFIGURATION.md`) reconciled at
  push by kb-updater (diff mode).
- Human doc `docs/ocr-pipeline.md` states "OCR everything tagged" — now wrong. **Flag for the
  operator** (human doc — not edited without go-ahead): update its selection-rules section +
  Mermaid flow to include the born-digital gate.

## Testing requirements

A fix/feature without a failing-first test is an assertion. Regression tests ship in the branch.

- **Detection module (`born_digital.py`), synthetic fixtures per structural class** —
  born-digital text PDF (real fonts, no glyphless → SKIP), born-digital + partial image
  (< COVERAGE → SKIP), pure-image scan (0 text, full-page image → OCR), searchable scan with a
  **full-page** image (text + coverage ≥ COVERAGE → OCR via coverage), searchable scan with an
  **inset** image + a **glyphless** OCR layer named `GlyphLessFont` (text present, coverage <
  COVERAGE → OCR via the glyphless check, *not* coverage — the Tesseract-family class the operator
  chose to close), a glyphless layer carrying a **subset prefix** (`ABCDEF+GlyphLessFont` → still
  detected, guards the prefix-strip), a **banded** Tesseract searchable scan (page split into
  sub-`COVERAGE` image strips **plus** a `GlyphLessFont` layer → OCR via the glyphless check,
  since largest-image coverage alone would miss it — pins the accepted-residual boundary), an
  **image-heavy born-digital page** (one ~0.4-coverage image plus smaller images that *sum* past
  `COVERAGE`, real fonts, no glyphless → **SKIP** — pins the Doc A case and locks the max-coverage
  formula against a max→sum regression), and mixed with the **textless scan page placed LAST**
  (guards the trailing-`\f` segmentation trap — must OCR, not skip). Assert the verdict for each;
  assert a born-digital doc reports **no**
  `GlyphLessFont`; assert the first-`N`-segments text-yield rule (a born-digital doc's trailing
  `\f` does not create a phantom 0-char page that blocks every skip). **Real operator documents are
  PII and are never committed** — fixtures reproduce the *structure* (generated PDFs), not the
  content. The 9-doc validation is the design evidence, recorded here, not a committed fixture.
- **Fail-safe (D6)** — non-PDF mime → OCR without fetching original; **`mime_type` absent/unknown
  → the original IS fetched and PDF-ness taken from the download `Content-Type` (D10); a non-PDF
  Content-Type there → OCR** (no silent no-op); `pdftotext`/`pdfinfo`/`pdfimages`/`pdffonts`
  failure/timeout/garbage → OCR (each probe, **including `pdffonts`**); a probe emitting >
  `PROBE_MAX_OUTPUT_BYTES` → OCR; encrypted/corrupt PDF → OCR; missing poppler binary → OCR + one
  warning; empty ngx content on an otherwise-born-digital PDF → OCR (D5 guard).
- **Thresholds** — a page at `MIN_CHARS-1` fails, at `MIN_CHARS` passes; per-page **largest-image**
  coverage at 0.86 fails, 0.84 passes; whole-document rule (one failing page, or a `GlyphLessFont`
  anywhere → OCR).
- **Skip action (`worker.py`)** — SKIP does a tags-only PATCH (PRE→POST, no content rewrite),
  adds the marker tag only when configured, releases the processing tag, records the right
  write-back outcome; a permanent 4xx on the skip PATCH quarantines; a transient error re-raises.
- **Config** — `OCR_SKIP_BORN_DIGITAL` default `True`; `OCR_BORN_DIGITAL_MIN_CHARS` default 50
  and rejects 0 (`_require_at_least_one`); `OCR_BORN_DIGITAL_TAG_ID` default `None` and parses a
  positive int; all three in `CONFIG_KEYS`. **The key-universe count IS pinned** —
  `tests/unit/common/test_config.py` asserts `len(CONFIG_KEYS) == 87`; update it to **90** (and
  the accompanying docstring).
- **Web** — pin the three new `SettingsField`s present in the right sections with the right
  control kinds (toggle / number / number).

## Rollout

Branch `feat/born-digital-ocr-skip` → PR referencing this spec → **operator merges** → the
merge triggers the standard image build + auto-update deploy. Code default `ON` applies
where the config table has no stored value, so the gate is live on first deploy; the operator
can flip `OCR_SKIP_BORN_DIGITAL` off in the UI to revert instantly, and set
`OCR_BORN_DIGITAL_TAG_ID` to audit skips in paperless. **No CHANGELOG file exists** — record the
default-ON behaviour change in the PR description and `DECISIONS.md`; recommend (ask the
operator) a short note in the README config section, a human doc. **Post-deploy acceptance:**
re-run `scratchpad/probe.py` (computing the **shipped max-coverage** formula, not the sum variant)
against the live instance (not committed) and spot-check the `OCR_BORN_DIGITAL_TAG_ID` filter in
paperless; confirm the decision log shows born-digital documents skipping and scans OCR-ing. The
9-doc set was re-measured 2026-07-21 under both max and clipped-sum coverage; max reproduces the
operator-confirmed 9/9 (all report `glyphless: false`, so signal 3 fired no false positives),
while sum flips Doc A — the recorded reason for D3's max choice.

## Open risks

1. **Per-page `Page size` variance** — `pdfinfo` reports one page size; a document with mixed
   page dimensions makes coverage approximate. Low risk (uniform in all 9 samples); if it
   bites, compute per-page size via `pdfinfo -f/-l`. Fail-safe covers a bad parse.
2. **`pdftotext`/`pdfimages -list`/`pdffonts` output format across poppler versions** — parsed by
   whitespace/name with fixed rules (validated on the image's poppler; `pdffonts` in particular
   was never exercised by a *positive* sample in the probe — the 9 scan originals had 0 fonts).
   Pin with fixture tests (incl. a `GlyphLessFont` and a subset-prefixed one); a parse failure
   fails safe to OCR.
3. **Searchable scans — Tesseract-family subclass closed by the glyphless check; a real-font
   subclass remains (honest scope; correction re-presented to the operator 2026-07-21).** The
   coverage ceiling catches searchable scans whose image fills ≥ `COVERAGE` of the page (near-all
   scans). The `GlyphLessFont` check (D3) additionally closes **Tesseract-family** producers with
   an *inset* image — Tesseract, OCRmyPDF, and therefore **paperless-ngx's own OCR**, plus NAPS2 —
   the dominant producers. **Remaining residual:** a searchable scan from a **real-font** OCR
   producer (ABBYY FineReader / ScanSnap, Adobe Acrobat, Apple Vision — these draw the invisible
   layer with real fonts, so `GlyphLessFont` does not fire) **and** an inset image (< `COVERAGE`)
   would still be wrongly skipped. A second, even rarer slice of the same residual: a **banded**
   searchable scan (page tiled into image strips each < `COVERAGE`, so max-coverage doesn't fire)
   whose OCR layer is *also* real-font (a Tesseract-family banded scan is caught by the glyphless
   check; a textless one by the char floor). Both are narrower than "all searchable scans" and
   never hit by the operator's own (pure-image) scanner; consequence is quality-only, never
   breakage. The reserved invisible-text-render-mode (`Tr 3`) check (D3) is the general-form
   escalation that would close both real-font slices if they ever appear.
4. **`MIN_CHARS=50` and sparse born-digital pages** — a legitimate near-blank born-digital page
   (e.g. a section divider with < 50 chars) sends its whole document to OCR (safe over-OCR).
   Tunable via the exposed key.
