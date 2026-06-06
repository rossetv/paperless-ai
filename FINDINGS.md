# OpenAI Token-Cost Audit — paperless-ai

**Date:** 2026-06-05
**Scope:** Whole repository (`src/**`, ~23k LoC), read-only. Goal: stop wasting OpenAI tokens and spend fewer tokens for equal/better results.
**Method:** Six parallel read-only sub-agents, one per subsystem (OCR, classifier, indexer+embeddings+store, search/RAG, shared LLM plumbing) plus a read-only prod ground-truth inspection over SSH. Every finding is cited to `file:line` with quoted evidence and tagged **BURN-RISK** (wastes tokens) or **OPTIMISATION** (fewer tokens for equal/better output). Linchpin claims were re-verified by the orchestrator against source.
**Prod reality (matters for prioritisation):** This is a personal/homelab-scale deployment — four containers from one image (`rossetv/paperless-ai:latest`), `DOCUMENT_WORKERS=1`, `EMBEDDING_MAX_CONCURRENT=2`, index `index.db` = **51 MiB**, taxonomy 405 entries, chunk counts 1–15/doc. Steady state is currently healthy: **no** 429s, **no** circuit-breaker trips, **no** quarantine, **no** re-embed loops observed in logs. The big risks below are therefore mostly **latent** (one incident / one mis-set knob away) plus **recurring per-item** drains — not active fires.

> **How to use this doc:** each finding has a `- [ ]` checkbox and a `Decision:` line. Tick the ones you want done and/or write your call after `Decision:`, then tell me which IDs to fix. Several IDs are the *same underlying fix* — see the **Bundle map** so you don't pay for the same work twice.

---

## 1. Ranked biggest $ wins

Ranked by expected saving × likelihood × ease. "Bundle" lists every finding ID that the one fix resolves.

| # | Win | Type | Effort | Bundle (IDs) |
|---|-----|------|--------|--------------|
| 1 | **Cut `MAX_RETRIES` 20 → 3** (and share one attempt budget across the model chain). Caps worst-case from **60 paid attempts per item → ~3**. Confirmed live in prod (unset). | BURN | 1 env var | LLM-01 · OCR-06 · CLS-04 · RAG-07 · PROD-01 |
| 2 | **OCR `detail:"high"` → configurable, default `auto`/`low`.** Paid on *every page of every document* — the single biggest recurring vision cost. ~4–8× input-token cut per page. | BURN/OPT | small code + quality check | OCR-01 · LLM-06 |
| 3 | **Move synthesiser off `gpt-5.5` (top tier) as the default primary → `gpt-5.4`**, keep 5.5 in fallback only. Most expensive model on the most expensive call, every answered query. | BURN | 1 env var | RAG-02 · PROD-02(part) |
| 4 | **Set `reasoning_effort=low`/`none`** on classify, planner and synth (thread the kwarg through the shared wrapper). Kills the invisible reasoning-token premium on every `gpt-5.4`/`5.5` call. | BURN | small code | CLS-05 · RAG-03 · LLM-04(part) |
| 5 | **Central output cap (`max_completion_tokens`) + fix the GPT-5 param-name bug.** No call path caps output today; the fallback helper *structurally can't*; the classifier's `max_tokens` may be silently stripped on `gpt-5*`. | BURN | small code | LLM-02 · OCR-02 · CLS-03 · RAG-01 |
| 6 | **Pin `EMBEDDING_MODEL` explicitly in the compose env.** It runs on the *app default* today, and **watchtower auto-update is on** — an image whose default changes would silently wipe & re-embed the whole 51 MiB index. | BURN (latent) | 1 compose line | PROD-03 · PROD-04 · IDX-04 |
| 7 | **Split fallback chains so `gpt-5.5` isn't a routine fallback for OCR/classify** (e.g. `AI_MODELS=gpt-5.4-mini,gpt-5.4`). ID/passport pages refuse on cheap tiers and escalate to 5.5 *today*. | BURN | 1 env var | LLM-04 · PROD-02 |
| 8 | **Shrink + cache the classification taxonomy.** Up to 300 names JSON-dumped into *every* classify prompt, in a cache-defeating order. Drop limit 100→~40 and put it in the static prefix. | OPT | small code + 1 env var | CLS-01 · CLS-02 · LLM-09 |
| 9 | **Bound `LLM_MAX_CONCURRENT`** (default 0/unbounded → e.g. 4). Storm mitigation; lower priority at `DOCUMENT_WORKERS=1` but a free guardrail. | BURN | 1 env var | LLM-03 |
| 10 | **Add a query/result cache (short TTL).** A byte-identical repeat query re-pays embed + plan + synth in full — there is zero caching anywhere. | BURN/OPT | moderate code | RAG-05 |
| 11 | **Cap synthesis context** (`SEARCH_TOP_K` upper bound + a context token/char budget). Synth currently stuffs *all* chunks of the top-K docs, doubled on refinement, uncapped. | BURN | small code | RAG-04 |
| 12 | **Add `OCR_MAX_PAGES` cap.** No ceiling today — a 200-page scan is 200 vision calls. | BURN | small code | LLM-05 |

Lower-tier wins (still worth doing): **RAG-06** structured outputs for planner/synth · **RAG-08** skip planner on trivial queries · **RAG-10** skip synth on weak retrieval · **IDX-02** oversized-chunk guard · **OCR-10** retry write-back in place instead of re-OCR · **IDX-01** chunk overlap 256→128 (cheap, embeddings are cheap) · **LLM-07** cache per-model compat-strip · **LLM-08** default `CLASSIFY_MAX_CHARS` · **OCR-05/CLS-08** slim prompts · **OCR-08** `OCR_MAX_SIDE` 1600→~1024 (only while on high detail).

---

## 2. What's already good — do NOT "fix" these

These are correct, load-bearing defences. Touching them risks *introducing* burn.

- **Incremental embedding genuinely works.** The embed call is gated behind a SHA-256 content-hash equality check (`indexer/worker.py:121,126`); unchanged docs take the metadata-only path and spend **zero** embedding tokens. Your #1 fear (re-embedding done work) is defended.
- **The metadata-only update path is real and wired in.** `store/writer.py:221` `update_metadata` updates title/tags/etc. and explicitly never touches `chunks`. The classifier's write-back bumps Paperless `modified`, but the hash gate means that costs an HTTP re-fetch, not re-embedding.
- **Search has a HARD, enforced LLM-call ceiling.** `_LlmBudget` raises after 3 chat calls per query (`search/core.py:88-121`) — there is no agentic loop that can run away. This is the model the rest of the app should copy.
- **Quarantine + circuit breaker stop token-burning loops.** Permanent (4xx) write-back failures error-tag and de-queue the doc (`ocr/worker.py:125-146`, `classifier/worker.py:155-171`); 3 consecutive write-back failures halt the daemon (`circuit_breaker.py:27,62-76`).
- **Preflight is free.** `_check_llm_reachable` uses `client.models.list()`, not a paid completion (`common/preflight.py:84`). No paid boot call on the tag daemons. (The indexer's one-token "ping" embed at `indexer/daemon.py:296` is boot-only and negligible — see LLM-10.)
- **Embeddings are cost-sane.** Cheapest model (`text-embedding-3-small`), `dimensions` set, batched at 96/request, bounded concurrency (`common/embeddings.py:61,120,185`).
- **Polling never re-LLMs finished work.** Tag gating skips post-tagged/processing docs (`common/document_iter.py:51-64`); a transient loop error sleeps before retry rather than tight-looping (`common/daemon_loop.py:169-182`).
- **Full re-embed cannot be triggered from a read/search/query path.** Verified: store reader has no INSERT/UPDATE/embed; rebuild is admin-gated and only writes a sentinel (`search/index_routes.py:106`).
- **Prompt structure is injection-safe** and OCR's system-prompt-first/image-last ordering is already cache-friendly (`search/prompts.py:121-171`, `ocr/provider.py:69-83`).

---

## 3. Prod ground truth (read-only SSH, secrets masked)

Live config that differs from, or confirms, the code defaults — this drives the severities above.

| Setting | Prod value | Source | Note |
|---|---|---|---|
| Image | `rossetv/paperless-ai:latest` (all 4 containers) | `docker ps` | **Watchtower auto-update enabled** on all four |
| `LLM_PROVIDER` | `openai` | env | — |
| `AI_MODELS` | `gpt-5.4-mini, gpt-5.4, gpt-5.5` | startup banner | Confirmed live (OCR + classify chain) |
| `SEARCH_ANSWER_MODEL` | `gpt-5.5` (app default) | code default | Top tier on every answer |
| `EMBEDDING_MODEL` | `text-embedding-3-small` (**app default, unset in env**) | banner | See PROD-03 |
| `MAX_RETRIES` | **unset → app default 20 live** | env absent | See LLM-01/PROD-01 |
| `LLM_MAX_CONCURRENT` | unset → app default 0 (unbounded) | env absent | See LLM-03 |
| `DOCUMENT_WORKERS` | **1** (overridden) | compose | Shrinks the concurrency-storm blast radius vs the code default of 4 |
| `PAGE_WORKERS` | 8 | banner | Up to 8 concurrent OCR vision calls/doc |
| `EMBEDDING_MAX_CONCURRENT` | 2 (overridden) | compose | — |
| `CLASSIFY_MAX_TOKENS` | unset → 0 (unbounded output) | env absent | See LLM-02/CLS-03 |
| `CLASSIFY_TAXONOMY_LIMIT` | unset → 100 (→ up to 300 names/call) | env absent | See CLS-01 |
| `OCR_DPI` / `OCR_MAX_SIDE` | 300 / 1600 | banner | — |
| `RECONCILE_INTERVAL` / `DELETION_SWEEP_INTERVAL` | 300s / 3600s | banner | Fine |
| Index size | `index.db` 51 MiB, `app.db` 0.78 MiB (+4 MiB WAL) | `du`/`ls` | Re-embed blast radius ≈ 51 MiB of vectors |

**Observed in logs:** classifier processed a 14-doc boot batch, every doc `attempts=1` on `gpt-5.4-mini` — healthy. One ID document (doc 1164) refused on `gpt-5.4-mini` **and** `gpt-5.4`, then succeeded on `gpt-5.5` after ~47 s (`refusals=2, fallback_successes=1`) — a live example of the chain escalating to the priciest tier. No 429s / breaker / quarantine / re-embed events. Indexer emits every log line **twice** (PROD-05, cosmetic). `app.db-wal` 4 MiB un-checkpointed (PROD-06, cosmetic).

---

## 4. Bundle map (same fix, multiple IDs)

| Root fix | Canonical | Also appears as |
|---|---|---|
| Retry multiplier (20 × chain) | **LLM-01** | OCR-06, CLS-04, RAG-07, PROD-01 |
| No central output-token cap (+ GPT-5 param bug) | **LLM-02** | OCR-02, CLS-03, RAG-01 |
| `reasoning_effort` never set | **CLS-05** | RAG-03, LLM-04(part) |
| `gpt-5.5` as routine fallback / synth primary | **LLM-04** | RAG-02, PROD-02 |
| Taxonomy bloat in classify prompt | **CLS-01** | CLS-02, LLM-09 |
| Watchtower + app-default embedding model → silent re-embed | **PROD-03** | PROD-04, IDX-04, LLM-11 |

Fix the canonical and the rest fall out. The per-lane entries below carry lane-specific notes worth reading.

---

## 5. Findings — Cross-cutting / LLM plumbing (`src/common`)

These are the root causes. Highest leverage: one change, every subsystem benefits.

### LLM-01 — Retry multiplier: 20 retries × 3-model chain = up to 60 paid attempts per logical call
- **Tag:** BURN-RISK · **Severity:** Critical (by blast radius; currently dormant in prod)
- **Location:** `common/config.py:528-529` (`MAX_RETRIES` default 20) · `common/retry.py:54-78` · `common/llm.py:101` (`@retry`) + `llm.py:152-167` (chain loop, each model independently retried)
- **What:** Every model in a fallback chain is retried up to `MAX_RETRIES` times, so one logical LLM op can bill `MAX_RETRIES × len(chain)` completions.
- **Why it matters ($):** `retry.py:54` loops `range(1,20)` + one final attempt = 20 attempts/model; default chain is 3 models → **up to 60 billable attempts per page/doc/query**. `RateLimitError` is retryable (`llm.py:33`), so a 429 storm self-amplifies: throttled → fire up to 60 more → deeper throttle. Each attempt on a `gpt-5.5` page carries the full (unbounded, high-detail) payload. Prod runs the default 20 (confirmed unset).
- **Evidence:** `MAX_RETRIES=_require_at_least_one("MAX_RETRIES", _get_int_env(source,"MAX_RETRIES",20))`; `models = unique_models([primary_model,*fallback_models]); for model in models: ... self._create_completion(...)`.
- **Recommended fix:** Default `MAX_RETRIES`→**3**. Better: pass a *shared* attempt budget through `_complete_with_model_fallback` so the whole chain shares ~4–5 attempts total, not 20 each. Honour `Retry-After` and give `RateLimitError` a small separate cap instead of blind exponential fan-out.
- **Confidence:** High
- `Decision:` FIX IT
- [ ]

### LLM-02 — No central output cap; fallback helper structurally can't set one; GPT-5 may reject `max_tokens`
- **Tag:** BURN-RISK · **Severity:** Critical
- **Location:** `common/llm.py:101-109` (`_create_completion` injects nothing) + `llm.py:152-155` (`_complete_with_model_fallback` passes only model+messages) · `config.py:551` (`CLASSIFY_MAX_TOKENS` default 0) · `classifier/provider.py:217-218` · `ocr/provider.py:89-93` (OCR sets none)
- **What:** No shared output ceiling. Planner/synth *cannot* pass one (helper has no such arg); OCR never does; classify defaults to 0 (omitted). Output is bounded only by the model max on most paths.
- **Why it matters ($):** Output (and reasoning) tokens are the expensive half. An unbounded completion on `gpt-5.5` can emit thousands of tokens; multiply by the LLM-01 retry fan-out. **Subtle bug:** GPT-5-series uses `max_completion_tokens`, not `max_tokens` — the classifier's `max_tokens` (provider.py:218) is liable to be rejected on `gpt-5.4-mini` and silently stripped by its compat loop, so even when set the cap may not apply to the *actual* prod models.
- **Evidence:** `def _create_completion(self,**kwargs): ... client.chat.completions.create(**kwargs)`; `completion = self._create_completion(model=model, messages=messages)`; classify only sets `max_tokens` when `>0`.
- **Recommended fix:** Inject a default in `_create_completion` (`kwargs.setdefault("max_completion_tokens", settings.LLM_MAX_OUTPUT_TOKENS)`), add explicit per-stage caps to `_complete_with_model_fallback`, and use `max_completion_tokens` for `gpt-5*`. Add `LLM_MAX_OUTPUT_TOKENS`. **Verify against the pinned SDK whether `gpt-5.x` rejects `max_tokens`** before relying on the classifier's existing cap.
- **Confidence:** High (no cap); Medium (exact GPT-5 param behaviour — needs a live API check)
- `Decision:` THIS CAN CAP OCR TRANSCRIPTIONS OF LARGE DOCUMMENTS, AND I DO NOT SEE A BENEFIT FOR THIS. DO NOT IMPLEMENT
- [ ]

### LLM-03 — `LLM_MAX_CONCURRENT` defaults to 0 (unbounded)
- **Tag:** BURN-RISK · **Severity:** Medium (High on paper; reduced by prod `DOCUMENT_WORKERS=1`)
- **Location:** `config.py:536` · `common/concurrency.py:60-67,121-127`
- **What:** No ceiling on simultaneous in-flight billable calls; the enforcement path exists and is wired, only the default is wrong.
- **Why it matters ($):** Unbounded concurrency provokes `RateLimitError`, which (retryable) triggers the LLM-01 fan-out across many threads at once. On paper OCR could run `PAGE_WORKERS=8 × DOCUMENT_WORKERS=4 = 32` concurrent vision calls/process; **prod runs `DOCUMENT_WORKERS=1`** so the real OCR ceiling is ~8 and classify ~1 — so this is latent, not active. Still a free guardrail.
- **Evidence:** `LLM_MAX_CONCURRENT=max(0,_get_int_env(source,"LLM_MAX_CONCURRENT",0))`; `if self._semaphore is None: yield; return`.
- **Recommended fix:** Default to a non-zero bound (4–8). One-line change with existing enforcement.
- **Confidence:** High
- `Decision:` FIX IT.
- [ ]

### LLM-04 — Fallback chain escalates to the most expensive tier (`gpt-5.5`) for mechanical, high-volume work
- **Tag:** BURN-RISK · **Severity:** High
- **Location:** `config.py:474` (chain) + `:476` (`SEARCH_ANSWER_MODEL=gpt-5.5`) · consumed `ocr/provider.py:85`, `classifier/provider.py:144`, `synthesizer.py:138`
- **What:** The shared `AI_MODELS` chain ramps mini→mid→**flagship**, and is the fallback for OCR, classify *and* search. Any refusal/error on the cheap tiers pulls in a `gpt-5.5` call.
- **Why it matters ($):** The flagship sits in the routine fallback for OCR transcription and field extraction, where a mini model almost always suffices. Prod *already* escalates ID/passport pages to `gpt-5.5` on privacy refusals (doc 1164). And `SEARCH_ANSWER_MODEL=gpt-5.5` starts at flagship *and* falls back through the chain. Recent commit `768b05e` retuned tiers but left the flagship in the mechanical chains.
- **Evidence:** `default_ai_models = ["gpt-5.4-mini","gpt-5.4","gpt-5.5"]`; `default_answer_model = "gpt-5.5"`; OCR `models_to_try = unique_models(self.settings.AI_MODELS)`.
- **Recommended fix:** Per-stage chains: OCR/classify fall back mini→mid only (dedicated `OCR_MODELS`/`CLASSIFY_MODELS`, or drop the flagship). Also **verify the `gpt-5.x` model IDs exist on the account** — a typo'd name throws `NotFoundError`, which is caught and silently walks the whole chain (`llm.py:156-166`), turning every call into a multi-attempt failure.
- **Confidence:** High (cost shape); Medium (whether flagship-in-fallback is intentional post-retune)
- `Decision:` IGNORE THIS.
- [ ]

### LLM-05 — OCR has no page cap: one vision call per page, unbounded
- **Tag:** BURN-RISK · **Severity:** High
- **Location:** `ocr/worker.py:210-216` (fan-out over `range(page_count)`) · `ocr/provider.py:88-96`. No `OCR_MAX_PAGES` setting exists.
- **What:** OCR transcribes every page as a separate vision completion with no ceiling — unlike classify (`CLASSIFY_MAX_PAGES=3`).
- **Why it matters ($):** A 200-page scan = 200 `detail:"high"` calls, each subject to LLM-01 retries. Large multi-hundred-page PDFs are routine in a document archive.
- **Evidence:** `future_to_index = {executor.submit(self._ocr_one_page, pages, i): i for i in range(page_count)}`.
- **Recommended fix:** Add `OCR_MAX_PAGES` (0 = unbounded for back-compat); slice the range and log truncation.
- **Confidence:** High
- `Decision:` IGNORE THIS.
- [ ]

### LLM-07 — Classifier compat-strip loop re-discovers unsupported params on every document
- **Tag:** BURN-RISK · **Severity:** Medium
- **Location:** `classifier/provider.py:72-100` (`_create_with_compat`, up to 4 iterations) × `_create_completion` (`@retry`)
- **What:** On a `BadRequestError` for an unsupported param, the classifier strips it and re-calls — up to 4×/model — and never caches *which* params a model rejects, so the discovery cost is repaid per document.
- **Why it matters ($):** Stacks on LLM-01. Worst case interleaves with retries. Concretely: if `gpt-5.4-mini` rejects `max_tokens` (LLM-02), every classify burns an extra billable attempt just to rediscover-and-strip it, forever.
- **Evidence:** `for _ in range(len(self._COMPAT_PARAMS)+1): ... return self._create_completion(**params)`.
- **Recommended fix:** Cache `set[str]` of unsupported params per model (process-lifetime) and pre-strip. Better, fix LLM-02 so the right param name is used and the strip never trips.
- **Confidence:** Medium
- `Decision:` FIX IT.
- [ ]

### LLM-08 — `CLASSIFY_MAX_CHARS` defaults to 0: classify input uncapped behind the page cap
- **Tag:** OPTIMISATION · **Severity:** Medium
- **Location:** `config.py:550` · `classifier/worker.py:237-243`
- **What:** The hard char ceiling on classify input is disabled by default; input is bounded only by `CLASSIFY_MAX_PAGES=3` + the headerless limit.
- **Why it matters ($):** Three dense pages (tables, fine print) can be tens of thousands of chars, all sent + the taxonomy block (CLS-01) — for a metadata task that rarely needs the full text.
- **Evidence:** `CLASSIFY_MAX_CHARS=_get_int_env(source,"CLASSIFY_MAX_CHARS",0)`; truncation applied only when `>0`.
- **Recommended fix:** Default to ~12000–20000.
- **Confidence:** Medium
- `Decision:` IGNORE THIS.
- [ ]

### LLM-09 — Full taxonomy JSON-embedded in every classify prompt *(see canonical CLS-01)*
- **Tag:** OPTIMISATION · **Severity:** Low (canonical CLS-01 is the High-severity treatment)
- **Location:** `classifier/provider.py:196-205` · `CLASSIFY_TAXONOMY_LIMIT` 100 (`config.py:553`)
- **What/Why/Fix:** Up to 300 names per call, paid on every doc, grows with the library. Full detail under **CLS-01/CLS-02**.
- **Confidence:** Low (trade-off genuine)
- `Decision:` FIX THIS.
- [ ]

### LLM-11 — Config hot-reload of a `REINDEX_KEY` re-embeds the whole archive *(see canonical PROD-03)*
- **Tag:** BURN-RISK · **Severity:** Medium
- **Location:** `config.py:146-148` (`REINDEX_KEYS = {EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP}`) · `indexer/daemon.py:200-206`
- **What:** Changing any reindex key wipes all chunks and re-embeds everything; the Settings UI can do this with no restart.
- **Why it matters ($):** A flip-flop or accidental change = a full 51 MiB re-embed, uncapped/un-confirmed in code. No tight-loop risk (sentinel consumed once/cycle); this is operator-error mitigation. Embeddings are cheap, so severity is bounded — but combined with **PROD-03/04** (watchtower + app-default model) it becomes a *silent* trigger.
- **Recommended fix:** Surface the projected cost (doc_count × avg chunks) at CRITICAL before wiping; require explicit UI confirmation for `EMBEDDING_MODEL`; pin the model (PROD-03).
- **Confidence:** Medium
- `Decision:` FIX THIS.
- [ ]

### LLM-10 — Indexer boot "ping" embed *(audited, negligible — no action)*
- **Tag:** INFO · **Severity:** Low. `indexer/daemon.py:296` embeds one token at boot (not on hot-reload — verified). Fractions of a cent; leave as-is.

---

## 6. Findings — OCR (`src/ocr`)

### OCR-01 — Every page sent at `detail:"high"` — the dominant per-page vision cost
- **Tag:** BURN-RISK · **Severity:** Critical
- **Location:** `ocr/provider.py:78` (assembled `:69-83`, sent `:96`)
- **What:** The image part hardcodes `detail:"high"`, forcing tile-based pricing on every page.
- **Why it matters ($):** `low` detail ≈ flat ~85 tokens; `high` scales to ~768px short side then bills 512px tiles at ~170 each + base → an A4 page ≈ **1000–1800+ input tokens vs ~85 at low**, a **~4–8× multiplier on the most-repeated call in the system**, on every page of every document. The cookbook's own guidance is `detail="auto"` default, reserving high for handwriting / small labels / dense tables / low-contrast scans — not blanket.
- **Evidence:** `"image_url": {"url": f"data:image/png;base64,{payload}", "detail": "high"}`.
- **Recommended fix:** Add `OCR_IMAGE_DETAIL` (default `auto` or `low`); for typed/printed docs at 1600px, low/auto is usually sufficient. Make high opt-in. Validate on a dense-scan sample before committing — this is the one win with a real quality trade-off, so A/B it.
- **Confidence:** High
- `Decision:` FIX THIS BY CHANGING TO AUTO.
- [ ]

### OCR-02 — No `max_tokens` on OCR completions *(see canonical LLM-02)*
- **Tag:** BURN-RISK · **Severity:** High
- **Location:** `ocr/provider.py:89-93` (params are only model/messages/timeout).
- **Lane note:** Unlike the classifier, OCR never caps output and has no GPT-5 param-compat handling. A mis-reading vision model can pour out thousands of output tokens per page. Fix via the central wrapper (LLM-02) with an `OCR_MAX_TOKENS`.
- **Confidence:** High
- `Decision:` OCR SHOULD NOT CAP OUTPUT OTHERWISE IT WOULD RETURN BROKEN TRANSCRIPTIONS. THIS IS WRONG. DO NOT TOUCH THIS.
- [ ]

### OCR-06 — Fallback chain × `MAX_RETRIES` multiplies paid vision attempts *(see canonical LLM-01)*
- **Tag:** BURN-RISK · **Severity:** High
- **Location:** `ocr/provider.py:88-114` × `llm.py:101` × `retry.py:54-78`.
- **Lane note:** Worst case **3 models × 20 = 60 high-detail image uploads for one page**. This compounds with OCR-01 (each attempt pays the high-detail premium) and OCR-05 (no page cap). The *successful* refusal path is bounded; the *error* path is not.
- **Confidence:** High
- `Decision:` THIS WILL BE FIXED BY LOWERING 20 RETRIES TO 3 RETRIES.
- [ ]

### OCR-10 — Transient write-back failure re-OCRs the entire document
- **Tag:** BURN-RISK · **Severity:** Medium
- **Location:** `ocr/worker.py:101-133` (transient error re-raises at `:132-133`; OCR of all pages happens at `:103` *before* the write)
- **What:** If the *write-back* fails transiently (5xx/network), the doc keeps its PRE tag and is re-pulled next poll, re-running OCR on **every page from scratch** — spent vision tokens are thrown away and repaid.
- **Why it matters ($):** A network blip after a 50-page doc is fully transcribed = 50 high-detail calls repaid. The circuit breaker only counts *permanent* failures, so transient write blips can re-OCR repeatedly without tripping it.
- **Evidence:** `page_results,_ = self._ocr_pages_in_parallel(pages)` then `outcome = self._update_paperless_document(...)`; `except PAPERLESS_CALL_EXCEPTIONS: if not is_permanent_paperless_error(exc): raise`.
- **Recommended fix:** Retry the *write* in place (a few backed-off attempts) before re-raising, or persist per-page results to resume the write without re-OCR. The write is cheap; the OCR is not.
- **Confidence:** Medium
- `Decision:` FIX THIS.
- [ ]

### OCR-08 — `OCR_MAX_SIDE=1600` is larger than `detail:"high"` actually consumes
- **Tag:** OPTIMISATION · **Severity:** Medium
- **Location:** `config.py:538` · consumed `ocr/image_converter.py:247-248`, `ocr/provider.py:129-134`
- **What:** High detail scales to a 768px short side before tiling, so part of the 1600px you generate is discarded server-side.
- **Why it matters ($):** While on high detail, ~1024–1152px long side often lands in the same/fewer tile bracket with no accuracy loss, shaving ~140–170 tokens per tile removed. If you adopt low/auto (OCR-01), image size stops affecting token cost entirely — so this only matters while you stay on high.
- **Evidence:** `OCR_MAX_SIDE=_get_int_env(source,"OCR_MAX_SIDE",1600)`.
- **Recommended fix:** If staying on high, test `OCR_MAX_SIDE≈1024–1152`. Moot once detail is low/auto.
- **Confidence:** Medium
- `Decision:` WE ARE ADOPTING AUTO.
- [ ]

### OCR-05 — OCR system prompt is oversized (~400 tokens re-sent per page)
- **Tag:** OPTIMISATION · **Severity:** Low
- **Location:** `ocr/prompts.py:6-43`
- **What/Why ($):** A ~40-line instruction block (authorisation paragraph + full Markdown marker table) sent with every page; ~350–450 tokens × every page. Prompt caching absorbs most of it on hits, but it's pure repeated cost on misses, and a leaner prompt shrinks both.
- **Evidence:** the 10-row graphical-elements table at `prompts.py:29-38`.
- **Recommended fix:** Collapse the table to a one-line legend, trim the authorisation prose; verify quality unchanged. Low priority.
- **Confidence:** Medium
- `Decision:` DO NOT TOUCH THIS.
- [ ]

**OCR audited & cleared (no action):** OCR-03 (system-static-first/image-last ordering is already correct) · OCR-07 (PNG vs JPEG changes bandwidth, **not** vision tokens — not a cost lever) · OCR-09 (cookbook `verbosity:"high"` would *raise* output tokens — do not adopt for a cost goal).

---

## 7. Findings — Classifier (`src/classifier`)

### CLS-01 — Full taxonomy (up to 300 names) injected into every classification prompt
- **Tag:** BURN-RISK · **Severity:** Critical
- **Location:** `classifier/provider.py:196-205` · `classifier/taxonomy.py:181-196` · `CLASSIFY_TAXONOMY_LIMIT` 100 (`config.py:553-555`)
- **What:** All correspondent + document-type + tag names (each capped at 100 → up to 300) are serialised into every document's user message.
- **Why it matters ($):** Paid on **every** document and grows with the library. 300 JSON-quoted names ≈ 1.5k–4k input tokens/call on top of the ~900-token system prompt. Prod already has 405 taxonomy entries. The names are usage-ranked (`_top_names`), so the long tail rarely gets reused yet is always paid.
- **Evidence:** `f"Existing correspondents ...:\n{json.dumps(taxonomy.correspondents, ...)}..."` then `"Document transcription:\n{text}"`.
- **Recommended fix:** (a) Cut `CLASSIFY_TAXONOMY_LIMIT` hard (30–40). (b) Candidate-filter: only inject names whose tokens appear in the (truncated) doc text, or top-K retrieval. A missing name isn't fatal — the normaliser already creates unseen items (`taxonomy.py:52-75`), same outcome as today for anything past the limit. Pair with CLS-02.
- **Confidence:** High
- `Decision:` FIX THIS.
- [ ]

### CLS-02 — Message ordering defeats OpenAI prompt caching
- **Tag:** OPTIMISATION · **Severity:** High
- **Location:** `classifier/provider.py:138-142,171-207`
- **What:** Per-document variable text (truncation note) leads the user message and the static taxonomy is glued into the *same* string as the variable document text — so nothing past the system prompt is a stable cacheable prefix.
- **Why it matters ($):** Caching keys on the longest identical prefix. As-is, only the ~900-token system prompt is cacheable; the big cost (the taxonomy, CLS-01) is never in a cacheable position. Static-first ordering would let the entire taxonomy block be cached across a batch at a fraction of the price (~50–90% off cached input).
- **Evidence:** `if truncation_note: parts.append(truncation_note)` (variable, first) … taxonomy + `f"Document transcription:\n{text}"` concatenated (static glued to variable).
- **Recommended fix:** Static-first, variable-last: put system prompt + tag-limit guidance + taxonomy in the cacheable region, emit truncation note + document text as the final segment. Split `text` into its own trailing part.
- **Confidence:** High
- `Decision:` FIX THIS.
- [ ]

### CLS-03 — `CLASSIFY_MAX_TOKENS` defaults to 0 (unbounded output) *(see canonical LLM-02)*
- **Tag:** BURN-RISK · **Severity:** High
- **Location:** `config.py:551` · `classifier/provider.py:217-218`
- **Lane note:** The JSON result is ~80–150 tokens, but nothing caps a runaway/verbose (esp. reasoning, CLS-05) generation. Default ~400–512. Note the GPT-5 param-name caveat in LLM-02 — verify the cap actually applies to `gpt-5.4-mini`.
- **Confidence:** High
- `Decision:` DO NOT TOUCH THIS.
- [ ]

### CLS-04 — 3-model chain × `MAX_RETRIES=20` *(see canonical LLM-01)*
- **Tag:** BURN-RISK · **Severity:** High
- **Location:** `classifier/provider.py:144-167` × `retry.py:54-78`.
- **Lane note:** Each retried/escalated attempt re-sends the full taxonomy + document payload (CLS-01). 429 retried 20×/model.
- **Confidence:** High
- `Decision:` WE ARE CHANGING MAX RETRIES ALREADY.
- [ ]

### CLS-05 — Reasoning-tier models with no `reasoning_effort` / `verbosity` cap (canonical for the reasoning bundle)
- **Tag:** BURN-RISK · **Severity:** High
- **Location:** `config.py:474` (chain has `gpt-5.4`/`gpt-5.5`) · `classifier/provider.py:209-222` (no reasoning params) — same gap in `planner.py`/`synthesizer.py` (RAG-03). Grep confirms `reasoning_effort`/`verbosity` appear **nowhere** in `src/`.
- **What:** Reasoning-capable models run at default effort on tasks that are pure structured extraction / planning / grounded QA.
- **Why it matters ($):** Reasoning tokens bill as output and are invisible — frequently 500–3000+ per call at default effort, dwarfing the ~100-token JSON result. OpenAI's guidance: *"use `none` for execution-heavy tasks … reserve `high`/`xhigh` for truly reasoning-intensive tasks"* and *"reasoning effort is a last-mile knob, not the primary way to improve quality."* Classification, planning and extractive synthesis are execution-heavy.
- **Evidence:** `_build_params` sets only model/messages/timeout/temperature/max_tokens/response_format — no `reasoning_effort`.
- **Recommended fix:** Thread `reasoning_effort` through `_complete_with_model_fallback`; classify + planner `none`/`minimal`, synth `low`. Pair with LLM-04 (move off 5.5). Verify the exact param name (`reasoning_effort` vs `reasoning.effort`) against the pinned SDK.
- **Confidence:** High (Medium on exact param name)
- `Decision:` FIX THIS. ENSURE YOU WON'T PASS THIS PARAMETER TO MODELS THAT DO NOT SUPPORT IT.
- [ ]

### CLS-06 — Parse failure escalates to the next (pricier) model instead of retrying the cheap one
- **Tag:** OPTIMISATION · **Severity:** Medium
- **Location:** `classifier/provider.py:153-166`
- **What:** On a JSON-parse failure the code `continue`s to the next model — i.e. pays a failed cheap call then a successful expensive one.
- **Why it matters ($):** Low frequency (strict Structured Outputs *is* used here — see "good"), but when it fires it's usually a truncation from hitting an output limit, which CLS-03 makes likelier.
- **Evidence:** `except (json.JSONDecodeError, ValueError): ... continue`.
- **Recommended fix:** Mostly resolved by CLS-03. Optionally retry the same model once before escalating.
- **Confidence:** Medium
- `Decision:` DO NOT TOUCH THIS. THERE'S NO POINT IN RETRYING WITH SAME MODEL.
- [ ]

### CLS-08 — System prompt verbose (~900 tokens) and contains cost-counterproductive instructions
- **Tag:** OPTIMISATION · **Severity:** Low
- **Location:** `classifier/prompts.py:10-115`
- **What/Why ($):** ~100-line system prompt with a large title-template example block (`:82-114`). Cacheable, but paid in full on cold-cache calls. Two lines actively fight the cost goal: `:34` *"Read the entire document"* (untrue post-truncation) and `:35` *"Reason step-by-step internally"* (pulls toward more tokens — contradicts the CLS-05 fix).
- **Recommended fix:** Condense examples; drop the "read entire document" and "reason step-by-step" lines (especially once `reasoning_effort` is lowered).
- **Confidence:** Medium
- `Decision:`DO NOT TOUCH THIS.
- [ ]

**Classifier audited & cleared:** CLS-07 (generic/empty results are error-tagged and de-queued — **no** re-classify loop; cost is written off once, not repeated). Structured Outputs (strict `json_schema`) **is** correctly used (`provider.py:60-63`, `prompts.py:144`); content **is** truncated (`worker.py:208-253`); **one** call/document for all fields.

---

## 8. Findings — Indexer / embeddings / store (`src/indexer`, `src/store`, `common/embeddings.py`)

> Headline: incremental indexing is **genuinely incremental** (SHA-256 gate). These findings are about overlap, the full-rebuild trigger, and one correctness gap — not a broken incremental path. Embeddings use the cheapest model, so $ impact here is modest vs the chat side.

### IDX-04 — Full re-embed is fenced, but `EMBEDDING_MODEL` is hot-loadable and a careless change wipes every vector (canonical for the re-embed bundle)
- **Tag:** BURN-RISK · **Severity:** High
- **Location:** `store/writer.py:335-394` (`check_embedding_model` wipes chunks + watermark) · `indexer/daemon.py:201` · `config.py:146-148` (`REINDEX_KEYS`) · hot-reload `daemon.py:409-412`
- **What:** Changing `EMBEDDING_MODEL` (a hot-loadable config value) makes the next boot wipe all chunks and re-embed the whole archive from scratch.
- **Why it matters ($):** The maximum-cost event: whole library × chunks × tokens. Fencing is mostly good (cannot fire from a read/search path; called once at boot; a lone `EMBEDDING_DIMENSIONS` change is rejected). **But** `EMBEDDING_MODEL` is hot-loadable and on prod runs on the *app default* with watchtower on (PROD-03/04) — so an image default change is a *silent* trigger. The wipe itself is correct (you can't mix model vectors); the risk is trigger ergonomics.
- **Evidence:** `DELETE FROM chunks; ... DELETE FROM meta WHERE key='modified_watermark'`; boot `rebuild = store_writer.check_embedding_model()`.
- **Recommended fix:** Pin `EMBEDDING_MODEL` in compose (PROD-03); log projected cost at CRITICAL before wiping; require explicit confirmation in the Settings UI. Do **not** change the wipe logic.
- **Confidence:** High
- `Decision:` FIX IT.
- [ ]

### IDX-01 — 256/2000 chunk overlap re-embeds ~13% of every changed document's tokens
- **Tag:** OPTIMISATION · **Severity:** Medium (Low $ — embeddings are cheap)
- **Location:** `config.py:278` (overlap 256) + `:462` (size 2000) · `indexer/chunker.py:94,111,131` · `indexer/worker.py:142-143`
- **What:** Adjacent chunks share 256 chars of a 2000-char window, so the overlap is embedded twice.
- **Why it matters ($):** Overlap fraction 256/2000 = **12.8%**, i.e. ~+13% input tokens over the no-overlap minimum on every embedded document — a flat ~13% surcharge on any full backfill. Not wrong (overlap aids retrieval), but a direct dial. On `text-embedding-3-small` the absolute $ is small.
- **Evidence:** `overlap_prefix = window_text[-overlap:]`; `texts = [chunk.text for chunk in text_chunks]; vectors = self._embedding_client.embed(texts)`.
- **Recommended fix:** Drop `CHUNK_OVERLAP`→128 (6.4%) or 64, or raise `CHUNK_SIZE`. Both are `REINDEX_KEYS` (one-off re-embed to take effect) — change at the next reindex, not standalone.
- **Confidence:** High
- `Decision:` FIX THIS.
- [ ]

### IDX-02 — No oversized-chunk guard: one >8191-token chunk fails the whole document, re-billing every retry
- **Tag:** BURN-RISK · **Severity:** Medium
- **Location:** `indexer/chunker.py:131` (char-based size) · `indexer/worker.py:143` · `common/embeddings.py:166-201`
- **What:** Chunk size is in *characters* (2000) but the embedding limit is 8191 *tokens*; dense CJK / non-English / base64-like OCR can exceed 8191 tokens within 2000 chars → API rejects the batch as `BadRequestError`.
- **Why it matters ($):** That error is non-retryable → `EmbeddingError` fails the *whole document* (not just the chunk) → it's retried up to 5× (`_failed_documents.py:43`), each retry re-sending the entire 96-chunk batch. One bad chunk re-bills up to 95 valid siblings, five times, before dead-lettering.
- **Evidence:** `slice_text = para_text[start:start+chunk_size]`; `vectors = self._embedding_client.embed(texts)` → `input=batch` straight to the API; whole-doc failure at `_incremental.py:323-330`.
- **Recommended fix:** Token-count guard (e.g. `tiktoken`) that hard-splits any chunk >~8000 tokens, or char-cap at ~6000; at minimum isolate per-chunk so one bad chunk skips itself.
- **Confidence:** Medium
- `Decision:` FIX THIS.
- [ ]

### IDX-03 — Metadata-only re-fetch hauls the full OCR body over HTTP every cycle (no token cost)
- **Tag:** OPTIMISATION · **Severity:** Low
- **Location:** `common/paperless.py:630-634` · `indexer/reconciler/_incremental.py:176` · `indexer/worker.py:121,126`
- **What:** The classifier's metadata PATCH bumps Paperless `modified`; `iter_all_documents` filters on `modified__gt`, so every classified doc re-enters the watermark page, where the indexer re-downloads its full OCR text and re-hashes — only to hit the hash gate and do a metadata-only update.
- **Why it matters ($):** **Zero embedding tokens** (the gate holds — system working as designed). It's a bandwidth/CPU re-processing tax, not an OpenAI cost. Flagged so it isn't mistaken for a token issue.
- **Recommended fix:** (Debt, not a quick fix.) Request a light projection (id+modified) for the diff pass; only fetch full content when the hash must be recomputed.
- **Confidence:** High
- `Decision:` FIX IT.
- [ ]

**Indexer audited & cleared:** IDX-05 (embedding concurrency caps *throughput*, not spend — raising it spends the same money faster) · IDX-06 (reconciler cadence does **not** double-embed; deletion sweep enumerates IDs only, never embeds; single-writer flock prevents concurrent indexers).

---

## 9. Findings — Search / RAG (`src/search`)

> Per-query call graph (verified): **planner (1) → retrieve → synth (1) → optional refinement synth (1)** — a hard ceiling of **3** chat calls (`core.py` `_LlmBudget`). Retrieval-only (`search_documents`) makes just the planner call. Stored docs are never re-embedded on a query path. The problem isn't the *count* — it's that each call is on the priciest tier, unbounded, un-cached, and reasoning-on.

### RAG-02 — Synthesiser default model is `gpt-5.5` (top tier) as the PRIMARY *(see also LLM-04)*
- **Tag:** BURN-RISK · **Severity:** Critical
- **Location:** `config.py:476` (`default_answer_model="gpt-5.5"`) · `synthesizer.py:136`
- **What:** The answer synthesiser — the largest-input (full chunk context) and largest-output (prose answer) call — runs on the most expensive tier by default, before any fallback.
- **Why it matters ($):** This is the single biggest recurring per-query overspend. The planner sensibly defaults to cheap `gpt-5.4-nano`, so the cheap model is on the easy call and the dear one on the expensive call — backwards for cost. For grounded extractive QA, `gpt-5.4` is typically indistinguishable.
- **Evidence:** `default_answer_model = "gpt-5.5"`; `primary_model=self.settings.SEARCH_ANSWER_MODEL`.
- **Recommended fix:** Default `SEARCH_ANSWER_MODEL`→`gpt-5.4`; keep `gpt-5.5` only in the fallback chain, gated behind eval evidence.
- **Confidence:** High
- `Decision:` FIX THIS. LET'S USE 5.4 BY DEFAULT THEN.
- [ ]

### RAG-01 — Planner & synthesiser outputs are unbounded *(see canonical LLM-02)*
- **Tag:** BURN-RISK · **Severity:** Critical
- **Location:** `synthesizer.py:135-140` · `planner.py:92-97` · root `llm.py:152-167`
- **Lane note:** Because both use `_complete_with_model_fallback`, they **cannot** set `max_tokens` today. Synth answering over a stuffed multi-chunk context with no cap, on `gpt-5.5`, is the worst offender. Fix = add the param to the helper + `SEARCH_ANSWER_MAX_TOKENS` (~600–800) and `SEARCH_PLANNER_MAX_TOKENS` (~256).
- **Confidence:** High
- `Decision:` I FEEL LIKE THIS MIGHT LEAD TO CAPPED SEARCH ANSWERS. I DO NOT WANT TO INTRODUCE THIS RISK.
- [ ]

### RAG-03 — Reasoning-tier chain, no `reasoning_effort` cap, on every query *(see canonical CLS-05)*
- **Tag:** BURN-RISK · **Severity:** High
- **Location:** `synthesizer.py:135-140` · `planner.py:92-97`.
- **Lane note:** 2–3 reasoning calls/query at default effort. Planner needs ~none; synth is grounded extraction (low). Same root fix as CLS-05.
- **Confidence:** High
- `Decision:` FIX IT.
- [ ]

### RAG-04 — Synthesis context is unbounded in token volume (no cap, full chunks, doubled on refine)
- **Tag:** BURN-RISK · **Severity:** High
- **Location:** `synthesizer.py:121` · `prompts.py:222-229` · `retriever.py:362-375` · `refinement.py:95-101` · `SEARCH_TOP_K` floor-only validated (`config.py:581-583`)
- **What:** Synth stuffs the *full text* of every chunk of the top-K docs with no per-chunk truncation and no total cap; refinement synthesises over the *merged union* of two retrieval rounds (~2×).
- **Why it matters ($):** This is the synth call's input bill; scales linearly with `SEARCH_TOP_K` (default 10 but only floor-validated — an operator can set it arbitrarily high) and `CHUNK_SIZE` (2000). The 280-char `_snippet` is display-only — synth gets `chunk.text` raw.
- **Evidence:** `labelled_chunks = [(chunk.document_id, chunk.text) for chunk in chunks]`; retriever returns *all* chunks of top-K docs.
- **Recommended fix:** `SEARCH_MAX_CONTEXT_CHARS`/token budget truncating the assembled block; an upper bound on `SEARCH_TOP_K`; consider passing only the top-N highest-RRF chunks rather than every chunk of every top-K doc.
- **Confidence:** High
- `Decision:` I FEEL LIKE THIS WILL FUCK UP SEARCH, BETTER NOT TOUCH THIS.
- [ ]

### RAG-05 — No query / result / embedding caching: identical repeat queries re-pay the full pipeline
- **Tag:** BURN-RISK · **Severity:** High
- **Location:** whole pipeline; `recent_searches.py:77-111` is history-only, recorded *after* `core.answer` (`routes.py:255-258`). Grep for `lru_cache|TTLCache|cachetools|*cache` → no result/embedding cache anywhere.
- **What:** No cache of query embeddings, plans, or answers. A byte-identical repeat pays a fresh embed + 2–3 LLM calls.
- **Why it matters ($):** A dashboard re-issuing canned queries, or a user re-running "show my invoices", pays full price every time over a slowly-changing archive.
- **Recommended fix:** Small TTL cache keyed on `(normalised_query, filters, index_version)` → serialised `SearchResult`, invalidated on index-version bump. Even 60–300s kills duplicate spend. Caching the query embedding alone is a cheap first step.
- **Confidence:** High
- `Decision:` FIX THIS! CACHE IT FOR MAYBE 4 HOURS OR SO, THEN DISAPPEAR FROM HISTORY AFTER CACHE IS GONE.
- [ ]

### RAG-06 — Planner/synth use prose-JSON via a `{…}`-substring extractor, not strict `json_schema`
- **Tag:** BURN-RISK · **Severity:** Medium
- **Location:** `planner.py:124` + `synthesizer.py:171` via `extract_json_object` (`llm.py:177-207`); contrast classifier `provider.py:219-221`
- **What:** Both ask for JSON in the prompt and parse free-text; no `response_format`. (They can't pass it — same helper limitation as RAG-01.)
- **Why it matters ($):** (1) Output tokens wasted on fences/preamble/reasoning prose every call. (2) A parse miss degrades the planner to raw-query retrieval → worse retrieval → likelier `needs_more` → triggers the *extra* refinement LLM call. So a failed parse can *cause* a 3rd paid call.
- **Evidence:** `data = extract_json_object(stripped)`; fallback slice `start=text.find("{"); end=text.rfind("}")`.
- **Recommended fix:** Thread `response_format` through the helper; strict schemas for the `QueryPlan` and the `Answered|NeedsMore` union. The classifier's adaptive "retry without response_format on BadRequest" is the template.
- **Confidence:** High
- `Decision:` FIX IT.
- [ ]

### RAG-07 — Up to 3 calls × 3 models × 20 retries = 180 attempts/query worst case *(see canonical LLM-01)*
- **Tag:** BURN-RISK · **Severity:** Medium
- **Location:** `llm.py:152-167` × `MAX_RETRIES` 20.
- **Lane note:** Search is *interactive* — 20 retries per model suits a background daemon, not a live endpoint. Also: search completions pass **no `timeout`** (classify does), so a hung request rides `REQUEST_TIMEOUT=180` before each retry. Pass `timeout` through the helper and consider a smaller retry budget for the live path.
- **Confidence:** Medium
- `Decision:` WE ARE LOWERING MAX RETRIES TO 3 ALREADY.
- [ ]

### RAG-08 — Planner runs on every query, including trivial keyword lookups
- **Tag:** OPTIMISATION · **Severity:** Medium
- **Location:** `core.py:199,246` (always `self._plan(...)`)
- **What:** Even a one-word query pays a full planner round-trip whose fallback is literally `semantic_queries=(query,)`.
- **Why it matters ($):** Removes a whole LLM call from a meaningful fraction of traffic (short/keyword queries) where the planner adds little over "embed + FTS the query".
- **Evidence:** `plan = self._plan(query, budget)` with no query-shape guard; fallback plan at `planner.py:164-169`.
- **Recommended fix:** Heuristic short-circuit: for short queries with no temporal/entity language, build the trivial plan in code and skip the call.
- **Confidence:** Medium
- `Decision:` FIX THIS VERY VERY CAREFULLY.
- [ ]

### RAG-10 — Weak-retrieval queries still pay a top-tier synth to emit a near-constant "not found"
- **Tag:** OPTIMISATION · **Severity:** Low
- **Location:** `core.py:209` + `synthesizer.py:199-205` (the genuine no-hits path at `core.py:202-207` is already optimal — 0 LLM calls)
- **What:** When retrieval returns a *few weak* chunks, the exploratory synth still runs on the top tier, and in final mode coerces a fixed "no relevant information" string after the call.
- **Recommended fix:** A minimum-RRF-score / min-chunk-count gate before the exploratory synth — below threshold, return the no-match result without calling the LLM.
- **Confidence:** Medium
- `Decision:` FIX THIS, VERY VERY CAREFULLY.
- [ ]

### RAG-09 — Synth user message puts the variable question before the static delimiter (minor caching)
- **Tag:** OPTIMISATION · **Severity:** Low
- **Location:** `prompts.py:222-229`; also `planner.py` interpolates `{today}` into the system prompt (`prompts.py:97-107`), making it non-byte-stable day-to-day.
- **Recommended fix:** Move the static delimiter/instructions to the front of the user turn; move `{today}` to the user turn so the planner system prompt is byte-stable and fully cacheable.
- **Confidence:** Medium
- `Decision:` FIX IT.
- [ ]

**Search audited & cleared:** the hard 3-call ceiling (`core.py:88-121`), retrieval-only path (1 call), single batched query embed with graceful `[]` degrade, bounded refinement (≤1), and injection-safe prompts are all correct — see §2.

---

## 10. Findings — Prod runtime (read-only SSH)

### PROD-03 — `EMBEDDING_MODEL` runs on the app default (unpinned) — silent re-embed risk (canonical with PROD-04/IDX-04)
- **Tag:** BURN-RISK · **Severity:** Medium
- **What:** `EMBEDDING_MODEL` is unset in compose/env; the app default `text-embedding-3-small` is in force.
- **Why it matters ($):** If a future image changes the default (watchtower auto-pulls — PROD-04), the model silently changes, invalidating the 51 MiB `index.db` and forcing a full re-embed at boot (IDX-04).
- **Evidence:** `indexer.started ... embedding_model=text-embedding-3-small`; `EMBEDDING_MODEL` absent from `docker exec ... env`.
- **Recommended fix:** Pin `EMBEDDING_MODEL=text-embedding-3-small` (and `EMBEDDING_DIMENSIONS`) explicitly in the compose env. One line; removes the silent trigger.
- **Confidence:** High
- `Decision:` FIX IT.
- [ ]

### PROD-04 — Watchtower auto-update enabled on all four workers
- **Tag:** BURN-RISK · **Severity:** Medium
- **What:** `com.centurylinklabs.watchtower.enable=true` on all four paperless-ai services; watchtower is running.
- **Why it matters ($):** Every auto-pulled image restarts all four workers (each a boot preflight) and, if a `REINDEX_KEY` default changed between versions, triggers an automatic full re-embed with no human in the loop (PROD-03/IDX-04). You don't control *when* a new image lands.
- **Evidence:** `docker ps` → `watchtower Up (healthy)`; compose labels on all four services.
- **Recommended fix:** Pin image tags (or pin the cost-relevant settings per PROD-03) so an auto-update can't silently change embedding behaviour. Consider excluding the indexer from auto-update, or pinning a digest.
- **Confidence:** High
- `Decision:` THIS IS OK, I CONTROL THE IMAGES. DO NOT TOUCH THIS. LET'S JUST NOT FUCK UP THE IMAGE.
- [ ]

### PROD-01 — `MAX_RETRIES=20` is live in prod *(see canonical LLM-01)*
- **Tag:** BURN-RISK · **Severity:** High — confirmed unset in every container's env, so the default 20 governs OCR + classify. Quickest mitigation while the code fix lands: set `MAX_RETRIES=3` in the compose env.
- `Decision:` CHANGE TO 3. FIX IT. ALSO FIX IN PROD.
- [ ]

### PROD-02 — Chain escalates to `gpt-5.5` on refusals in prod *(see canonical LLM-04)*
- **Tag:** BURN-RISK · **Severity:** High — doc 1164 (an ID scan) refused on mini **and** mid, then ran `gpt-5.5` for ~47 s. Any image/photo page (IDs, passports, medical) systematically escalates to the priciest tier. Quick mitigation: `AI_MODELS=gpt-5.4-mini,gpt-5.4` in compose.
- `Decision:` I ALREADY FIXED THIS, GPT-5.4-MINI,GPT-5.4,GPT-5.5,O4-MINI
- [ ]

### PROD-06 — `app.db-wal` is 4 MiB, un-checkpointed *(cosmetic)*
- **Tag:** OPTIMISATION · **Severity:** Low — no token cost; slows reads and overstates risk on unclean kill. Consider a periodic `PRAGMA wal_checkpoint(TRUNCATE)`.
- `Decision:` FIX IT.
- [ ]

**Prod audited & cleared / info:** PROD-05 (indexer logs every line **twice** — a duplicate-handler logging misconfig, not duplicate *work*; worth fixing for log hygiene but no cost) · PROD-07 (cost knobs all on app defaults — captured in the table in §3).

---

## 11. Methodology & caveats

- **Read-only.** No code was changed. This document is the only artefact written.
- **Verification.** Linchpin claims (MAX_RETRIES=20, model chains, OCR `detail:"high"`, fallback helper params, concurrency default) were re-read from source by the orchestrator, not taken on sub-agent trust. Prod facts come from read-only SSH (`docker ps/logs/exec env`, secrets masked).
- **What I could NOT fully verify (flagged as Medium confidence where relevant):**
  - Whether `gpt-5.x` actually rejects `max_tokens` (vs requiring `max_completion_tokens`) — needs a live API call to confirm; it changes whether the classifier's existing cap works (LLM-02/CLS-03).
  - Exact `reasoning_effort` param name/shape for the pinned OpenAI SDK (CLS-05/RAG-03).
  - Absolute $ figures — I deliberately give *relative multipliers* and *per-event* costs, not dollar amounts, because spend depends on your document volume, query rate, and the current price sheet. Plug your own per-model rates and monthly volumes into the multipliers above to dollarise.
- **Severity is calibrated to prod reality:** low volume, `DOCUMENT_WORKERS=1`, no observed storms. The Critical/High items are mostly *latent blast radius* (a retry storm, a silent re-embed) plus *recurring per-item* drains (OCR high-detail, gpt-5.5 synth, reasoning tokens, taxonomy) — not active incidents. At your scale, the latent tail events could dwarf steady-state spend, which is why cheap guardrails (LLM-01, PROD-03) rank near the top.

*Tell me which IDs to fix and I'll implement them (the bundle map means a handful of changes clears most of the list).*
