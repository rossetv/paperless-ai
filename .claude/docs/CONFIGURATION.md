<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../INDEX.md)

# Configuration

## Facts

### Model

| Item | Value | Source |
|------|-------|--------|
| Precedence | `app.db` `config` table value **>** environment variable **>** coded default | `src/common/config/_loader.py` |
| Shape | `Settings` — `@dataclass(frozen=True, slots=True)`, built once, never mutated. A change produces a *new* object; consumers detect it by identity | `src/common/config/_settings.py` |
| Single validation path | Both loaders funnel through `_build_settings`, so parsing/validation/clamping is identical whatever the source | `src/common/config/_settings.py` |
| First-run seeding | `appdb.config.seed_from_env` imports the environment into the table **only when the table is entirely empty** (idempotent — every process boots at once and all call it) | `src/appdb/config.py` |
| Hot-load | `current_settings(app_db_path)` takes one `BEGIN DEFERRED` snapshot of `(config_version, config)` and rebuilds only when the monotonic `config_version` has advanced. Cross-process coordination is that integer alone — no signal, no IPC, no restart | `src/common/config/_loader.py` |
| Write path | `PUT /api/settings` (admin) validates, writes and bumps `config_version` in one `BEGIN IMMEDIATE` | `src/search/settings_routes.py`, `src/appdb/config.py` |
| Secrets storage | `app.db` sits on the protected `/data` volume, so secrets are stored in clear; masking is an API-surface concern (`********` unless `?reveal=true`, which is audit-logged). `Settings.__repr__` masks them too | `src/common/config/_catalogue.py` (`SECRET_KEYS`), `src/search/settings_routes.py::get_settings`, `src/common/config/_settings.py` (`Settings.__repr__`) |

### Key classes

| Class | Keys | Meaning |
|-------|------|---------|
| `BOOTSTRAP_KEYS` | `APP_DB_PATH`, `INDEX_DB_PATH` | Environment-only — they say where the databases live, so they can never live *in* a database |
| `SECRET_KEYS` | `OPENAI_API_KEY`, `PAPERLESS_TOKEN` | Masked by the Settings API and by `Settings.__repr__` |
| `CONFIG_KEYS` | 87 keys | The complete universe `PUT /api/settings` accepts; anything else is rejected (`validate_change_set` in `src/search/settings_service.py`) |
| `REINDEX_KEYS` | `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `CHUNK_SIZE`, `CHUNK_OVERLAP` | A change wipes and re-embeds the whole index; the save schedules the rebuild sentinel **before** committing |

`AI_MODELS` is a legacy env-only fallback for `OCR_MODELS`/`CLASSIFY_MODELS`, deliberately absent from `CONFIG_KEYS` (migration v6 in `app.db` splits it). `SEARCH_API_KEY` is retired — programmatic access is by minted API keys only.

### Hot-load coverage

Everything hot-loads **except** structural knobs fixed at loop/app construction: `POLL_INTERVAL` and `DOCUMENT_WORKERS` (daemon cadence and pool size), and the bootstrap keys. A config change also **resets the write-back circuit breaker** in both tag daemons and **clears the search result cache**.

### Providers

Six independent provider settings, each `openai` | `ollama`, resolved in `_build_settings` (`src/common/config/_settings.py`):

| Setting | Defaults to |
|---------|-------------|
| `OCR_PROVIDER`, `CLASSIFY_PROVIDER`, `SEARCH_PLANNER_PROVIDER`, `SEARCH_ANSWER_PROVIDER` | `LLM_PROVIDER` |
| `SEARCH_JUDGE_PROVIDER` | `SEARCH_PLANNER_PROVIDER` (not `LLM_PROVIDER`) |
| `EMBEDDING_PROVIDER` | `openai` — **independent of `LLM_PROVIDER`** (`src/common/config/_parsers.py::_resolve_embedding_provider`); flipping the chat provider does not move the embedding space |

`OPENAI_API_KEY` is required whenever *any* of the six is `openai`; a fully local deployment may omit it (it then carries `""`, not `None`) — `_settings.py` (`_build_settings`). Model defaults are per provider (`_default_models_for` in `_settings.py`):

| Provider | `OCR_MODELS` / `CLASSIFY_MODELS` | planner / answer / judge |
|----------|----------------------------------|--------------------------|
| `openai` | `gpt-5.6-luna`, `gpt-5.6-terra` | `gpt-5.6-terra` / `gpt-5.6-terra` / `gpt-5.6-luna` |
| `ollama` | `gemma3:27b`, `gemma3:12b` | `gemma3:12b` / `gemma3:27b` / `gemma3:12b` |

`gpt-5.6-sol` (the third 5.6 tier) is selectable in every model field but is never a coded default — nothing in the pipeline is frontier-hard enough to justify its price (spec D1). `OPENAI_FLEX_TIER` (default `true`) applies the ~50%-cheaper Flex service tier to OCR + classifier only, and only while that step's provider is `openai`; the three search stages always run on the standard tier.

### Selected defaults

| Key | Default | Source |
|-----|---------|--------|
| `POLL_INTERVAL` | 15 s | `_settings.py` (`_build_settings`) |
| `MAX_RETRIES` | 3 | `_settings.py` (`_build_settings`) |
| `REQUEST_TIMEOUT` | 180 s — the one ceiling on every outbound call: Paperless HTTP (`paperless.py` `PaperlessClient.__init__`), each chat call (`library_setup.py::setup_libraries`), each embedding call (`embeddings.py::_build_embedding_client`), and Poppler's `pdftoppm` kill timeout (`ocr/worker.py::OcrProcessor._download_and_convert` → `image_converter.py::_pdf_to_page_source`) | `_settings.py` (`_build_settings`) |
| `OPENAI_FLEX_TIER` | `true` — OCR + classifier only, gated on that step's own provider being `openai`; floors the per-call timeout at `FLEX_MIN_TIMEOUT_SECONDS` (600s) when on | `_settings.py` (`OPENAI_FLEX_TIER` field), `common/llm.py::service_tier_params` |
| `OCR_REASONING_EFFORT` | `none` — perception, not reasoning, on the highest-volume call | `_parsers.py::_resolve_ocr_reasoning_effort` |
| `CLASSIFY_REASONING_EFFORT` | `low` — schema-constrained extraction needs little deliberation | `_parsers.py::_resolve_classify_reasoning_effort` |
| `SEARCH_JUDGE_REASONING_EFFORT` | `none`; `SEARCH_PLANNER_REASONING_EFFORT` / `SEARCH_ANSWER_REASONING_EFFORT` stay `medium` (the models' own default) | `_settings.py` (`_build_settings`) |
| Reasoning-effort choice set | `{none, low, medium, high, xhigh}` — matches the live OpenAI API (verified 2026-07-15), not the installed SDK's `ReasoningEffort` literal, which still lists the retired `minimal`/lacks `xhigh`. A stored `minimal` is coerced to `none` with a `config.reasoning_effort_minimal_coerced` warning rather than rejected, so a pre-existing config never bricks a deploy | `_parsers.py` (`_REASONING_EFFORT_CHOICES`, `_resolve_reasoning_effort`) |
| `LLM_MAX_CONCURRENT` | 4 (0 = unbounded) | `_settings.py` (`_build_settings`) |
| `OCR_DPI` / `OCR_MAX_SIDE` | 300 / 1600 px | `_settings.py` (`_build_settings`) |
| `PAGE_WORKERS` / `DOCUMENT_WORKERS` | 8 / 4 | `_settings.py` (`_build_settings`) |
| `PRE_TAG_ID` / `POST_TAG_ID` / `ERROR_TAG_ID` | 443 / 444 / 552 | `_settings.py` (`_build_settings`) |
| `CLASSIFY_PRE_TAG_ID` | `POST_TAG_ID` — OCR-done documents flow into the classifier with no extra wiring | `_settings.py` (`_build_settings`) |
| `RECONCILE_INTERVAL` / `DELETION_SWEEP_INTERVAL` | 300 s / 3600 s | `_settings.py` (`_build_settings`) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 2000 / 256 (overlap must be `0 <= overlap < CHUNK_SIZE`) | `_settings.py` (`_build_settings`), `_parsers.py::_resolve_chunk_overlap` |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` | `text-embedding-3-small` / 1536 | `_settings.py` (`_build_settings`) |
| `SEARCH_TOP_K` / `SEARCH_MAX_REFINEMENTS` | 10 / 1 (no upper cap; each pass costs LLM calls) | `_settings.py` (`_build_settings`), `_parsers.py::_resolve_search_max_refinements` |
| `SEARCH_GATE_ADEQUACY` / `_RELEVANCE` / `_JUDGE` | all `true` | `_settings.py` (`_build_settings`) |
| `SEARCH_RELEVANCE_MIN_SIMILARITY` | 0.60 | `_settings.py` (`_build_settings`) |
| `SEARCH_CACHE_TTL_SECONDS` | 14400 (4 h) | `_settings.py` (`_build_settings`) |
| `SEARCH_SESSION_TTL` | 604800 s (7 d, "remember me"; otherwise an 8 h cookie) | `_settings.py` (`_build_settings`) |
| `SEARCH_MAX_CONCURRENT` | 4 (one ceiling shared by HTTP + MCP; 0 = unbounded) | `_settings.py` (`_build_settings`) |
| `SEARCH_KEY_DAILY_TOKEN_QUOTA` | 0 = disabled | `_settings.py` (`_build_settings`) |
| `SEARCH_SERVER_HOST` / `_PORT` | `0.0.0.0` / 8080 | `_settings.py` (`_build_settings`), `_parsers.py::_resolve_server_port` |
| `SEARCH_FORWARDED_ALLOW_IPS` | `*` | `_settings.py` (`_build_settings`) |
| `PRICING_REFRESH_URL` | `""` = disabled (no network call; bundled seed prices) | `_parsers.py::_resolve_pricing_refresh_url` |

## Procedures

1. **Add a config key** — add it to `CONFIG_KEYS` (`src/common/config/_catalogue.py`), add the field to `Settings` and its parse/clamp line in `_build_settings` (`src/common/config/_settings.py`), and surface it in the SPA's declarative schema (`web/src/features/settings/fieldModel/sections.ts`). If it changes chunking or embeddings, add it to `REINDEX_KEYS` too.
2. **Read config at runtime** — never `os.environ`: call `common.config.current_settings()` at a safe boundary (a daemon between documents; the search server per request via `_resolve_search_core`).
3. **Test a backend without saving** — `POST /api/settings/test-connection` (admin) probes Paperless / OpenAI / Ollama and never 500s.

## Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Hot-reload hard-fails after blanking `OCR_MODELS`/`CLASSIFY_MODELS` in the UI | `_get_csv_env(..., require_non_empty=True)` raises `ValueError` on blank — unlike the int/float/bool parsers, blank is **not** "use the default" | Never blank the field; set an explicit model list |
| A blank value for a scalar key (`STALE_LOCK_RECOVERY=` in a compose file) means "use the coded default" | `_get_int_env` / `_get_float_env` / `_get_bool_env` all fall back on blank (COMMON-20). Blank *is* reachable in the config table: `appdb.config.seed_from_env` copies an empty env var in verbatim | Nothing to do — but note a bad *non-blank* value still fails closed at boot |
| OCR refusal detection silently disabled | Blanking `OCR_REFUSAL_MARKERS` returns `[]` with no error (same CSV asymmetry) | Restore the marker list |
| A new AI step routes to the wrong provider | `OpenAIChatMixin._provider` defaults to `"openai"`; a step that forgets to override it ignores its own `*_PROVIDER` | Override `_provider` (see the five existing overrides in `ocr/provider.py`, `classifier/provider.py`, `search/planner.py`, `search/judge.py`, `search/synthesizer.py`) |
| A stored `*_REASONING_EFFORT=minimal` from before 2026-07-15 doesn't crash the daemon on hot-reload | `minimal` is gone from `_REASONING_EFFORT_CHOICES`, but `_resolve_reasoning_effort` coerces it to `none` (logging `config.reasoning_effort_minimal_coerced`) instead of raising — validation runs on every hot-reload, so a hard fail would brick a live config | Re-save the field from the Settings UI to persist `none` explicitly and silence the warning |
| `PUT /api/settings` rejects a secret | The literal mask `********` is rejected at the boundary — the SPA omits an unchanged secret | Send the new value or omit the key |
| A lone `EMBEDDING_DIMENSIONS` change silently wipes the index | It is deliberately **not** a `REINDEX_KEY`, so the save is accepted with **no** re-index warning — but `StoreWriter` compares the stored `embedding_dimensions` meta against the configured value and, on any mismatch, wipes and re-embeds the whole index at the next reconcile (`src/store/writer.py::StoreWriter.upsert_document`). Nothing in `validate_change_set` rejects it (`src/search/settings_service.py::validate_change_set`) | Only ever change it together with `EMBEDDING_MODEL`, to the width that model emits |
| Switching `EMBEDDING_PROVIDER` to `ollama` is rejected | `validate_change_set` refuses an OpenAI embedding-model name on Ollama — the save would wipe the index and then fail to re-embed | Set `EMBEDDING_MODEL` (local model) and `EMBEDDING_DIMENSIONS` (its width) in the **same** save (`src/search/settings_service.py::validate_change_set`) |
| Config change appears to do nothing | The consumer only re-reads at a safe boundary, and `POLL_INTERVAL` / `DOCUMENT_WORKERS` are fixed for the loop's life | Wait a poll; restart only for those two keys |
| A stale `Settings` leaks between tests | `_SETTINGS_CACHE` is process-local module state | Reset it in test teardown (see `tests/unit/search/test_api_hot_reload.py`) |

## Related

- [ARCHITECTURE](ARCHITECTURE.md) · [OPERATIONS](OPERATIONS.md) · [SECURITY](SECURITY.md) · [modules/common](modules/common.md) · [modules/appdb](modules/appdb.md)
- Human docs: `docs/configuration.md`
