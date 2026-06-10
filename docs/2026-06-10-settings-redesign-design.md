# Settings Page Redesign — Design Spec

**Date:** 2026-06-10
**Status:** Approved (mock signed off; backend split authorised)
**Mock:** `docs/settings-redesign-mock.html`

## 1. Problem

The `/settings` page has three concrete defects, confirmed against the live page:

1. **Model selection is scattered.** Answering "what model runs where" means visiting four sections — the shared `AI_MODELS` chain (LLM Provider, silently powering both OCR and Classification), the embedding model (Embeddings & Index), and Search's three separate model selects (planner/answer/judge). Two paradigms coexist (one shared fallback chain vs. per-role selects).
2. **Confusing categories.** "Performance" is a grab-bag (page-workers is an OCR concern; poll-interval a daemon concern). "Pipeline Tags" is presented as a standalone topic when it is the wiring *between* the OCR and Classify daemons. "Embeddings & Index" mixes search infrastructure with indexer scheduling.
3. **Too much at once.** ~60 fields on one scroll, with no distinction between the handful you actually tune and the set-once-forever knobs.

## 2. Goals

- Reorder and regroup settings by the **document's journey**: Connections → OCR → Classification → Indexing → Search → Automation & Daemons → Logging.
- Give **each pipeline stage ownership of its own model(s)**, so model choice is local to the stage that uses it.
- **Hide rarely-touched fields** behind per-card "Advanced" disclosures, collapsed by default.
- Adopt mediaman's **collapsed integration-card pattern with an auto-tester** for Connections.
- Use **Font Awesome** glyphs throughout (already the project's icon system).
- Preserve the existing long-scroll + scroll-spy rail navigation.

## 3. Non-goals

- No change to the settings storage model, hot-reload mechanism, draft/save machinery, or RBAC.
- No new design tokens beyond what the component library already exposes.
- No encryption-at-rest change for secrets (out of scope).
- No change to search ranking, OCR, or classification behaviour beyond the model-list source.

## 4. New category structure

Seven sections, in pipeline order. The four core stages (OCR, Classification, Indexing, Search) carry accent-coloured icon badges; the supporting sections (Connections, Automation, Logging) carry neutral badges.

| Order | Section id | Title | Rail group | Badge icon |
|------|-----------|-------|-----------|-----------|
| 1 | `connections` | Connections | Pipeline | `link` (neutral) |
| 2 | `ocr` | OCR | Pipeline | `eye` (accent) |
| 3 | `classification` | Classification | Pipeline | `tags` (accent) |
| 4 | `indexing` | Indexing | Pipeline | `index`/database (accent) |
| 5 | `search` | Search | Pipeline | `search` (accent) |
| 6 | `automation` | Automation & Daemons | Operations | `gears` (neutral) |
| 7 | `logging` | Logging | Operations | `document`/file-lines (neutral) |
| — | `users` | Users (route) | Access control | `users` |
| — | `keys` | API Keys (route) | Access control | `key` |

### 4.1 Field → section/group/Advanced mapping

Every existing config key keeps its identity; only its home and visibility change. "Adv" = inside that card's collapsed Advanced disclosure.

**Connections** (accordion integration cards, see §6.2)
- *Provider strip* (not a card): `LLM_PROVIDER` (segmented OpenAI/Ollama).
- *Paperless-ngx card*: `PAPERLESS_URL`, `PAPERLESS_PUBLIC_URL`, `PAPERLESS_TOKEN`.
- *OpenAI card*: `OPENAI_API_KEY`.
- *Ollama card* (rendered only when `LLM_PROVIDER === 'ollama'`): `OLLAMA_BASE_URL`.

**OCR**
- *Model*: `OCR_MODELS` (list), `OCR_REASONING_EFFORT` (segmented).
- *Imaging & throughput*: `OCR_DPI`, `OCR_MAX_SIDE`, `PAGE_WORKERS` (moved from Performance).
- *Advanced*: `OCR_INCLUDE_PAGE_MODELS`, `OCR_REFUSAL_MARKERS`.

**Classification**
- *Model*: `CLASSIFY_MODELS` (list), `CLASSIFY_REASONING_EFFORT` (segmented).
- *Tagging*: `CLASSIFY_TAG_LIMIT`, `CLASSIFY_DEFAULT_COUNTRY_TAG`.
- *Advanced*: `CLASSIFY_MAX_PAGES`, `CLASSIFY_TAIL_PAGES`, `CLASSIFY_MAX_CHARS`, `CLASSIFY_MAX_TOKENS`, `CLASSIFY_HEADERLESS_CHAR_LIMIT`, `CLASSIFY_TAXONOMY_LIMIT`, `CLASSIFY_PERSON_FIELD_ID`.

**Indexing**
- *Embeddings*: `EMBEDDING_MODEL` (reindex), `EMBEDDING_DIMENSIONS`.
- *Chunking & schedule*: `CHUNK_SIZE` (reindex), `CHUNK_OVERLAP` (reindex), `RECONCILE_INTERVAL`.
- *Advanced*: `DELETION_SWEEP_INTERVAL`, `EMBEDDING_MAX_CONCURRENT`.

**Search**
- *Models*: `SEARCH_PLANNER_MODEL` + `SEARCH_PLANNER_REASONING_EFFORT`; `SEARCH_ANSWER_MODEL` + `SEARCH_ANSWER_REASONING_EFFORT`; `SEARCH_JUDGE_MODEL` + `SEARCH_JUDGE_REASONING_EFFORT` (each: select + reasoning sub-line, see §6.4).
- *Retrieval & relevance*: `SEARCH_TOP_K`, `SEARCH_RELEVANCE_MIN_SIMILARITY`, `SEARCH_RELEVANCE_TIER_STRONG`.
- *Behaviour*: `SEARCH_GATE_JUDGE`, `SEARCH_IDENTITY_AWARE`.
- *Advanced*: `SEARCH_MAX_REFINEMENTS`, `SEARCH_RELEVANCE_TIER_GOOD`, `SEARCH_RELEVANCE_TIER_PARTIAL`, `SEARCH_JUDGE_RATIONALES`, `SEARCH_SERVER_HOST`, `SEARCH_SERVER_PORT`, `SEARCH_MAX_CONCURRENT`, `SEARCH_SESSION_TTL`.

**Automation & Daemons**
- *Pipeline tags*: `PRE_TAG_ID` (OCR queue), `POST_TAG_ID` (OCR complete → classifier queue), `ERROR_TAG_ID`.
- *Workers & polling*: `DOCUMENT_WORKERS`, `LLM_MAX_CONCURRENT`, `POLL_INTERVAL`.
- *Advanced*: `CLASSIFY_PRE_TAG_ID`, `CLASSIFY_POST_TAG_ID`, `OCR_PROCESSING_TAG_ID`, `CLASSIFY_PROCESSING_TAG_ID`, `REQUEST_TIMEOUT`, `MAX_RETRIES`, `MAX_RETRY_BACKOFF_SECONDS`.

**Logging**
- `LOG_LEVEL` (segmented), `LOG_FORMAT` (segmented).

> **Coverage check — preserve the current surfaced set, do not add fields.** This redesign *reorganises* the keys the UI shows today; it does not surface new ones (the brief is "too much information", so adding fields is wrong). Every key in the **current** `SETTINGS_SECTIONS` appears exactly once above, with `AI_MODELS` replaced by `OCR_MODELS` + `CLASSIFY_MODELS` (§5). Keys that are in `CONFIG_KEYS`/the GET response but were **never rendered** today stay unsurfaced: `OCR_IMAGE_DETAIL`, `SEARCH_FORWARDED_ALLOW_IPS`, `SEARCH_CACHE_TTL_SECONDS`, `SEARCH_SKIP_PLANNER_FOR_TRIVIAL`, `SEARCH_GATE_ADEQUACY`, `SEARCH_GATE_RELEVANCE`, `SEARCH_MIN_QUERY_CHARS`, plus bootstrap-only `INDEX_DB_PATH`/`APP_DB_PATH` and the constant `REFUSAL_MARK`. (`toDraft` already ignores keys with no field-model entry, so these round-trip untouched.)

## 5. Backend changes

### 5.1 Split `AI_MODELS` → `OCR_MODELS` + `CLASSIFY_MODELS`

- `src/common/config/_settings.py`: replace the `AI_MODELS` field with `OCR_MODELS` and `CLASSIFY_MODELS`, both parsed via `_get_csv_env(..., require_non_empty=True)`. Update `_ProviderDefaults` and `_resolve_provider_defaults` to carry `ocr_models` and `classify_models` (seed both with the existing provider defaults — OpenAI `["gpt-5.4-mini","gpt-5.4","gpt-5.5"]`, Ollama `["gemma3:27b","gemma3:12b"]`).
- `src/common/config/_catalogue.py`: in `CONFIG_KEYS`, replace `"AI_MODELS"` with `"OCR_MODELS"` and `"CLASSIFY_MODELS"`.
- `src/ocr/provider.py` (line ~97): `self.settings.AI_MODELS` → `self.settings.OCR_MODELS`.
- `src/classifier/provider.py` (line ~75): → `self.settings.CLASSIFY_MODELS`.
- **Search fallback** (`src/search/planner.py`, `synthesizer.py`, `judge.py`): `fallback_models=self.settings.AI_MODELS` → `self.settings.CLASSIFY_MODELS`. Rationale: these are text-only LLM calls behind a primary `SEARCH_*_MODEL`; the classify chain (text models) is the correct fallback. This removes the last `AI_MODELS` reader so the key can be deleted entirely.
- `src/ocr/daemon.py` / `src/classifier/daemon.py`: update the startup-log `ai_models=` field to the per-stage key.

### 5.2 One-time config migration

Add a migration in `src/appdb/migrations.py` (follow the existing versioned-migration pattern):

- If a `config` row `AI_MODELS` exists, copy its value into both `OCR_MODELS` and `CLASSIFY_MODELS` (only if those rows do not already exist), then delete the `AI_MODELS` row.
- Bump `config_version` so running daemons hot-reload immediately.
- Deployments that set `AI_MODELS` only via env (never persisted to the `config` table) rely on §5.3.

### 5.3 Env back-compat

In `_resolve_provider_defaults` / `_build_settings`, when `OCR_MODELS` / `CLASSIFY_MODELS` are absent from the source but a legacy `AI_MODELS` env var is present, fall back to `AI_MODELS` for both before applying coded defaults. This keeps existing `.env`/compose deployments working without edits. Emit a one-time deprecation log.

### 5.4 Connection-test: generalise to per-service

Extend `POST /api/settings/test-connection` (`src/search/settings_routes.py`, `_test_connection`) to accept an optional `service: "paperless" | "openai" | "ollama"` (default `"paperless"` for back-compat) plus the relevant credential overrides:

- `paperless`: existing behaviour (build throwaway `PaperlessClient`, `count_documents()`; `document_count` populated).
- `openai`: build a throwaway OpenAI client from candidate `OPENAI_API_KEY`; one cheap probe (`models.list()` or equivalent). `ok`/`detail` only; `document_count = 0`.
- `ollama`: probe candidate `OLLAMA_BASE_URL` reachability (a GET on the base). `ok`/`detail` only.

Mirror the existing handler contract exactly: never raise 500 — always return `TestConnectionResponse {ok, document_count, detail}` with the failure reason in `detail`. Update `TestConnectionRequest` in `src/search/wire/settings.py` to add the optional `service` and provider credential fields (all optional; empty = use stored). Admin-only, unchanged.

### 5.5 Backend tests

- Update `tests/helpers/factories/_core.py` (`make_settings*`) to provide `OCR_MODELS`/`CLASSIFY_MODELS`.
- Update every test that sets `AI_MODELS` as an env key.
- New: migration test (AI_MODELS row → both keys, version bumped, old row gone).
- New: env back-compat test (legacy `AI_MODELS` env → both lists).
- New: per-service test-connection tests (openai ok/fail, ollama ok/fail) mirroring the existing Paperless integration tests, mocking the probe clients.
- Verify the split call-sites: OCR uses `OCR_MODELS`, classifier uses `CLASSIFY_MODELS`, search fallback uses `CLASSIFY_MODELS`.

## 6. Frontend changes

### 6.1 `SETTINGS_SECTIONS` rewrite

Rewrite `web/src/features/settings/fieldModel/sections.ts` to the seven sections and the group/field/Advanced layout in §4.1. Mechanics:

- Add an optional `advanced?: boolean` to `SettingsGroup` (or a dedicated `advancedFields: SettingsField[]` on a group) so a card can render a common block plus a collapsed Advanced block. Chosen approach: extend `SettingsGroup` with an optional `advanced?: SettingsField[]` — the common `fields` render normally; `advanced` fields render inside a `Disclosure` titled "Advanced (n)". Keeps one group = one card.
- Rename the `AI_MODELS` field entry to two list fields `OCR_MODELS` / `CLASSIFY_MODELS`.
- The Search planner/answer/judge model fields use the extended select control (§6.4).

### 6.2 Connections — accordion integration cards

Build a new `features/settings/ConnectionCard` component (lives in `features/` because it consumes `TestConnectionResponse`). Mirrors mediaman's `intg-card`:

- Collapsed by default. Header: coloured glyph (brand initial), title, sub-description, a connection-status pill (`ok`/`err`/`off`/`untested` tones with a dot), a `Test` button, and a chevron (`chevron-down`, rotates on expand). Header is a `role="button"` toggling the body.
- Body (hidden when collapsed): the card's fields, rendered with the existing `Row` + `FieldControl` machinery.
- Status pill + Test wire to `useTestConnection()` with the per-service request (§5.4).

Connections renders: the provider segmented strip, then `ConnectionCard` for Paperless, OpenAI, and (only when provider is Ollama) Ollama. A small `useEffect` auto-tests configured services on mount, staggered ~200 ms apart; services with empty credentials show "Not configured" (`off`) without a probe.

`TestConnectionAction`'s current Paperless-only logic folds into `ConnectionCard` (or `ConnectionCard` reuses it). Remove the standalone Endpoint-card `headerActions` Test wiring.

### 6.3 Advanced disclosures

`SettingsSection` renders, per group: the common `fields` as today, then if `group.advanced?.length` a `Disclosure` (existing primitive) with summary "Advanced" + a count chip, containing the advanced fields as `Row`s. Collapsed by default.

### 6.4 Model + reasoning composite (Search only)

Extend `SelectControl` in `fieldModel/types.ts` with optional `reasoningKey?: string` and `reasoningOptions?: {value;label}[]`. In `FieldControl`, when a select has `reasoningKey`, render the `SettingsSelectField` then a second line: a small "Reasoning" label + a `Segmented` bound to `reasoningKey`. The composite calls `onChange(field.key, model)` and `onChange(reasoningKey, effort)` independently. Only the three Search model fields use this; OCR/Classify reasoning stay as their own `segmented` rows.

**Draft-loading the reasoning sub-key.** `toDraft` only seeds keys for which `fieldByKey` returns a field (it guards `if (field)`), so the reasoning sub-key must be resolvable even though it is not a standalone `group.fields` entry. Update `fieldByKey` and `allFieldKeys` in `fieldModel/helpers.ts` to also resolve a synthetic string-typed field for any `reasoningKey` declared on a select control. The render loop still iterates only `group.fields`, so no duplicate row appears; `toDraft` sees the reasoning key, parses it as a string, and the composite reads/writes `draft[reasoningKey]` normally. Cover this in `fieldModel.test.ts`.

### 6.5 NumberStepper — unit inside the well

Adjust `NumberStepper` so the `suffix` renders **inside** the value field, to the right of the number (e.g. `2048 px`), not as a trailing label outside the `+` button. Token-driven styling only.

### 6.6 Row — reindex pill beside the label

Add an optional reindex indicator to `Row`: when a field's key is in `reindexKeys`, render a small amber pill "Rebuilds the index on save" (FA `arrows-rotate`) **beside the label title** on the same line. Replaces/*supersedes* the current reindex note treatment. Driven by the existing `reindexKeys` set already threaded through `SettingsSection`.

### 6.7 Navigation rail

Update `SETTINGS_NAV_GROUPS` in `web/src/components/layout/SettingsLayout/SettingsLayout.tsx` to three groups — **Pipeline** (Connections, OCR, Classification, Indexing, Search), **Operations** (Automation & Daemons, Logging), **Access control** (Users, API Keys) — with new `to: '/settings#<id>'` anchors matching the new section ids and the icons from §4. No number badges. `SettingsSideNav` is presentational and unchanged. (Optionally retire the now-divergent `sectionIcons.ts` if nothing else imports it.)

### 6.8 Icon additions

Add to `IconName` union + `FA_CLASS` in `web/src/components/primitives/Icon/Icon.tsx`: `tags`→`fa-tags`, `gears`→`fa-gears`, `arrows-rotate`→`fa-arrows-rotate`, `arrow-up`→`fa-arrow-up`, `arrow-down`→`fa-arrow-down`. Add the five names to the `names` array in `Icon.test.tsx`. (`database`/`index`, `file-lines`/`document`, `book`/`library`, `eye`, `link`, `chevron-down`, `search` already exist.)

### 6.9 Frontend tests

- `fieldModel.test.ts`: assert the seven section ids, that every `Settings` key (minus bootstrap/constant) is covered, OCR/CLASSIFY split keys present, and the Advanced grouping shape.
- `SettingsSection.test.tsx`: Advanced disclosure renders collapsed; model+reasoning composite writes both keys; reindex pill renders for reindex keys.
- New `ConnectionCard.test.tsx`: collapse/expand, auto-test tones (ok/err/off), per-service request payloads, Ollama card hidden when provider is OpenAI.
- `NumberStepper.test.tsx`: suffix rendered inside the value control.
- `Icon.test.tsx`: new names covered.
- Keep `SettingsScreen.test.tsx` green (save sends only changed keys, dirty count, re-index toast).

## 7. Data flow — auto-test on mount

```
mount Connections
  → for each service in [paperless, openai, (ollama if provider=ollama)]:
       if required creds empty in draft → setConn(off, "Not configured")
       else → setConn(untested, "Testing…"); after idx*200ms:
                useTestConnection({service, …overrides})
                  → ok    → setConn(ok, "Connected")
                  → !ok   → setConn(err, detail)
```

Manual `Test` button reuses the same path for one service and shows transient "Testing…/OK ✓/Failed" on the button.

## 8. Risks & mitigations

- **Migration on live prod (push-to-main deploys).** The migration is idempotent (only copies when target rows absent; deletes the old row). Env back-compat (§5.3) covers env-only deployments. Verify against the actual deployment's `app.db` state in the plan's verification step.
- **Search fallback semantics change.** Routing search fallback to `CLASSIFY_MODELS` instead of `AI_MODELS` is behaviour-equivalent for any deployment whose `AI_MODELS` was the de-facto text chain; the migration copies the same list into `CLASSIFY_MODELS`, so the effective fallback is unchanged on upgrade.
- **Auto-test load cost.** 2–3 probes per settings open, staggered, only for configured services; admin-only page, low frequency. Acceptable.
- **Coverage thresholds** (web: 90/85/90/90). New `ConnectionCard` and control changes need tests to stay above floors.
- **Two-key composite control** must not double-count dirty state or break the "save only changed keys" contract — covered by tests.

## 9. Build sequence

1. **Backend split + migration + env back-compat** (config, providers, search fallback, daemons, migration) with tests. Independently shippable; UI keeps working via the unchanged GET/PUT surface.
2. **Per-service test-connection endpoint** + wire model + tests.
3. **Icon additions** (+ test).
4. **Primitive tweaks**: NumberStepper suffix-inside; Row reindex pill; `SettingsGroup.advanced` + Disclosure rendering in `SettingsSection`; SelectControl reasoning composite.
5. **`ConnectionCard`** + auto-tester wiring + tests.
6. **`SETTINGS_SECTIONS` rewrite** to the new structure + `SETTINGS_NAV_GROUPS` rail regroup + tests.
7. **Full verification**: web `lint`/`typecheck`/`test`/`build`; backend `ruff`/`mypy`/`pytest`; run the app and eyeball against the mock; confirm CI green.
