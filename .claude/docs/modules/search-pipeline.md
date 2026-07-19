<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../../INDEX.md)

# Module: search-pipeline

## Purpose

The read side of paperless-ai: turns a free-text query into a cited prose answer over the local SQLite search index. A bounded loop — plan → resolve filters → hybrid retrieve (vector + FTS, RRF-fused) → relevance gate → LLM judge → synthesise → optional re-plan refinement — with three fail-fast layers, a per-query LLM-call budget, a TTL result cache, per-phase telemetry/costing, and a per-API-key daily token quota.

Pure library: no FastAPI, no MCP SDK, no `sqlite3` in the pipeline modules. It is driven by `src/search/routes.py` (HTTP) and `src/search/mcp_server.py` (MCP).

**Entrypoint** — `SearchCore` in `src/search/core.py`, built by `_resolve_components` in `src/search/api.py` and cached per `config_version` by `_resolve_search_core`. Process entry point: `paperless-search-server = "search.api:main"` (`pyproject.toml`).

| Public method | LLM calls | Backs |
|---------------|-----------|-------|
| `answer(query, ui_filters, asker, on_event)` | full pipeline (≤ budget) | HTTP `/api/search`, MCP `deep_search` |
| `retrieve(query, ui_filters, on_event)` | zero chat calls (embedding only) | MCP `semantic_search` |
| `keyword_search(query, ui_filters, limit, offset)` | none (no embedding either) | MCP `keyword_search` |
| `list_filters()` | none | MCP `list_filters` |
| `fetch_documents(ids, paperless_client)` | none | MCP `fetch_documents` |

## Key files

| File | Role |
|------|------|
| `src/search/core.py` | `SearchCore` — the orchestrator (2133 lines; `# rationale:` comment authorises the §3.1 overage). Owns the bounded loop, the three fail-fast layers, `_LlmBudget`, the result-cache lookup, the refinement loop, no-match/clarify construction, and every trace-detail serialiser. `FETCH_MAX_CHARS = 50_000`. |
| `src/search/planner.py` | `QueryPlanner` (`OpenAIChatMixin`). `plan()` = LLM call #1 → `RetrievalPlan | ClarifyNeeded`; `replan()` = the Phase-2 refinement re-plan, sharing the prompt/schema/parse path via `_complete_and_parse`. Fail-open to `build_broad_semantic_plan`. (496 lines, authorised rationale.) |
| `src/search/retriever.py` | Two concerns, documented rationale (945 lines): `resolve_specs()` — free-text guesses → resolved `RetrievalSpec` (taxonomy ids + ISO dates), incl. the deterministic date safety net and unfiltered recall twins; and `Retriever` — per-spec vector/keyword store searches, one batched embedding call for all semantic specs, RRF fusion (`_RRF_K = 60`, 1-based ranks), top-K docs by best chunk, per-doc chunk cap. Also `_match_name`. |
| `src/search/judge.py` | `RelevanceJudge` — Layer 3, one cheap call on `SEARCH_JUDGE_MODEL` returning a `DocVerdict` (`keep`/`reason`/`score`) per candidate document. Recall-biased and fail-open. |
| `src/search/synthesizer.py` | `Synthesizer` — the answer call. `mode="exploratory"` may return `NeedsMore`; `mode="final"` coerces to `Answered`. Degrades to `_FALLBACK_FINAL_ANSWER` / `_FALLBACK_EXPLORATORY_ADJUSTMENT`; parses citations defensively. |
| `src/search/refinement.py` | Pure plan helpers: `broaden_plan`, `build_broad_semantic_plan`, `raw_rag_plan` (the zero-LLM `retrieve()` plan), `trivial_plan` (planner skip), `merge_chunks` (dedupe by chunk id, sort by `rrf_score` desc). |
| `src/search/relevance.py` | `relevance_tier(similarity, thresholds)` → `strong`/`good`/`partial`/`weak` from `SEARCH_RELEVANCE_TIER_*` (defaults 0.70 / 0.66 / 0.60). Independent of the Layer-2 gate floor. |
| `src/search/sources.py` | `assemble_sources` — group chunks by document (best `rrf_score`, snippet, best vector similarity), one `get_documents` look-up for taxonomy names, Paperless deep-link (`_paperless_url`), relevance tier. Sort key `(judge_score, rrf_score)` desc — a document with no judge score (no judge ran, or the judge omitted it) falls back to its `rrf_score` in the primary slot. |
| `src/search/cache.py` | Process-singleton bounded TTL `SearchResultCache` (`_MAX_ENTRIES = 512`, `OrderedDict`; eviction is oldest-*stored* first — `get` does not refresh position, so it is FIFO-by-write, not true LRU). `build_cache_key`, `is_cacheable`, `get_search_result_cache`, `reset_search_result_cache`. |
| `src/search/dates.py` | Pure deterministic date parsing: `normalise_iso_date`, `extract_date_range` (ISO literal → quarter → month+year → bare year 1900–2199 → last/this month/year; first rule wins). |
| `src/search/text.py` | Log-prefix caps (`QUERY_LOG_PREFIX_CHARS = 60`, `ADJUSTMENT_LOG_PREFIX_CHARS = 120`) and `is_trivial_query`: ≤3 words, no digit, no `@#/£$€%`, no temporal word, no interior capitalised token. |
| `src/search/prompts.py` | The three system prompts, the strict `json_schema` response formats, the user-message builders, and `build_planner_taxonomy_block` (live taxonomy names, capped by `SEARCH_PLANNER_TAXONOMY_LIMIT`). Injection defence via `common.prompt_fences.build_data_fence` (SRCH-01). (909 lines, authorised rationale.) |
| `src/search/trace.py` | `_Telemetry` — one per `answer()`/`retrieve()`. Emits `PhaseStart` + `PhaseRecord` to the optional `on_event` sink (SSE), prices each `LlmCallUsage` against its own recorded provider, accumulates `SearchTrace` + `CostSummary` onto `SearchStats`. Pins the price book once per search. |
| `src/search/pricing.py` | `MODEL_PRICES` (single edit point for OpenAI list prices, incl. the gpt-5.6 trio; `SEED_PRICES_AS_OF = "2026-07-14"`) and `price_call(model, provider, usage, table=...)`. Pure — no config, no I/O. |
| `src/search/pricing_book.py` | `PriceBook` (table + as_of + source + fetched_at) from bundled seed → `app.db` cache → optional operator-configured refresh URL. `refresh_price_book`, `get/set/reset_current_price_book`, `PricingRefreshError`. |
| `src/search/spend_quota.py` | Per-API-key daily (UTC) token quota: `check_quota()` before the pipeline (raises `QuotaExceededError` → HTTP 429 on the REST routes, a tool error on MCP), `record_usage()` / `record_usage_blocking()` after. `mcp_api_key_id` `ContextVar` carries the key id through the raw-ASGI MCP auth middleware. |
| `src/search/offload.py` | `run_blocking()` (`run_in_executor` for blocking store/LLM/SQLite work) and `LazySemaphore` (event-loop-bound on first use, hot-reloadable via `set_limit`). Shared by `routes.py` and `mcp_server.py`. |
| `src/search/fetch.py` | `assemble_fetched` — the MCP `fetch_documents` body: canonical full text from Paperless capped at `core.FETCH_MAX_CHARS`, wrapped with local index metadata. A per-id failure becomes an error-carrying `FetchedDocument`. |
| `src/search/errors.py` | `SearchError` hierarchy, incl. `LlmBudgetExceededError`. |

**Tests**

| File | Covers |
|------|--------|
| `tests/integration/test_search_pipeline.py` | Full pipeline over a real `StoreWriter`/`StoreReader` SQLite store in `tmp_path` (only LLM transport + embedding client mocked): answer-with-citation, empty-store short-circuit, `retrieve()`-only ranked sources. |
| `tests/integration/test_search_pipeline_refinement.py` | The bounded refinement loop end-to-end (split out for the 500-line ceiling). |
| `tests/integration/test_salary_april_regression.py` | The motivating regression: "What was my salary in April 2025?" must cite the April payslip (#750) and exclude the vector-equally-near Feb/Jan decoys (#1482/#1483) — only the `date()` SQL filter separates them. Pins multi-spec + date-safety-net behaviour. |
| `tests/integration/test_synth_evidence_gating.py` | Phase-3B: an off-period-only corpus must not silently substitute a decoy; the synthesiser message must carry title+date headers; multi-document citation flow-through. |
| `tests/integration/test_search_spend_quota.py` | The daily token quota across the REST and stream surfaces. |
| `tests/unit/search/` | One file per concern: `test_core*.py` (cache, fail_fast, identity, judge, skips, sources, trace), `test_planner*.py`, `test_retriever*.py`, `test_resolve_specs.py` + `test_match_name.py` (the two retriever concerns split out of `test_retriever*.py`), `test_judge.py`, `test_synthesizer*.py`, `test_refinement.py`, `test_relevance.py`, `test_sources.py`, `test_fetch.py`, `test_cache.py`, `test_dates.py`, `test_text.py`, `test_prompts*.py`, `test_trace*.py`, `test_offload.py`, `test_pricing*.py`, `test_spend_quota.py`. |

## Invariants

- **A plan always carries at least one spec.** Enforced twice: `planner._build_retrieval_plan` substitutes `build_broad_semantic_plan` when the parsed spec list is empty, and `retriever._make_safety_net_spec` synthesises a broad-semantic base rather than indexing into an empty list (which would raise `IndexError`).
- **Every LLM stage is fail-open.** `planner.plan`/`replan`, `judge.judge` and `synthesizer.synthesise` never raise: malformed / empty / all-models-failed responses degrade to a safe fallback. A degraded planner response can never become a false `ClarifyNeeded`; a degraded judge keeps every document (`degraded=True`, `score=1.0`).
- **Per-query LLM-call ceiling = `2 + j + R * (2 + j)`** (`core._max_llm_calls`), where `j = 1` iff `SEARCH_GATE_JUDGE` and `R = SEARCH_MAX_REFINEMENTS`. `_LlmBudget.record()` increments *before* each call and raises `LlmBudgetExceededError` on breach — an explicit raise, never `assert` (stripped under `python -O`). The query embedding is not a chat call and is not counted.
- **`SearchCore` holds no per-request state**; one instance is shared across all request threads. Planner/Judge/Synthesizer are pure functions wrapped in classes for DI; all state lives in the injected `Settings`.
- **`retrieve()` makes zero chat LLM calls** — only the retriever's embedding call. Layer 0 still applies; Layer 2 does not (it is advisory).
- **A taxonomy name never resolves to a guessed id.** `_match_name` returns `id=None` for `ambiguous` and `near_miss` — a wrong filter is worse than none, since text retrieval still runs.
- **UI filters may only narrow, never widen** (`retriever._intersect`): dates take the later `from` / earlier `to`; a set UI correspondent/type overrides the spec's; tags are unioned. The broadened (empty-retrieval retry) pass passes `ui_filters=None`, so a user-chosen filter does not survive the broaden.
- **Layer 0 is the only zero-LLM rejection.** A query shorter than `SEARCH_MIN_QUERY_CHARS` (default 2, measured after `strip()`) returns `outcome_kind='clarify'` with an empty trace, before any phase runs. It applies to `answer()` and `retrieve()` alike.
- **The Layer-2 relevance gate is conservative and fail-open** (`core._gate_rejects` → `core._is_irrelevant`): it runs only when `SEARCH_GATE_RELEVANCE` is on (default `True`), and rejects only when `best_vector_similarity` is known *and* below `SEARCH_RELEVANCE_MIN_SIMILARITY` (default 0.60) *and* there is no keyword hit. A `None` similarity always proceeds to synthesis.
- **The judge's boolean `keep` is the sole Layer-3 gate; `score` only ranks sources.** The pipeline bails to `no_match` only when a non-degraded judge drops every document; if filtering leaves nothing, it fails open to all chunks.
- **Retrieved chunk text is untrusted.** It only ever enters the *user* message, after the question, fenced between an unguessable per-message nonce; the system prompt declares everything inside the fence to be data, never instructions (SRCH-01, `CODE_GUIDELINES.md` §10.2). Chunk headers (`[id] title (date)`) come from our index, never from the chunk body.
- **The refinement loop always terminates with an `Answered` outcome** — the last allowed pass runs in `mode="final"`, which coerces `NeedsMore`.
- **The synthesiser final-mode fallback is a degrade sentinel and is never cached** — a model recovery is visible on the very next query.
- **The pipeline modules import `store/` and `common/` only** — never `fastapi`, the MCP SDK or `sqlite3`. The two exceptions are the DB-backed siblings: `spend_quota` (`appdb.key_usage`, `appdb.connection`) and `pricing_book` (`appdb.model_pricing`), which reach `app.db` through `appdb`, never raw `sqlite3`.
- **`search.pricing` is pure** — no config, no I/O, no network. Its I/O sibling is `search.pricing_book`.

## Gotchas

- **A cache hit still charges the spend quota.** `answer()` returns the cached `SearchResult` unchanged, so its cost summary is the *original* query's token count; all three surfaces pass that total straight through — `record_usage` in the `/api/search` handler and in the MCP tool wrapper, `record_usage_blocking` in the `/api/search/stream` worker body — so a zero-cost hit debits the key's daily bucket as if spent. The SPA is told it was a hit (a synthetic zero-cost `cache` phase whose detail carries `from_cache` / `original_cost`), but the quota path does not check.
- **`resolve_specs` can return `max_specs + 1` specs.** The unfiltered recall-twin cap bounds only *twins*; originals — including the safety-net spec — always survive (`_append_unfiltered_twins`).
- **`SEARCH_SKIP_PLANNER_FOR_TRIVIAL` bypasses Layer 1.** A trivial query short-circuits the planner call entirely (`core._plan` → `trivial_plan`), so the adequacy gate (`SEARCH_GATE_ADEQUACY`) never fires for it.
- **`SearchStats.llm_calls` counts *attempted* calls, not billed ones.** A stage that degrades because every model failed (no successful API call) is still counted.
- **The cache singleton's TTL is fixed at first construction** — `get_search_result_cache` ignores its `ttl_seconds` argument once built. A changed `SEARCH_CACHE_TTL_SECONDS` takes effect only after `reset_search_result_cache()`, which `_resolve_search_core` (`src/search/api.py`) calls whenever the `config_version` moves — so it hot-reloads on the next request after a settings save.
- **The cache key is bypassed (fail-open) when `StoreReader.get_stats()` raises** — a search must never fail because the cache could not key itself. When `SEARCH_CACHE_TTL_SECONDS == 0` the key is not even built, avoiding a wasted `get_stats()` round-trip per query.
- **The index-version key is `document_count:chunk_count:MAX(documents.indexed_at)`, never `last_reconcile_at`** — the latter is rewritten at the end of *every* reconcile cycle (including no-ops) and would evict valid no-match entries each cycle. `indexed_at` is stamped on every upsert, so an in-place re-index that leaves both counts unchanged still busts the key. An empty index renders the third component as the literal `"none"`.
- **Model fallback to `CLASSIFY_MODELS` only happens when the stage's provider equals `CLASSIFY_PROVIDER`** — otherwise those model names belong to a different endpoint and would 404. Same guard in `planner.py`, `judge.py` and `synthesizer.py`. `reasoning_effort` is passed only when the stage's provider is `openai`; `service_tier` too, and always as the literal `"default"` — the search stages never run on Flex, since a human is waiting on the response (unlike OCR/classifier, which default to Flex — see [ocr](ocr.md)/[classifier](classifier.md)). Judge's reasoning-effort default is `none` (a keep/drop filter); planner and answer stay at the models' own `medium`.
- **`_specs_equal` (the refinement no-op guard) deliberately excludes `rationale`** and sorts keywords/tag ids — the re-plan regenerates rationale text every call, so including it would stop the guard ever firing. A no-op pass skips the re-retrieve *and* the re-judge, so the actual call count sits below the `_max_llm_calls` ceiling.
- **A `ClarifyNeeded` returned by a *re-plan* is ignored** — refinement never asks the user to clarify; it falls through to a single final synthesise on existing evidence.
- **A re-judge bail mid-refinement does not downgrade to `no_match`** — it falls back to the merged chunks (we already had relevant evidence).
- **`_cited_sources` narrows sources to the cited documents**, but falls back to the full retrieved set when the outcome is `NeedsMore`, has no citations, or every cited id was hallucinated — never an empty, sourceless answer.
- **`relevance_tier` treats a keyword-only hit (`similarity is None`) as `good`**, not `weak` — an exact-term match is a deliberate signal.
- **`judge._parse_score` rejects `bool` explicitly** — `bool` is an `int` subclass, so `True` would otherwise read as score 1.0.
- **`planner._str_list` guards the classic LLM shape error**: a bare string where a list is expected (`"keywords": "invoice"`) would otherwise iterate character-by-character into `['i','n','v',…]` and poison retrieval. `_str_or_none` returns `None` (not a repr) for a list/dict, so `"correspondent": ["npower","EDF"]` never becomes the literal filter candidate `"['npower', 'EDF']"`.
- **`dates._RE_YEAR` carries a `(?!-)` negative lookahead** so a malformed ISO date (e.g. `2025-13-99`) cannot fall through to the bare-year rule and silently widen the range to the whole year.
- **The spend quota is a soft cap**: check → run → record is a window, so concurrent queries can both pass the check and overshoot. `record_usage` swallows (and logs) DB errors — a usage-write fault must never break an in-flight search or stream. `record_usage_blocking` opens its *own* `app.db` connection so a client disconnect closing the request connection cannot race the stream's write. Quota is disabled by default (`SEARCH_KEY_DAILY_TOKEN_QUOTA=0`) and never applies to cookie/browser callers — zero DB I/O in that case.
- **`LazySemaphore` with a ceiling ≤ 0 returns a `nullcontext`, not `asyncio.Semaphore(0)`** — the latter would block the first acquirer forever. `set_limit()` drops the semaphore; in-flight holders finish on the old object.
- **`cache.is_cacheable` imports `_FALLBACK_FINAL_ANSWER` from `search.synthesizer` at function scope** — its `# rationale:` comment cites a `cache` ↔ `synthesizer` import cycle. Leave it lazy; the constant is read only on the rare cache-write path.
- **`core.py` (2133), `retriever.py` (945), `prompts.py` (909) and `planner.py` (496) carry explicit `# rationale:` comments** authorising their overage of the `CODE_GUIDELINES.md` §3.1 500-line ceiling — do not "fix" them by splitting.
- **`_Telemetry` pins the price book once per search** so a background refresh cannot swap the table mid-query, and prices each call against the provider recorded on its own `LlmCallUsage` — a mixed-provider query (judge on Ollama, answer on OpenAI) costs each step correctly.
- **Cost uses `completion` tokens only** — reasoning tokens are a subset of completion. Cached-input discounts are not modelled (a deliberate over-estimate). `provider == "ollama"` → `usd=0.0, local=True`; an unknown model → `usd=None` (the UI shows "—").

## Extension points

| Want to… | Change |
|----------|--------|
| Add/refresh an OpenAI list price | `MODEL_PRICES` in `src/search/pricing.py` (bump `SEED_PRICES_AS_OF`); the operator refresh URL feeds `search.pricing_book` — there is no official OpenAI pricing API. |
| Change what the planner sees, or a prompt/JSON schema | `src/search/prompts.py` — keep untrusted chunk text inside the `build_data_fence` nonce (SRCH-01). |
| Add a deterministic plan shape (a new short-circuit) | `src/search/refinement.py` — pure helpers, no LLM, unit-testable in isolation. |
| Add a retrieval filter dimension | `RetrievalSpec` resolution in `retriever.resolve_specs` + `_intersect`, then the store-side `SearchFilters` in `store.models`. |
| Tune gating / loop shape | `SEARCH_*` keys in `src/common/config/_settings.py` (+ `_catalogue.py` for the settings UI); no pipeline code change. |
| Add an MCP tool or HTTP route | `src/search/mcp_server.py` / `src/search/routes.py` — the pipeline stays transport-free; new SSE phases serialise in `src/search/wire/stream.py`. |

## Related

- Modules: [search-api](search-api.md) (the transport that drives this one), [store](store.md) (the index it reads), [common](common.md) (LLM/embedding/config), [appdb](appdb.md) (`key_usage`, `model_pricing`).
- Consumers (outside the module boundary): `src/search/routes.py` (`/api/search`, `/api/search/stream`), `src/search/mcp_server.py` (the five MCP tools), `src/search/api.py` (wiring + hot-reload core cache), `src/search/wire/stream.py` (SSE serialisation of `PhaseEvent = PhaseStart | PhaseRecord`).
- Dependencies: `store.reader.StoreReader` (the only route to the index — the pipeline never touches `sqlite3`), `store.models`, `common.llm` (`OpenAIChatMixin`, `extract_json_object`, `LlmCallUsage`), `common.embeddings`, `common.config.Settings`, `common.paperless.PaperlessClient`, `common.prompt_fences.build_data_fence`, `appdb.key_usage` + `appdb.model_pricing`.
- Architecture: [ARCHITECTURE](../ARCHITECTURE.md)
- Human docs (read-only): `docs/search-pipeline.md`, `docs/search.md`
