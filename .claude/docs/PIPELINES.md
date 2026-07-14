<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../INDEX.md)

# Pipelines

The four document/query pipelines, their stages, and where each one gives up.

## Facts

### 1. OCR (`src/ocr/`)

| Stage | Detail |
|-------|--------|
| Select | `common.document_iter.iter_documents_by_pipeline_tag` over `PRE_TAG_ID`; skips non-int ids, already-done docs (stripping their stale queue tag) and docs already claimed |
| Claim | `common.claims.claim_processing_tag` (`OCR_PROCESSING_TAG_ID`) — refresh → add → re-read and verify. Best-effort, not atomic |
| Rasterise | `ocr.image_converter.open_page_source`: PDF (substring test `"pdf" in content_type.lower()`) → pdf2image/poppler `paths_only=True` into a temp dir at `size=OCR_MAX_SIDE` (fmt PNG, `dpi=OCR_DPI`, `timeout=REQUEST_TIMEOUT`); multi-frame TIFF → per-frame temp PNGs; single images in memory. Any poppler failure or undecodable bytes → `ImageConversionError` → error tag |
| Transcribe | `ThreadPoolExecutor(PAGE_WORKERS)`; per page, `unique_models(OCR_MODELS)` in order — an API error *or* a refusal advances to the next model; the whole chain failing yields `REFUSAL_MARK` |
| Assemble | `ocr.text_assembly.assemble_full_text` — blank pages skipped, `--- Page N ---` headers when >1 page, `Transcribed by model:` footer |
| Write back | `update_document` + tag swap `PRE_TAG_ID` → `POST_TAG_ID`; error/refusal → `ERROR_TAG_ID` |
| Memory bound | At most ~`PAGE_WORKERS` page bitmaps resident; pages are loaded one at a time from temp files and the temp file is deleted as it is consumed |

### 2. Classification (`src/classifier/`)

| Stage | Detail |
|-------|--------|
| Select | `CLASSIFY_PRE_TAG_ID` (defaults to `POST_TAG_ID`) |
| Divert | Pre-existing error tag → finalise & skip; empty content → re-queue for OCR; refusal/redaction content (`quality_gates.needs_error_tag`) → error tag |
| Truncate | `content_prep`: page-header slicing (head `CLASSIFY_MAX_PAGES` + `CLASSIFY_TAIL_PAGES`; no `--- Page N ---` headers ⇒ falls back to `CLASSIFY_HEADERLESS_CHAR_LIMIT`), then a hard `CLASSIFY_MAX_CHARS` ceiling — always preserving the `Transcribed by model:` footer |
| Prompt | Stable prefix (tag-limit guidance + the three taxonomy lists) then the variable suffix (truncation note + nonce-fenced document text). The prefix is byte-identical across a batch (it interpolates only `CLASSIFY_TAG_LIMIT` and the taxonomy snapshot), for OpenAI prompt caching |
| Parse | `result.parse_classification_response` — coerces string `tags`, nulls and non-string scalars to safe values |
| Gate | `is_empty_classification` or a generic/empty `document_type` ⇒ error-tag (returns `None`, so the circuit breaker is untouched) |
| Tags | dedupe → blacklist (`{ai, error, indexed, new}`) → drop tags equal to correspondent/type/person → **required** tags (OCR model tags, year tag, `CLASSIFY_DEFAULT_COUNTRY_TAG`) always added and never counted against `CLASSIFY_TAG_LIMIT`; optional LLM tags trimmed. Everything lowercased |
| Resolve | `TaxonomyCache` (RLock) — normalised lookup, POST-create on miss, post-create re-check. Correspondents match by substring; types and tags exactly |
| Write back | `update_document_metadata` + tag swap |

### 3. Indexing (`src/indexer/` → `src/store/`)

| Stage | Detail |
|-------|--------|
| Cycle | hot-reload config (`current_settings`) → consume `reconcile.request` (forces a sweep) and `rebuild.request` (wipes the index first) → incremental sync (which refreshes the taxonomy before any document work) → deletion sweep when due (`DELETION_SWEEP_INTERVAL`) or manually triggered → `checkpoint()` → interruptible wait (`RECONCILE_INTERVAL`). The whole body is inside one `try/except Exception`: a failed cycle never advances the sweep clock and never kills the daemon |
| Sync (cold) | Watermark `None` ⇒ full-document backfill, streamed lazily in batches of 100 (`_batched`) — peak memory is O(one batch), never O(archive) |
| Sync (steady) | Watermark set ⇒ sparse `{id, modified}` projection; a row whose normalised `modified` equals the stored value is skipped without fetching its body; only genuinely-changed ids are fetched in full |
| Per document | Content gate (empty/whitespace or `ERROR_TAG_ID` ⇒ SKIPPED, pruning any existing row) → SHA-256 hash gate (unchanged ⇒ `update_metadata`, METADATA_ONLY) → `chunk_text` → `EmbeddingClient.embed` → `upsert_document` (INDEXED). Zero chunks ⇒ refuse to upsert |
| Chunking | Paragraph-aware windows of `CHUNK_SIZE` with `CHUNK_OVERLAP`, page hints from `--- Page N ---`, then a hard 6000-char cap per chunk so dense CJK cannot blow the 8191-token embedding limit |
| Watermark | Advances to `max(modified on the page) - OVERLAP_MARGIN` (10 s) whenever the page held any document — **unconditionally on failures**. Failures live in a persisted `failed_documents` map instead, retried out of band, dead-lettered at 5 consecutive failures |
| Sweep | Full Paperless id enumeration; **any** enumeration failure prunes nothing; each candidate is 404-confirmed individually |

### 4. Search (`src/search/core.py`)

| Layer / stage | Detail |
|---------------|--------|
| Layer 0 | Degenerate-input guard: a query shorter than `SEARCH_MIN_QUERY_CHARS` (after stripping) returns clarify with **zero** LLM calls. Applies to `answer()` and `retrieve()` alike |
| Plan (LLM 1) | `QueryPlanner.plan` → `RetrievalPlan` (≥1 spec, always) or `ClarifyNeeded`. Fail-open: any malformed/failed response degrades to a broad semantic plan and can never become a false clarify. `SEARCH_SKIP_PLANNER_FOR_TRIVIAL` bypasses it (and, with it, the adequacy gate) |
| Resolve | `retriever.resolve_specs` — filter guesses → taxonomy ids + ISO dates; an ambiguous or near-miss name resolves to **no** filter, never a guessed id; a deterministic date safety net and unfiltered recall-twins are added |
| Retrieve | One batched embedding call for all semantic specs; per-spec vector (`vec_distance_cosine` KNN) + FTS5 bm25; RRF fusion (`k = 60`); top-K documents by best chunk, capped chunks per document. Filters are applied as a WHERE on `documents` **before** ranking |
| Layer 2 (gate) | Only when `SEARCH_GATE_RELEVANCE` is on, and only in `answer()` (never `retrieve()`). Conservative and fail-open: reject only when the best vector similarity is *known*, below `SEARCH_RELEVANCE_MIN_SIMILARITY`, and there is no keyword hit |
| Layer 3 (LLM 2, judge) | One verdict per candidate document; recall-biased, fail-open (a failure keeps everything, `degraded=True`). `keep` is the gate; `score` only ranks sources |
| Synthesise (LLM 3) | `exploratory` mode may return `NeedsMore`; the last allowed pass runs in `final` mode, which coerces to `Answered`. Chunk text is nonce-fenced in the user message |
| Refine | Up to `SEARCH_MAX_REFINEMENTS` passes (re-plan → re-retrieve → re-judge → re-synthesise). A re-plan that produces an equivalent spec set is a no-op and skipped; a re-plan's `ClarifyNeeded` is ignored |
| Budget | `2 + j + R*(2 + j)` chat calls (`j` = 1 iff `SEARCH_GATE_JUDGE`, `R` = `SEARCH_MAX_REFINEMENTS`); breaching it raises `LlmBudgetExceededError` |
| Cache | TTL result cache (`SEARCH_CACHE_TTL_SECONDS`, 512 entries), keyed on (normalised query, filters, index version, asker). The final-mode fallback sentinel is never cached |

## Procedures

1. **Re-run one document through OCR / classification** — `POST /api/documents/{id}/retranscribe` or `/reclassify` (tag swap; the daemon picks it up next poll).
2. **Re-index everything** — `POST /api/index/rebuild` (admin) or change a `REINDEX_KEYS` setting.
3. **Trace a search** — use `POST /api/search/stream` and read the `phase_start`/`phase_done` frames, or `stats.trace` on `POST /api/search`.

## Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| A wholly blank document is error-tagged | `assemble_full_text` yields `""` ⇒ the "no text" error path, not success | Expected behaviour |
| Page headers skip numbers (Page 1, Page 3) | A blank page emits no section at all; the header number is still the true page index (`enumerate(page_results, 1)` over the full-length result list) | Cosmetic, by design |
| Real scans never hit the blank-page short-circuit | `is_blank` counts only pixel-perfect 255 white; a 250–254 background is not blank | Expected — only synthetic pages skip |
| A document with a genuine `[OCR ERROR]` string in its text is error-tagged | The marker is matched as a plain substring of the assembled text | Known trap |
| The classifier error-tags everything and nothing halts | Result-quality rejections return `None`, so the circuit breaker never sees them — only Paperless write failures can halt a daemon | Check the model/prompt, not the breaker |
| A "manual reconcile" did not force a deletion sweep | A sentinel that lands during the inter-cycle *wait* is consumed by the wait and its return value discarded; the next cycle sees no sentinel. The sync still runs | Known gap (`src/indexer/daemon/_loop.py:170-174`) — the periodic sweep still fires on `DELETION_SWEEP_INTERVAL` |
| A cache hit still debits an API key's quota | The cached result carries the *original* token totals, and `/api/search` records `result.cost.tokens.total` unconditionally — no cache-hit flag exists on the result to check | Known — see [modules/search-pipeline](modules/search-pipeline.md) |
| Search misses a document that exists in Paperless | It was skipped (empty content / error tag), dead-lettered after 5 failures, or the index has not reconciled since it changed | `GET /api/index/failed`, `GET /api/stats` |

## Related

- [modules/ocr](modules/ocr.md) · [modules/classifier](modules/classifier.md) · [modules/indexer](modules/indexer.md) · [modules/search-pipeline](modules/search-pipeline.md) · [modules/store](modules/store.md)
- Human docs: `docs/ocr-pipeline.md`, `docs/classification-pipeline.md`, `docs/indexer.md`, `docs/search-pipeline.md`
