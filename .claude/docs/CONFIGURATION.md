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
| Secrets storage | `app.db` sits on the protected `/data` volume, so secrets are stored in clear; masking is an API-surface concern (`********` unless `?reveal=true`, which is audit-logged). `Settings.__repr__` masks them too | `src/common/config/_catalogue.py:22-26`, `src/search/settings_routes.py:63`, `src/common/config/_settings.py:471-490` |

### Key classes

| Class | Keys | Meaning |
|-------|------|---------|
| `BOOTSTRAP_KEYS` | `APP_DB_PATH`, `INDEX_DB_PATH` | Environment-only — they say where the databases live, so they can never live *in* a database |
| `SECRET_KEYS` | `OPENAI_API_KEY`, `PAPERLESS_TOKEN` | Masked by the Settings API and by `Settings.__repr__` |
| `CONFIG_KEYS` | 86 keys | The complete universe `PUT /api/settings` accepts; anything else is rejected (`validate_change_set`, `src/search/settings_service.py:238`) |
| `REINDEX_KEYS` | `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `CHUNK_SIZE`, `CHUNK_OVERLAP` | A change wipes and re-embeds the whole index; the save schedules the rebuild sentinel **before** committing |

`AI_MODELS` is a legacy env-only fallback for `OCR_MODELS`/`CLASSIFY_MODELS`, deliberately absent from `CONFIG_KEYS` (migration v6 in `app.db` splits it). `SEARCH_API_KEY` is retired — programmatic access is by minted API keys only.

### Hot-load coverage

Everything hot-loads **except** structural knobs fixed at loop/app construction: `POLL_INTERVAL` and `DOCUMENT_WORKERS` (daemon cadence and pool size), and the bootstrap keys. A config change also **resets the write-back circuit breaker** in both tag daemons and **clears the search result cache**.

### Providers

Six independent provider settings, each `openai` | `ollama`, resolved in `_build_settings` (`src/common/config/_settings.py:524-552`):

| Setting | Defaults to |
|---------|-------------|
| `OCR_PROVIDER`, `CLASSIFY_PROVIDER`, `SEARCH_PLANNER_PROVIDER`, `SEARCH_ANSWER_PROVIDER` | `LLM_PROVIDER` |
| `SEARCH_JUDGE_PROVIDER` | `SEARCH_PLANNER_PROVIDER` (not `LLM_PROVIDER`) |
| `EMBEDDING_PROVIDER` | `openai` — **independent of `LLM_PROVIDER`** (`src/common/config/_parsers.py:157-180`); flipping the chat provider does not move the embedding space |

`OPENAI_API_KEY` is required whenever *any* of the six is `openai`; a fully local deployment may omit it (it then carries `""`, not `None`) — `_settings.py:633-645`. Model defaults are per provider (`_default_models_for`, `_settings.py:103-126`):

| Provider | `OCR_MODELS` / `CLASSIFY_MODELS` | planner / answer / judge |
|----------|----------------------------------|--------------------------|
| `openai` | `gpt-5.4-mini`, `gpt-5.4`, `gpt-5.5` | `gpt-5.4-mini` / `gpt-5.5` / `gpt-5.4-mini` |
| `ollama` | `gemma3:27b`, `gemma3:12b` | `gemma3:12b` / `gemma3:27b` / `gemma3:12b` |

### Selected defaults

| Key | Default | Source |
|-----|---------|--------|
| `POLL_INTERVAL` | 15 s | `_settings.py:686` |
| `MAX_RETRIES` | 3 | `_settings.py:689` |
| `REQUEST_TIMEOUT` | 180 s — the one ceiling on every outbound call: Paperless HTTP (`paperless.py:140`), each chat call (`library_setup.py:127,140`), each embedding call (`embeddings.py:124,127`), and Poppler's `pdftoppm` kill timeout (`ocr/worker.py:175` → `image_converter.py:318`) | `_settings.py:696` |
| `LLM_MAX_CONCURRENT` | 4 (0 = unbounded) | `_settings.py:698` |
| `OCR_DPI` / `OCR_MAX_SIDE` | 300 / 1600 px | `_settings.py:704,706` |
| `PAGE_WORKERS` / `DOCUMENT_WORKERS` | 8 / 4 | `_settings.py:710,711` |
| `PRE_TAG_ID` / `POST_TAG_ID` / `ERROR_TAG_ID` | 443 / 444 / 552 | `_settings.py:672,528,684` |
| `CLASSIFY_PRE_TAG_ID` | `POST_TAG_ID` — OCR-done documents flow into the classifier with no extra wiring | `_settings.py:608` |
| `RECONCILE_INTERVAL` / `DELETION_SWEEP_INTERVAL` | 300 s / 3600 s | `_settings.py:748,751` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 2000 / 256 (overlap must be `0 <= overlap < CHUNK_SIZE`) | `_settings.py:530`, `_parsers.py:312` |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` | `text-embedding-3-small` / 1536 | `_settings.py:738,741` |
| `SEARCH_TOP_K` / `SEARCH_MAX_REFINEMENTS` | 10 / 1 (no upper cap; each pass costs LLM calls) | `_settings.py:534`, `_parsers.py:329` |
| `SEARCH_GATE_ADEQUACY` / `_RELEVANCE` / `_JUDGE` | all `true` | `_settings.py:795-802` |
| `SEARCH_RELEVANCE_MIN_SIMILARITY` | 0.60 | `_settings.py:808` |
| `SEARCH_CACHE_TTL_SECONDS` | 14400 (4 h) | `_settings.py:789` |
| `SEARCH_SESSION_TTL` | 604800 s (7 d, "remember me"; otherwise an 8 h cookie) | `_settings.py:771` |
| `SEARCH_MAX_CONCURRENT` | 4 (one ceiling shared by HTTP + MCP; 0 = unbounded) | `_settings.py:775` |
| `SEARCH_KEY_DAILY_TOKEN_QUOTA` | 0 = disabled | `_settings.py:779` |
| `SEARCH_SERVER_HOST` / `_PORT` | `0.0.0.0` / 8080 | `_settings.py:763`, `_parsers.py:392` |
| `SEARCH_FORWARDED_ALLOW_IPS` | `*` | `_settings.py:770` |
| `PRICING_REFRESH_URL` | `""` = disabled (no network call; bundled seed prices) | `_parsers.py:398` |

## Procedures

1. **Add a config key** — add it to `CONFIG_KEYS` (`src/common/config/_catalogue.py`), add the field to `Settings` and its parse/clamp line in `_build_settings` (`src/common/config/_settings.py`), and surface it in the SPA's declarative schema (`web/src/features/settings/fieldModel/sections.ts`). If it changes chunking or embeddings, add it to `REINDEX_KEYS` too.
2. **Read config at runtime** — never `os.environ`: call `common.config.current_settings()` at a safe boundary (a daemon between documents; the search server per request via `_resolve_search_core`).
3. **Test a backend without saving** — `POST /api/settings/test-connection` (admin) probes Paperless / OpenAI / Ollama and never 500s.

## Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Hot-reload hard-fails after blanking `OCR_MODELS`/`CLASSIFY_MODELS` in the UI | `_get_csv_env(..., require_non_empty=True)` raises `ValueError` on blank — unlike the int/float/bool parsers, blank is **not** "use the default" | Never blank the field; set an explicit model list |
| OCR refusal detection silently disabled | Blanking `OCR_REFUSAL_MARKERS` returns `[]` with no error (same CSV asymmetry) | Restore the marker list |
| A new AI step routes to the wrong provider | `OpenAIChatMixin._provider` defaults to `"openai"`; a step that forgets to override it ignores its own `*_PROVIDER` | Override `_provider` (see the five existing overrides in `ocr/provider.py`, `classifier/provider.py`, `search/planner.py`, `search/judge.py`, `search/synthesizer.py`) |
| `PUT /api/settings` rejects a secret | The literal mask `********` is rejected at the boundary — the SPA omits an unchanged secret | Send the new value or omit the key |
| A lone `EMBEDDING_DIMENSIONS` change silently wipes the index | It is deliberately **not** a `REINDEX_KEY`, so the save is accepted with **no** re-index warning — but `StoreWriter` compares the stored `embedding_dimensions` meta against the configured value and, on any mismatch, wipes and re-embeds the whole index at the next reconcile (`src/store/writer.py:396-430`). Nothing in `validate_change_set` rejects it (`src/search/settings_service.py:208-300`) | Only ever change it together with `EMBEDDING_MODEL`, to the width that model emits |
| Switching `EMBEDDING_PROVIDER` to `ollama` is rejected | `validate_change_set` refuses an OpenAI embedding-model name on Ollama — the save would wipe the index and then fail to re-embed | Set `EMBEDDING_MODEL` (local model) and `EMBEDDING_DIMENSIONS` (its width) in the **same** save (`src/search/settings_service.py:256-266`) |
| Config change appears to do nothing | The consumer only re-reads at a safe boundary, and `POLL_INTERVAL` / `DOCUMENT_WORKERS` are fixed for the loop's life | Wait a poll; restart only for those two keys |
| A stale `Settings` leaks between tests | `_SETTINGS_CACHE` is process-local module state | Reset it in test teardown (see `tests/unit/search/test_api_hot_reload.py`) |

## Related

- [ARCHITECTURE](ARCHITECTURE.md) · [OPERATIONS](OPERATIONS.md) · [SECURITY](SECURITY.md) · [modules/common](modules/common.md) · [modules/appdb](modules/appdb.md)
- Human docs: `docs/configuration.md`
