# Spec — OpenAI Flex tier + GPT-5.6 model adoption

**Date:** 2026-07-15 · **Session slug:** flex-and-56-models · **Status:** approved by operator

## Goal

Cut LLM spend on the two highest-volume pipelines (OCR, classifier) by roughly 60–75% and
modernise every pipeline step onto the GPT-5.6 family, without touching `.env`, embeddings, or
prod behaviour until the operator flips stored settings in the UI.

Four workstreams: (1) refresh the reasoning-effort choice set, (2) adopt GPT-5.6 defaults and
dropdown options, (3) add OpenAI Flex processing (`service_tier: "flex"`) to the background
daemons behind a settings toggle, (4) make Flex capacity-429s retry until done instead of
error-tagging documents.

## Background and evidence

Two evidence layers, both required reading before re-litigating anything here:

**Live OpenAI docs research (2026-07-14, Chrome MCP against developers.openai.com).**
GPT-5.6 family confirmed real: `gpt-5.6-sol` $5/$30 per Mtok in/out, `gpt-5.6-terra` $2.50/$15,
`gpt-5.6-luna` $1/$6 — all 1.05M context, 128K max out, vision, structured outputs, Chat
Completions supported. Flex tier bills at Batch rates (50% off), returns occasional
`429 resource_unavailable` (unbilled) when capacity is short, default timeout 10 min, docs
describe it as ideal for "asynchronous workloads" — a literal description of the OCR and
classifier daemons. `gpt-5.4-mini`/`-nano` are not deprecated. Long-context (>272K input)
bills 2×/1.5× — irrelevant at current prompt sizes. 5.6 prompt-cache writes cost 1.25× input;
minimum cacheable prefix 1,024 tokens (the ~430-token OCR system prompt will simply never
cache — neutral).

**Live API verification (2026-07-15, 13 calls against api.openai.com with the operator's
service-account key).** This supersedes the docs where they conflict:

| Claim | Live verdict |
|---|---|
| `reasoning_effort: "none"` on Chat Completions | **Accepted** — gpt-5.6-luna/terra and gpt-5.4-mini all return 200, `reasoning_tokens=0` |
| `service_tier: "flex"` | **Accepted**, echoed back as `service_tier: "flex"` in the response |
| `reasoning_effort: "minimal"` | **Rejected** — 400 `unsupported_value`, message names `reasoning_effort` → the strip-layer matcher in `src/common/llm.py` (`_STRIPPABLE_PARAMS`) matches it |
| `temperature: 0.2` on 5.6 | **Rejected** — 400 `unsupported_value`, message names `temperature` → the classifier's hardcoded 0.2 strips cleanly, once per process |
| `reasoning_effort: "max"` | **Does not exist.** All three 5.6 models report supported values `none, low, medium, high, xhigh`. The docs' model-index chips listing `max` are wrong or stale. |
| `xhigh` | Accepted (gpt-5.6-luna, 200) |
| Quirk | `gpt-5.6-luna` + `reasoning_effort:"none"` + **no** `service_tier` → HTTP 401 "insufficient permissions", reproduced twice; identical call with explicit `service_tier:"default"` or `"flex"` succeeds; terra unaffected. Key-scoping or an OpenAI backend bug — unresolved, but cheap to immunise against (always send an explicit `service_tier`). |

Flex capacity-429 could not be provoked on demand; the assumption that it surfaces as
`openai.RateLimitError` (HTTP 429) rests on the docs and must be confirmed against the
exception type during implementation testing.

## Decisions

Each decision records the why and the rejected alternatives. Do not re-open without new
information; the operator has already ruled on all of these.

### D1 — Adopt GPT-5.6 Luna + Terra as defaults; Sol selectable but default nowhere

Nothing in this pipeline is frontier-hard: OCR is perception, classification is
schema-constrained extraction, the judge is a keep/drop filter. Sol buys nothing at 5× Luna's
price. Terra goes where reasoning-per-dollar matters (planner — a bad plan poisons everything
downstream; answer — biggest prompt, user waiting, citation grounding is the product).
**Rejected:** Sol as any default (pure waste); staying on gpt-5.4-mini (legitimate — not
deprecated — but forfeits both the cheaper sticker and the reasoning-token savings).

### D2 — Reasoning-effort choice set becomes `{none, low, medium, high, xhigh}`

`minimal` is gone from every current model (live-verified). `none` is the single biggest
saving on OCR and is currently blocked by the stale `_REASONING_EFFORT_CHOICES` frozenset in
`src/common/config/_parsers.py`, which was derived from the installed SDK's `ReasoningEffort`
Literal rather than the API. `max` is **excluded** — the operator initially chose "full
current set including max" from the docs, but live calls prove no 5.6 model accepts it;
including it recreates the exact silent-cost trap this change kills (pick it → 400 → strip
layer removes `reasoning_effort` entirely → model runs at its default `medium`). Deviation
approved at design review. The choice-set source of truth is now the live API, and the
comment above the frozenset must say so.

**Legacy migration:** validation fails closed at settings-build (daemon startup AND
hot-reload). A `"minimal"` stored in prod's config table would crash every daemon on the
first deploy. The shared resolver therefore coerces `minimal` → `none` with a warning log
instead of raising; all other invalid input still raises. `none` is chosen as the coercion
target because minimal sat below `low` on the old scale and the operator's stated intent for
cheap steps is `none`. **Rejected:** hard failure (bricks prod on deploy); coercing to `low`
(silently more expensive than the operator's floor).

### D3 — One global Flex toggle, `OPENAI_FLEX_TIER`, default on, OCR + classifier only

Single boolean config key (`CONFIG_KEYS` catalogue + `Settings` field + UI toggle in the
Connections → OpenAI section). Applies `service_tier: "flex"` to OCR and classifier calls
when the step's provider is `openai`. Search stages (planner/judge/synthesiser) never use
Flex — a human is waiting on those calls. Hot-loads without restart (daemons call
`current_settings()` every poll). Default **on** — operator's explicit choice; the discount
is the point.
**Rejected:** the Batch API (identical 50% discount but demands a job-submission/polling
architecture; Flex is a one-param change); per-stage flex toggles (no present need — the two
consumers move together); an env-var-only switch (operator manages config in the UI).

### D4 — Every OpenAI call sends an explicit `service_tier`

OCR/classifier: `"flex"` when the toggle is on, `"default"` when off. Search stages: always
`"default"`. Motivated by the live 401 quirk: the search judge's new default (luna + `none`)
is the exact combination that failed without an explicit tier. Explicit `"default"` is
documented, free, and deterministic.
**Safety net:** `service_tier` joins `_STRIPPABLE_PARAMS` in `src/common/llm.py` so any
OpenAI-compatible proxy or future provider that rejects the param gets it stripped and cached
rather than failing the model. (Ollama never sees it — the provider gate omits it — but the
strip entry is belt-and-braces.)

### D5 — Flex capacity-429: retry in-process until done

Operator's explicit pick ("just keep retrying until done") over two alternatives. Today a
sustained 429 burns the whole model chain in ~30–45s (app retry `MAX_RETRIES=3` × the SDK's
hidden client `max_retries=2` ≈ 9 HTTP attempts per model, then fallback) and then
**permanently error-tags the document** — it leaves the queue, a human must re-tag it. Under
Flex, capacity-429s are routine and unbilled, so that behaviour would quietly quarantine the
whole backlog during any capacity dip.

New semantics, scoped to **flex-tier calls only**: on `openai.RateLimitError`, retry the same
model indefinitely with exponential backoff capped at 60s, honouring daemon shutdown so the
process can still stop promptly. No model fallback on 429 (capacity shortage ≠ broken model),
no error tag, per-page work preserved. Every other error class keeps today's behaviour
(retry budget → fallback chain → error tag). A worker thread staying occupied during a
capacity outage is accepted — these are background daemons; the queue would stall either way.
**Rejected:** bounded retry (~15 min) then requeue-untagged (frees threads but re-OCRs — and
re-bills — the document's already-completed pages on every cycle); requeue-only (same
re-billing churn every 15s poll).

### D6 — Flex timeout: per-call `max(REQUEST_TIMEOUT, 600)`

Flex's documented default timeout is 10 min; `REQUEST_TIMEOUT` defaults to 180s. OCR and
classifier already pass a per-call `timeout` — raise it only on flex-tier calls. The
client-level default and every non-flex call keep `REQUEST_TIMEOUT`.
**Rejected:** raising global `REQUEST_TIMEOUT` (drags every call, including interactive
search, to 10 min); a new `FLEX_TIMEOUT` config knob (a config option for a value with
exactly one sensible setting today — overengineering smell).

### D7 — Search-stage model dropdown: the 5.6 trio only

`MODEL_OPTIONS` (used only by the planner/judge/answer selects) becomes
`gpt-5.6-luna / gpt-5.6-terra / gpt-5.6-sol`. Operator's literal ask; minimal dropdown rot.
Prod's currently-stored `gpt-5.4-nano`/`-mini` values still render — `SettingsSelectField`
injects an out-of-list stored value as an extra option — but once changed away, 5.4 models
can't be re-picked from the UI. Operator accepts.
**Rejected:** trio + 5.4 escape hatches; trio + all five current options (clutter, keeps
models nobody recommends). OCR_MODELS / CLASSIFY_MODELS are free-text list controls — no
dropdown exists there; only their defaults change.

### D8 — Defaults (the operator's approved configuration)

| Step | Models default | Effort default | Why |
|---|---|---|---|
| OCR | `gpt-5.6-luna, gpt-5.6-terra` | `none` | Perception, not reasoning; highest-volume call (per page) |
| Classifier | `gpt-5.6-luna, gpt-5.6-terra` | `low` | Schema-constrained extraction under strict `json_schema`; 1.05M context removes today's overflow risk |
| Search planner | `gpt-5.6-terra` | `medium` (unchanged) | Tiny prompt, one call, bad plan poisons everything — best reasoning-per-dollar in the product |
| Search judge | `gpt-5.6-luna` | `none` | Keep/drop filter — the docs' stated `none` use case |
| Search answer | `gpt-5.6-terra` | `medium` (unchanged) | Biggest prompt, user waiting, citation grounding is the product |
| Embeddings | **untouched** | n/a | See non-goals |

Ollama defaults (`gemma3:*`) untouched. Note `CLASSIFY_MODELS` is also the fallback chain for
planner/judge/synthesiser when that stage's provider matches — its new luna/terra value is a
sane chain for all of them. Search cost rises (~$0.10/query vs ~$0.02 on prod's nano chain) —
operator accepts; homelab query volume makes it a rounding error and the nano planner was the
weakest link in the system. Expected OCR cost: ~$0.003–0.005/page (luna @ none + Flex) vs
~$0.014 today (5.4-mini @ medium, standard) — the swing is mostly reasoning tokens and the
Flex discount, not the sticker price.

### D9 — Pricing table

`MODEL_PRICES` in `src/search/pricing.py` gains rows: luna 1.00/6.00, terra 2.50/15.00,
sol 5.00/30.00 (standard-tier, uncached — the table's existing deliberate over-estimate
convention; the search path never uses Flex so no Flex modelling needed). Existing rows stay —
prod runs on them until the operator flips stored settings. `SEED_PRICES_AS_OF` → 2026-07-14;
the "confirmed against the operator's account" comment is updated to cite the live docs +
live-call verification. Without these rows the cost chip silently shows "—" for every 5.6
call.

### D10 — Left alone, deliberately

- **Responses API migration** — rejected. Rewrites the single transport
  (`OpenAIChatMixin._create_completion`) plus every param path in all five stages, and Ollama
  speaks Chat Completions, so the dual-provider registry would need a second transport. A
  rewrite for a marginal quality gain. `reasoning.mode: "pro"` is Responses-only and stays
  unreachable.
- **Embeddings** — untouched. The stored identity triple `(provider, model, dimensions)`
  wipes the entire index on mismatch at next boot with no confirmation; no newer OpenAI
  embedding model exists anyway.
- **SDK client `max_retries`** — left at its implicit default (2). It stacks under the app
  retry loop (compounding attempts ×3 without the app layer knowing) but is harmless under
  the new patient 429 loop; reconstructing per-tier clients is complexity without present
  need. Recorded here so the stacking isn't rediscovered as a surprise.
- **`xhigh`/`max` as pipeline defaults, Sol at any step** — rejected (see D1/D2).

## Non-goals (known issues explicitly out of scope)

Recorded so they aren't mistaken for oversights; all pre-date this change:

1. No token/cost accounting on OCR or classifier (`usage_sink` is search-only) — flying blind
   on exactly the highest-volume calls. Check the OpenAI dashboard before/after this deploy.
2. Relevance-badge cut-points calibrated against `text-embedding-3-large` while the default
   model is `-small` — investigate separately.
3. Classifier prompt says "up to 8 tags" while the tag limit truncates to 5 — paying for
   discarded tags; prompt tuning, separate change.
4. `model_compat_cache` is process-local, never persisted — every redeploy re-pays discovery
   400s (one unbilled round-trip per stripped param per model; acceptable).

## Touch points

Python (`src/`):
- `common/config/_parsers.py` — `_REASONING_EFFORT_CHOICES` (new set + comment: source is
  live API, verified 2026-07-15); `_resolve_reasoning_effort` (minimal→none coercion +
  warning); `_resolve_ocr_reasoning_effort` Literal; **boy-scout:** the per-query LLM budget
  docstring near `_resolve_search_settings` lies (claims `2 + SEARCH_MAX_REFINEMENTS`, actual
  ceiling is 6 at shipped defaults — see `search/core.py` refinement loop).
- `common/config/_settings.py` — `_default_models_for` (openai branch); reasoning-effort
  defaults (OCR/classify/judge); `OCR_REASONING_EFFORT` Literal type; new
  `OPENAI_FLEX_TIER: bool` field + `_get_bool_env` wiring; stale judge-model docstring.
- `common/config/_catalogue.py` — `OPENAI_FLEX_TIER` into `CONFIG_KEYS`.
- `common/llm.py` — `service_tier` into `_STRIPPABLE_PARAMS`; flex-aware patient-429 retry
  path; **boy-scout:** the "MUST be verified against a real 400" comment above the matchers
  can now cite live verification for `reasoning_effort` and `temperature` (2026-07-15).
- `ocr/provider.py` — params dict: explicit `service_tier`, flex timeout.
- `classifier/provider.py` — `_build_params`: same.
- `search/planner.py`, `search/judge.py`, `search/synthesizer.py` — explicit
  `service_tier: "default"` (via the shared optional-params helper in `llm.py`).
- `search/pricing.py` — D9.
- `search/settings_service.py` — **boy-scout:** stale comment claiming `EMBEDDING_PROVIDER`
  follows `LLM_PROVIDER` (it hard-defaults to `openai`).

Web (`web/src/features/settings/`):
- `fieldModel/sections.ts` — `MODEL_OPTIONS` trio; `REASONING_EFFORT_OPTIONS` five values;
  Flex toggle field in Connections → OpenAI subsection; stale option-docstring fix.

KB (`.claude/`):
- `GATES.md` — create (mandatory, currently missing); gates = pytest, mypy, ruff
  check/format, bandit, web typecheck/lint/test:coverage/build, per `docs/TESTING.md`.
- `DECISIONS.md` — entry citing this spec.
- KB docs reconciled at push by kb-updater (diff mode) per the standard gate.

## Testing requirements

Regression tests ship in the same branch; a fix without a failing-first test is an assertion.

- Choice set: `none`/`xhigh` now parse; `max`/`""` still raise; `minimal` coerces to `none`
  with a warning (assert the log), for OCR + classify + all three search stages.
- Existing pinned tests flip: `test_invalid_reasoning_effort_raises` (parametrised
  `none`/`xhigh`/`""`), `TestOcrReasoningEffort.test_accepts_each_allowed_value`.
- Defaults: `_default_models_for` openai assertions updated; judge effort default `none`;
  classify default `low`; OCR default `none`.
- Flex: toggle default true; OCR/classifier params carry `service_tier:"flex"` + raised
  timeout when on, `"default"` + `REQUEST_TIMEOUT` when off; Ollama provider sends no
  `service_tier`; search stages always send `"default"`.
- Patient 429: flex call retries `RateLimitError` beyond `MAX_RETRIES` without model
  fallback or error tag, backoff capped, aborts on shutdown signal; non-flex 429 keeps
  today's budget; non-429 flex errors keep fallback/error-tag.
- Strip layer: `service_tier` strippable-registry entry (update the six-params-pinning test).
- Pricing: rows exist and are typed for the trio; `SEED_PRICES_AS_OF` is an ISO date.
- Web: pin `MODEL_OPTIONS` and `REASONING_EFFORT_OPTIONS` contents (nothing pins them
  today); Flex toggle field present, kind `toggle`, in the OpenAI subsection.

## Rollout

Branch `feat/flex-and-56-models` → PR referencing this spec → **operator merges** → watchtower
deploys to the NAS. Code defaults only apply where the config table has no stored value:
stored model choices don't jump; stages with unset efforts pick up new defaults immediately
(operator's stated intent). Operator then updates stored model/effort values in the settings
UI. `.env` untouched throughout. After deploy, compare OCR reasoning-token usage on the
OpenAI dashboard against pre-change (the app cannot measure it — non-goal 1).

## Open risks

1. Flex capacity-429's exact exception class (`RateLimitError` assumed from the docs' "429
   resource_unavailable") — confirm the SDK mapping when implementing the patient loop; if it
   ever surfaces as anything else, the loop must key on status 429, not the class name alone.
2. The 401 quirk may be specific to the verification key's scoping; prod's key may never hit
   it. Explicit `service_tier` is correct regardless.
3. A long OpenAI capacity outage stalls OCR/classifier worker threads (accepted in D5); the
   daemons' existing heartbeat/health surfaces would show the stall.
