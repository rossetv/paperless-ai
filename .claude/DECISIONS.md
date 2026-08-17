# Decisions

<!-- Claude-maintained, append-only. Entries are never edited or deleted; a
reversal gets a new dated entry that names what it supersedes. Every entry
starts with a heading of the form:

    ## YYYY-MM-DD — <short decision title>

kb-context.sh extracts titles by that pattern — this format and that script
are a coupled contract; change them only together, in the CLAUDE repo.

Entry body shape (Spec/Affects/Supersedes lines only when applicable):

    **Decision:** <what was decided>
    **Why:** <the reason — trade-offs considered>
    **Spec:** .claude/specs/<file>.md
    **Affects:** <KB doc paths this decision touches, comma-separated>
    **Supersedes:** <date/title of the earlier entry, only if a reversal>

Delete nothing above when appending; append new entries at the end of file. -->

## 2026-07-15 — Adopt GPT-5.6, refresh reasoning efforts, add Flex tier

**Decision:** OpenAI defaults move to gpt-5.6-luna/terra (Sol selectable,
never default); reasoning-effort choices become the live-verified {none, low,
medium, high, xhigh}, with stored "minimal" coerced to "none"; OCR +
classifier run on the Flex service tier behind `OPENAI_FLEX_TIER` (default
on) with retry-until-done capacity-429 semantics; every OpenAI call names its
`service_tier` explicitly. Batch API, the Responses API migration, and any
embedding change are rejected for now.
**Why:** "max" is excluded from the reasoning-effort set — the docs list it
but the live API rejects it. Batch/Responses/embedding changes were weighed
and rejected — see spec sections D3/D10 for the trade-offs considered.
**Spec:** `.claude/specs/20260715-flex-and-56-models.md`
**Affects:** common/config, common/llm, ocr, classifier, search, web settings

## 2026-07-15 — Remove GATES.md's fulfilled reconciliation note

**Decision:** Delete the three-line note in `GATES.md` stating gates 9/10 were not yet
documented in `TESTING.md` — the same commit documents them there, fulfilling the note.
**Why:** The note was a self-scheduled reminder, not a gate; once fulfilled it would lie.
No gate row was removed or edited — the 10-gate table is untouched. Approved by: human
(operator, 2026-07-15), per the gate's removal-needs-a-record rule.
**Affects:** `.claude/GATES.md`, `.claude/docs/TESTING.md`

## 2026-07-15 — Migrate GATES.md to the canonical stanza grammar

**Decision:** Rewrite `GATES.md` from the ad-hoc table format (authored earlier today)
into the canonical stanza grammar from the config repo's `templates/kb/GATES.md` —
`### gate: <id>` stanzas with kind/why/added/mandated-by-human fields and fenced
commands, plus the template's standard anti-cheat and change-control sections.
**Why:** The kb-gate's push-time validator parses only the canonical grammar; the table
format read as "no gates declared" and blocked every push. All ten commands are
unchanged — this is a format migration, not a gate change. Approved by: human
(operator, 2026-07-15 — "approved", in response to the explicit rewrite proposal).
**Affects:** `.claude/GATES.md`

## 2026-07-15 — Correct the LLM-budget claim in CODE_GUIDELINES.md

**Decision:** Amend §14.3 and §10.6 — the "three LLM calls per query" ceiling becomes the
real formula `(2 + j) × (1 + SEARCH_MAX_REFINEMENTS)`, six at shipped defaults, citing
`search/core._max_llm_calls`.
**Why:** The judge gate plus the refinement loop made "three" false long before this
branch; the corrected code docstrings cross-referenced §14.3 and sent readers to the lie.
Human-owned law, edited only on explicit operator instruction: "You are allowed to edit
the CODE_GUIDELINES.md to fix this" (2026-07-15).
**Affects:** `CODE_GUIDELINES.md` §14.3, §10.6

## 2026-07-21 — Skip AI OCR on born-digital PDFs
**Decision:** A deterministic poppler gate in the OCR worker skips vision-OCR for PDFs that
are already born-digital — detected on the *original* file (`pdftotext` per-page text yield +
`pdfimages` largest-image page-coverage + `pdffonts` `GlyphLessFont`) — while AI-OCRing scans,
images and scanner-produced searchable scans. Default on, whole-document, three settings-UI
config keys (`OCR_SKIP_BORN_DIGITAL`, `OCR_BORN_DIGITAL_MIN_CHARS`, `OCR_BORN_DIGITAL_TAG_ID`),
fail-safe to OCR on any doubt. A skip is a tags-only `PRE→POST` PATCH (content untouched),
breaker-neutral; a permanent write failure quarantines.
**Why:** The daemon re-OCR'd every tagged document, burning vision tokens on born-digital PDFs
that already carry a perfect text layer. Coverage uses the largest image (not the sum) because
a clipped-sum variant flips an operator-confirmed born-digital doc (image-heavy page) to OCR;
`GlyphLessFont` closes the Tesseract-family searchable-scan subclass. Every failure mode is
quality-only (falls through to OCR), never data loss — which is what makes default-on safe.
Empirically validated 9/9 against real documents on the operator's instance.
**Spec:** .claude/specs/20260721-born-digital-ocr-skip.md
**Affects:** `docs/PIPELINES.md`, `docs/modules/ocr.md`, `docs/CONFIGURATION.md`

## 2026-08-15 — Born-digital gate: text floor default 1, blank pages exempt
**Decision:** `OCR_BORN_DIGITAL_MIN_CHARS` default 50 → 1, and the per-page text floor now applies
only to a page that also carries a raster (`pdfimages` row, ppi 0 included) — a textless, imageless
page is a blank verso, a divider or (rarely) a vector-outline page — not a scan. Whole-document rule, `COVERAGE`, tags-only skip and the
exposed key are unchanged.
**Why:** The first real booklet (prod doc 1525, 59 pages) went through 59 vision calls because its
cover page held 44 chars + a logo — one under the shipped floor. The 9-doc calibration set had no
sparse born-digital page, so 50 sat in a gap with no low-side data and contradicted D4's own "has a
text layer vs none" semantics; a blank page is unfixable by tuning at any floor ≥ 1. Rejected:
intermediate defaults (arbitrary, fail folio-only versos), a new sparse-page image threshold (no
data), per-page routing (D8 v2 — its own spec; 0 mixed docs in the census). Operator: "so should
we do your initial recommendation 1 and 2?" → "do it. commit directly to main, small change, then
push." (2026-08-15).
Follow-ups landed in the same push on explicit operator instruction ("fix the human doc. also fix
the follow-up defect found", 2026-08-15): the human doc `docs/ocr-pipeline.md` corrected (default,
raster condition, honest residual — human-owned prose, edited only on that instruction), and
`_parse_max_coverage` now reads the ppi columns from the right so inline images (`[inline]`, one
token) no longer fail the whole gate closed.
**Spec:** .claude/specs/20260721-born-digital-ocr-skip.md (*Amendments*, 2026-08-15)
**Affects:** `src/ocr/born_digital.py`, `src/common/config/_settings.py`, `web/src/features/settings/fieldModel/sections.ts` (hint copy), `docs/ocr-pipeline.md`

## 2026-08-17 — Born-digital gate: a mangled text layer routes to OCR
**Decision:** the gate gains a fourth signal from the `pdftotext` output it already holds — a count of
`[A-Za-z];[A-Za-z]` (a semicolon glued between two letters); any hit → `mangled-text-layer`,
skip=False, logged as `mangled_hits` on every decision. Presence signals, thresholds and the
tags-only skip are unchanged; spec non-goal 3 is narrowed by exactly this one structural tell.
**Why:** prod doc 1523 (an Outlook-for-Mac print-to-PDF, macOS Quartz PDFContext, Calibri/Aptos)
passed every presence signal and was skipped, keeping ngx content in which every `ti`/`tt`/`ft`/`ffi`
ligature had become `;`/`5`/`C`/`m` (`mee;ng`, `le5er`, `draC`, `omcer` in shape; the document's
words are private) — Quartz writes a `ToUnicode` that maps those ligature glyphs to single wrong
characters (CMap dump on the pristine original; poppler 26.03 reproduces it). Pre-gate the vision
path rasterised and was immune. Rejected: a `Producer` sniff (over-broad, producer-bound), a
`ToUnicode` collision parser (a CMap parser for one observed producer), a `5`-in-word second tell
(hex/serial false positives, no measured recall gain on n = 1), an LLM judge (D1). Known residuals
recorded in the spec: `tt`/`ft`/`ffi`-only or word-initial-`ti` mangling still skips; semicolon-
delimited data, minified CSS/JS and `;`-joined URLs over-OCR. Count uses `finditer` (a `findall`
list on the 32 MiB probe cap measured 522 MB RSS vs 48 MB — the D6 bomb budget). Census: 1 of 16
skips affected; verified on all 16 real originals after the change (1523 → OCR, 15 unchanged).
Operator: "Let's go with A. commit directly to main and push." (2026-08-17). `docs/ocr-pipeline.md`
(human doc) edited minimally under the 2026-08-15 precedent so its signal list does not lie about
the code. Adversarial review R1 (Opus): NO-SHIP on three majors — a verbatim line of the operator's
private document in the test fixture/spec/decision (redacted to synthetic examples before any
push), the `findall` amplification, and an overstated "full recall" claim — all resolved in the
same commit.
**Spec:** .claude/specs/20260721-born-digital-ocr-skip.md (*Amendments*, 2026-08-17)
**Affects:** `src/ocr/born_digital.py`, `docs/ocr-pipeline.md`

