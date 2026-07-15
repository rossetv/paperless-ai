# Flex Tier + GPT-5.6 Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt GPT-5.6 defaults, refresh the reasoning-effort choice set (add `none`/`xhigh`, drop `minimal`), and run OCR + classifier on OpenAI's Flex tier behind a default-on settings toggle with retry-until-done 429 semantics.

**Architecture:** All LLM traffic funnels through `OpenAIChatMixin` in `src/common/llm.py`; config is a DB-backed `Settings` object rebuilt on `config_version` bumps (hot-reload, no restart). Changes are: one new boolean config key, param-assembly changes at the OCR/classifier/search call sites, a patient-429 branch in the shared compat layer, and constant/default updates in config + pricing + web field model.

**Tech Stack:** Python 3.11, pytest (+xdist), mypy, ruff, openai SDK ~1.x (Chat Completions only), React/TS + vitest for `web/`.

**Spec:** `.claude/specs/20260715-flex-and-56-models.md` — decisions D1–D10 are settled; do not re-litigate.

## Global Constraints

- Branch: `feat/flex-and-56-models`. NEVER push to `main` — push to `main` is a production deploy (watchtower).
- Conventional Commits, imperative, lowercase, no AI attribution.
- British English in prose/comments; code identifiers follow existing convention.
- Reasoning-effort choice set is exactly `{none, low, medium, high, xhigh}` — `max` is deliberately excluded (live API rejects it on every 5.6 model; docs are wrong).
- New OpenAI defaults: OCR `[gpt-5.6-luna, gpt-5.6-terra]` @ `none`; classify `[gpt-5.6-luna, gpt-5.6-terra]` @ `low`; planner `gpt-5.6-terra` @ `medium`; judge `gpt-5.6-luna` @ `none`; answer `gpt-5.6-terra` @ `medium`. Ollama defaults untouched.
- Flex applies ONLY to OCR + classifier, ONLY when that step's provider is `openai`. Search stages always send explicit `service_tier: "default"` when on openai, never flex.
- Every task: run its named tests before committing. Full gates run at the end (Task 11).
- Test commands: `python -m pytest <path> -v` (unit), whole suite `python -m pytest -n auto`; web from `web/`: `npm run test`, `npm run typecheck`.

---

### Task 1: Reasoning-effort choice set + `minimal` coercion

**Files:**
- Modify: `src/common/config/_parsers.py` (`_REASONING_EFFORT_CHOICES`, `_resolve_reasoning_effort`, `_resolve_ocr_reasoning_effort`)
- Modify: `src/common/config/_settings.py` (`OCR_REASONING_EFFORT` field type, around line 201)
- Test: `tests/unit/common/test_config.py`, `tests/unit/common/test_config_search.py`

**Interfaces:**
- Produces: `_resolve_reasoning_effort` accepting/returning values from `{none, low, medium, high, xhigh}`, coercing the literal string `"minimal"` to `"none"` with a `structlog` warning. `Settings.OCR_REASONING_EFFORT: Literal["none", "low", "medium", "high", "xhigh"]`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/common/test_config.py`, find `TestValidation.test_invalid_reasoning_effort_raises` (currently parametrised `["none", "xhigh", ""]`) and `TestOcrReasoningEffort.test_accepts_each_allowed_value` (currently parametrised `["minimal", "low", "medium", "high"]`). Replace/extend them (follow the file's existing `_build(mocker, {...})` helper conventions):

```python
@pytest.mark.parametrize("value", ["max", "medium-rare", ""])
def test_invalid_reasoning_effort_raises(self, mocker, value):
    with pytest.raises(
        ValueError, match="CLASSIFY_REASONING_EFFORT must be one of"
    ):
        _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_REASONING_EFFORT": value})

@pytest.mark.parametrize("value", ["none", "low", "medium", "high", "xhigh"])
def test_accepts_each_allowed_value(self, mocker, value):
    settings = _build(mocker, {**_MINIMAL_ENV, "OCR_REASONING_EFFORT": value})
    assert settings.OCR_REASONING_EFFORT == value

def test_minimal_coerces_to_none_with_warning(self, mocker):
    settings = _build(mocker, {**_MINIMAL_ENV, "OCR_REASONING_EFFORT": "minimal"})
    assert settings.OCR_REASONING_EFFORT == "none"

def test_minimal_coerces_for_classify_too(self, mocker):
    settings = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_REASONING_EFFORT": "minimal"})
    assert settings.CLASSIFY_REASONING_EFFORT == "none"
```

NOTE: `""` (blank) currently raises because `"".strip().lower()` is not in the choices — keep that pinned. In `tests/unit/common/test_config_search.py`, the judge-block `test_invalid_reasoning_effort_raises` (~line 335) and `TestSearchRagCostSettings.test_invalid_reasoning_effort_fails_closed` (~line 194) use invalid values — if they use `"none"`/`"xhigh"` as the invalid probe, switch the probe to `"max"`. Adapt names/placement to the classes that already exist; keep one coercion test per resolver family (OCR, classify, one search stage).

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest tests/unit/common/test_config.py -v -k "reasoning"`
Expected: new tests FAIL (`none`/`xhigh` rejected today, `minimal` accepted); old pins on `none`/`xhigh` now-inverted assertions fail.

- [ ] **Step 3: Implement**

In `src/common/config/_parsers.py`, replace the block at lines 245–251:

```python
# Allowed reasoning-effort values. Matches the live OpenAI API (verified
# 2026-07-15 with one test call per value against gpt-5.6-sol/-terra/-luna and
# gpt-5.4-mini): every current model reports supported values
# none/low/medium/high/xhigh. "minimal" is gone from every current model and
# is coerced to "none" below for configs saved before this change. "max" is
# deliberately absent: the docs' model-index chips list it but the live API
# rejects it on every 5.6 model, and a rejected effort gets stripped by the
# compat layer so the model silently runs at its own default ("medium") —
# more expensive than the operator asked for. Do not add values from docs
# alone; verify against the live API first.
_REASONING_EFFORT_CHOICES: frozenset[str] = frozenset(
    {"none", "low", "medium", "high", "xhigh"}
)
```

Add near the top of the file (after the existing imports; the module currently imports no logger):

```python
import structlog

log = structlog.get_logger(__name__)
```

In `_resolve_reasoning_effort`, insert the coercion between the normalise line and the membership check (keep the docstring's first paragraphs; update its `low` / `minimal` example wording to `("none" / "low")`):

```python
    effort = source.get(var_name, default).strip().lower()
    if effort == "minimal":
        # Legacy tier removed by OpenAI (verified 2026-07-15). Validation
        # fails closed at daemon startup AND on every Settings save, so
        # raising here would brick a stored config the UI could no longer
        # edit. "none" is the nearest current tier — minimal sat below "low"
        # on the old scale.
        log.warning(
            "config.reasoning_effort_minimal_coerced",
            var_name=var_name,
            coerced_to="none",
        )
        effort = "none"
    if effort not in _REASONING_EFFORT_CHOICES:
```

In `_resolve_ocr_reasoning_effort`, update the return annotation to `Literal["none", "low", "medium", "high", "xhigh"]` (docstring default text is updated in Task 2 — leave the default alone in this task).

In `src/common/config/_settings.py` line 201, change the field to:

```python
    OCR_REASONING_EFFORT: Literal["none", "low", "medium", "high", "xhigh"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/common/test_config.py tests/unit/common/test_config_search.py -v` then `mypy src`
Expected: PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/common/config/_parsers.py src/common/config/_settings.py tests/unit/common/test_config.py tests/unit/common/test_config_search.py
git commit -m "feat(config): refresh reasoning-effort choices to live openai set"
```

---

### Task 2: New model and effort defaults

**Files:**
- Modify: `src/common/config/_settings.py` (`_default_models_for` lines 103–126; judge-model docstring ~307–310; `SEARCH_JUDGE_REASONING_EFFORT` docstring ~312)
- Modify: `src/common/config/_parsers.py` (`_resolve_ocr_reasoning_effort` default, `_resolve_classify_reasoning_effort` default)
- Modify: `src/common/config/_settings.py` judge wiring (line ~798: `default="low"` → `default="none"`)
- Test: `tests/unit/common/test_config.py`, `tests/unit/common/test_config_search.py`

**Interfaces:**
- Produces: openai defaults — `ocr_models=["gpt-5.6-luna", "gpt-5.6-terra"]`, `classify_models=["gpt-5.6-luna", "gpt-5.6-terra"]`, `planner_model="gpt-5.6-terra"`, `answer_model="gpt-5.6-terra"`, `judge_model="gpt-5.6-luna"`; effort defaults OCR=`none`, classify=`low`, judge=`none` (planner/answer stay `medium`).

- [ ] **Step 1: Update the default-pinning tests to the new values (failing first)**

In `tests/unit/common/test_config.py`: `test_ocr_and_classify_models_default_openai` (~L82), `test_model_default_follows_step_provider` (~L983), `test_search_model_default_follows_step_provider` (~L992), and `TestOcrReasoningEffort.test_defaults_to_medium` (~L419 — rename to `test_defaults_to_none`, assert `"none"`). In `tests/unit/common/test_config_search.py`: `TestSearchRagCostSettings.test_reasoning_effort_defaults` (~L170 — planner/answer stay `"medium"`), judge `test_reasoning_effort_defaults_to_low` (~L325 — rename to `test_reasoning_effort_defaults_to_none`, assert `"none"`), `test_judge_model_defaults_to_planner_model_openai` (~L311 — judge default is now `gpt-5.6-luna` while planner defaults `gpt-5.6-terra`; the judge default NO LONGER equals the planner default on openai — rewrite the test to assert the two literal values, and rename it, e.g. `test_judge_and_planner_openai_defaults`). Keep the ollama variants asserting the unchanged gemma values. Assert classify effort default:

```python
def test_classify_reasoning_effort_defaults_to_low(self, mocker):
    settings = _build(mocker, _MINIMAL_ENV)
    assert settings.CLASSIFY_REASONING_EFFORT == "low"
```

- [ ] **Step 2: Run to verify the updated tests fail**

Run: `python -m pytest tests/unit/common/test_config.py tests/unit/common/test_config_search.py -v -k "default"`
Expected: FAIL on every updated assertion (old defaults still coded).

- [ ] **Step 3: Implement**

`src/common/config/_settings.py` `_default_models_for`, openai branch becomes:

```python
    return _ProviderDefaults(
        ocr_models=["gpt-5.6-luna", "gpt-5.6-terra"],
        classify_models=["gpt-5.6-luna", "gpt-5.6-terra"],
        planner_model="gpt-5.6-terra",
        answer_model="gpt-5.6-terra",
        judge_model="gpt-5.6-luna",
    )
```

Update the `SEARCH_JUDGE_MODEL` field docstring (~line 307) — it currently claims the judge defaults to the planner model (`gpt-5.4-mini` / `gemma3:12b`); the openai default is now `gpt-5.6-luna` (ollama still follows the planner default `gemma3:12b`). Update the `SEARCH_JUDGE_REASONING_EFFORT` docstring (~line 312) — the effort list becomes `` `none`/`low`/`medium`/`high`/`xhigh` `` and "Defaults to `none`".

`_parsers.py`:
- `_resolve_ocr_reasoning_effort`: delegate with `default="none"` and rewrite the docstring — OCR is perception, not reasoning; `none` spends zero reasoning tokens on the highest-volume call; verified accepted by the live API 2026-07-15:

```python
def _resolve_ocr_reasoning_effort(
    source: Mapping[str, str],
) -> Literal["none", "low", "medium", "high", "xhigh"]:
    """Resolve and validate ``OCR_REASONING_EFFORT`` (defaults to ``none``).

    Transcription is perception, not reasoning, and OCR is the highest-volume
    call in the system (one per page), so the default spends zero reasoning
    tokens. An operator opts *up* to ``low``+ if transcription quality on
    complex layouts ever warrants it.
    """
    # rationale: validated by shared helper; mypy cannot narrow `str` → `Literal[...]`.
    return _resolve_reasoning_effort(source, "OCR_REASONING_EFFORT", default="none")  # type: ignore[return-value]
```

- `_resolve_classify_reasoning_effort`: delegate with `default="low"`, docstring "(defaults to ``low``)" — schema-constrained extraction needs little deliberation.

`_settings.py` judge wiring line ~798: `default="low"` → `default="none"`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/common/test_config.py tests/unit/common/test_config_search.py -v` then `mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/common/config/_settings.py src/common/config/_parsers.py tests/unit/common/test_config.py tests/unit/common/test_config_search.py
git commit -m "feat(config): default the pipeline onto gpt-5.6 luna/terra"
```

---

### Task 3: `OPENAI_FLEX_TIER` setting

**Files:**
- Modify: `src/common/config/_catalogue.py` (`CONFIG_KEYS`)
- Modify: `src/common/config/_settings.py` (field + wiring)
- Test: `tests/unit/common/test_config.py`

**Interfaces:**
- Produces: `Settings.OPENAI_FLEX_TIER: bool`, default `True`, hot-reloadable like every config-table key. Tasks 4–5 and 8 consume it.

- [ ] **Step 1: Failing tests**

```python
class TestOpenAiFlexTier:
    def test_defaults_to_true(self, mocker):
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.OPENAI_FLEX_TIER is True

    def test_can_be_disabled(self, mocker):
        settings = _build(mocker, {**_MINIMAL_ENV, "OPENAI_FLEX_TIER": "false"})
        assert settings.OPENAI_FLEX_TIER is False

    def test_is_a_config_table_key(self):
        from common.config._catalogue import CONFIG_KEYS
        assert "OPENAI_FLEX_TIER" in CONFIG_KEYS
```

(Match the file's existing class/fixture style; there may be an existing test asserting the full CONFIG_KEYS census — if one pins a count or set, update it.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/common/test_config.py -v -k "flex"`
Expected: FAIL (`Settings` has no field, key not in catalogue).

- [ ] **Step 3: Implement**

`_catalogue.py`: in `CONFIG_KEYS`, directly under `"OPENAI_API_KEY",` add `"OPENAI_FLEX_TIER",`.

`_settings.py`: add the field after `LLM_MAX_CONCURRENT` (line ~183):

```python
    OPENAI_FLEX_TIER: bool
    """Run OCR and classifier OpenAI calls on the Flex service tier.

    Flex bills at ~50% of standard rates in exchange for slower responses and
    occasional capacity 429s (which the compat layer waits out — see
    ``common.llm``). Applies only to the two background daemons and only when
    that step's provider is ``openai``; the interactive search stages always
    use the standard tier. Default on — the discount is the point.
    """
```

Wiring, next to the other `_get_bool_env` lines in `_build_settings` (after `LLM_MAX_CONCURRENT=` line ~698):

```python
        OPENAI_FLEX_TIER=_get_bool_env(source, "OPENAI_FLEX_TIER", True),
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/common/test_config.py -v` then `mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/common/config/_catalogue.py src/common/config/_settings.py tests/unit/common/test_config.py
git commit -m "feat(config): add OPENAI_FLEX_TIER toggle, default on"
```

---

### Task 4: `service_tier` plumbing — helper, strippable registry, OCR + classifier params

**Files:**
- Modify: `src/common/llm.py` (`_STRIPPABLE_PARAMS`, new module constant + helper)
- Modify: `src/ocr/provider.py` (params dict in `transcribe_image`, lines 142–150)
- Modify: `src/classifier/provider.py` (`_build_params`, lines 176–203)
- Test: `tests/unit/common/test_llm.py`, `tests/unit/ocr/test_provider.py`, `tests/unit/classifier/test_provider.py` (follow each file's existing fixture style; classifier provider tests may live in `test_provider.py` + `test_provider_compat.py` — check both)

**Interfaces:**
- Produces: `common.llm.service_tier_params(*, flex_enabled: bool, request_timeout: int) -> dict[str, object]` returning `{"service_tier": "flex", "timeout": max(request_timeout, 600)}` or `{"service_tier": "default", "timeout": request_timeout}`. Constant `FLEX_MIN_TIMEOUT_SECONDS = 600`. Registry row `("service_tier", "service_tier", "service_tier_retries")`.
- Consumes: `Settings.OPENAI_FLEX_TIER` (Task 3).

- [ ] **Step 1: Failing tests**

`tests/unit/common/test_llm.py` — the registry-pinning test `test_registry_param_keys_are_the_six_documented` (line ~281) pins the param set; add `service_tier` to its expected set and rename it (`test_registry_param_keys_are_the_seven_documented`). Add:

```python
class TestServiceTierParams:
    def test_flex_enabled_floors_timeout(self):
        assert service_tier_params(flex_enabled=True, request_timeout=180) == {
            "service_tier": "flex",
            "timeout": 600,
        }

    def test_flex_enabled_keeps_larger_operator_timeout(self):
        assert service_tier_params(flex_enabled=True, request_timeout=900) == {
            "service_tier": "flex",
            "timeout": 900,
        }

    def test_flex_disabled_is_standard_tier(self):
        assert service_tier_params(flex_enabled=False, request_timeout=180) == {
            "service_tier": "default",
            "timeout": 180,
        }
```

OCR provider tests: assert the outgoing params (the existing tests capture `_create_with_compat` calls — follow that pattern): openai provider + flex on → `params["service_tier"] == "flex"` and `params["timeout"] == 600`; flex off → `"default"` + `timeout == settings.REQUEST_TIMEOUT`; ollama provider → `"service_tier" not in params`. Same three assertions for the classifier via `_build_params` (it's a pure method — call it directly).

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/common/test_llm.py tests/unit/ocr/test_provider.py tests/unit/classifier/ -v -k "service_tier or seven or flex"`
Expected: FAIL (`service_tier_params` undefined, registry has 8 rows/6 params, no service_tier in provider params).

- [ ] **Step 3: Implement**

`src/common/llm.py` — append to `_STRIPPABLE_PARAMS` (after the `verbosity` row):

```python
    ("service_tier", "service_tier", "service_tier_retries"),
```

Below the registry (module level), add:

```python
# Flex requests routinely run longer than standard-tier ones — OpenAI's own
# default timeout for them is 10 minutes — so flex calls floor their per-call
# timeout here instead of raising the global REQUEST_TIMEOUT (which would drag
# interactive search calls with it).
FLEX_MIN_TIMEOUT_SECONDS = 600


def service_tier_params(
    *, flex_enabled: bool, request_timeout: int
) -> dict[str, object]:
    """``service_tier`` + ``timeout`` params for an OpenAI background-daemon call.

    Always names a tier explicitly — even ``"default"``. Verified live
    (2026-07-15): a 5.6 request with ``reasoning_effort: "none"`` and *no*
    ``service_tier`` was rejected 401 by the API while the identical request
    with an explicit tier succeeded; explicit is also deterministic and free.
    """
    if flex_enabled:
        return {
            "service_tier": "flex",
            "timeout": max(request_timeout, FLEX_MIN_TIMEOUT_SECONDS),
        }
    return {"service_tier": "default", "timeout": request_timeout}
```

`src/ocr/provider.py` — import `service_tier_params` from `common.llm` (extend the existing `from common.llm import ...` line) and change the params build in `transcribe_image`:

```python
        for model in models_to_try:
            params: dict[str, object] = {
                "model": model,
                "messages": messages,
                "timeout": self.settings.REQUEST_TIMEOUT,
            }
            reasoning_effort = self._reasoning_effort()
            if reasoning_effort is not None:
                params["reasoning_effort"] = reasoning_effort
            if self.settings.OCR_PROVIDER == "openai":
                params.update(
                    service_tier_params(
                        flex_enabled=self.settings.OPENAI_FLEX_TIER,
                        request_timeout=self.settings.REQUEST_TIMEOUT,
                    )
                )
```

`src/classifier/provider.py` — same import; in `_build_params`, inside the existing `if self.settings.CLASSIFY_PROVIDER == "openai":` block add:

```python
            params.update(
                service_tier_params(
                    flex_enabled=self.settings.OPENAI_FLEX_TIER,
                    request_timeout=self.settings.REQUEST_TIMEOUT,
                )
            )
```

Extend `_build_params`'s docstring: service_tier is provider-gated like `reasoning_effort`; flex floors the timeout.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/common/test_llm.py tests/unit/ocr/ tests/unit/classifier/ -v` then `mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/common/llm.py src/ocr/provider.py src/classifier/provider.py tests/unit/common/test_llm.py tests/unit/ocr/test_provider.py tests/unit/classifier/
git commit -m "feat(llm): send explicit service_tier; flex on ocr+classifier"
```

---

### Task 5: Patient flex-429 retry in `_create_with_compat`

**Files:**
- Modify: `src/common/llm.py` (`_create_with_compat`, new `_wait_for_flex_capacity` helper, imports)
- Test: `tests/unit/common/test_llm.py` (`TestCreateWithCompat` has the fixture patterns for fake errors/providers)

**Interfaces:**
- Consumes: `common.shutdown.is_shutdown_requested` (existing), `params["service_tier"]` (Task 4).
- Produces: flex calls never return `None` on `openai.RateLimitError` unless shutdown is requested; non-flex 429 behaviour unchanged.

- [ ] **Step 1: Failing tests**

Follow `TestCreateWithCompat`'s existing style for constructing a provider and fake `openai` errors (`openai.RateLimitError` needs `message`, `response`, `body` — copy how the file already builds `BadRequestError`; use `httpx.Response(429, request=httpx.Request("POST", "http://t"))` if no helper exists). Patch sleeping so tests are instant:

```python
class TestFlexCapacityPatience:
    def test_flex_429_retries_until_success(self, provider, mocker):
        mocker.patch("common.llm._wait_for_flex_capacity", return_value=True)
        completion = _fake_completion("ok")
        provider._create_completion = mocker.Mock(
            side_effect=[_rate_limit_error(), _rate_limit_error(), completion]
        )
        result = provider._create_with_compat(
            {"model": "m", "messages": [], "service_tier": "flex"}, "m"
        )
        assert result is completion
        assert provider._create_completion.call_count == 3

    def test_flex_429_backoff_doubles_and_caps(self, provider, mocker):
        waits = mocker.patch("common.llm._wait_for_flex_capacity", return_value=True)
        provider._create_completion = mocker.Mock(
            side_effect=[_rate_limit_error()] * 8 + [_fake_completion("ok")]
        )
        provider._create_with_compat(
            {"model": "m", "messages": [], "service_tier": "flex"}, "m"
        )
        waited = [call.args[0] for call in waits.call_args_list]
        assert waited == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]

    def test_flex_429_aborts_on_shutdown(self, provider, mocker):
        mocker.patch("common.llm._wait_for_flex_capacity", return_value=False)
        provider._create_completion = mocker.Mock(side_effect=_rate_limit_error())
        result = provider._create_with_compat(
            {"model": "m", "messages": [], "service_tier": "flex"}, "m"
        )
        assert result is None

    def test_non_flex_429_stays_terminal(self, provider, mocker):
        wait = mocker.patch("common.llm._wait_for_flex_capacity")
        provider._create_completion = mocker.Mock(side_effect=_rate_limit_error())
        result = provider._create_with_compat({"model": "m", "messages": []}, "m")
        assert result is None
        wait.assert_not_called()
```

Also add a unit test for the sleeper itself (patch `common.llm.is_shutdown_requested` and `time.sleep`):

```python
class TestWaitForFlexCapacity:
    def test_returns_true_when_no_shutdown(self, mocker):
        mocker.patch("common.llm.is_shutdown_requested", return_value=False)
        sleep = mocker.patch("common.llm.time.sleep")
        assert _wait_for_flex_capacity(3.0) is True
        assert sleep.called

    def test_returns_false_immediately_on_shutdown(self, mocker):
        mocker.patch("common.llm.is_shutdown_requested", return_value=True)
        sleep = mocker.patch("common.llm.time.sleep")
        assert _wait_for_flex_capacity(3.0) is False
        sleep.assert_not_called()
```

(For the deadline arithmetic, patch `time.monotonic` with an itertools counter if needed — keep the test deterministic, no real sleeping.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/common/test_llm.py -v -k "flex or Flex"`
Expected: FAIL (`_wait_for_flex_capacity` undefined; flex 429 currently returns `None` after one strip-loop pass).

- [ ] **Step 3: Implement**

`src/common/llm.py` — imports: add `import time` and `from .shutdown import is_shutdown_requested`. Module constant near `FLEX_MIN_TIMEOUT_SECONDS`:

```python
# Capacity-429 backoff for flex calls: exponential from 1s, capped here. The
# cap keeps the daemon responsive to recovered capacity without hammering the
# API during an outage.
_FLEX_BACKOFF_CAP_SECONDS = 60.0


def _wait_for_flex_capacity(wait_seconds: float) -> bool:
    """Sleep *wait_seconds* in ≤1s slices; ``False`` if shutdown interrupts.

    Chunked so a SIGTERM lands within ~1s instead of a full backoff interval —
    a hung shutdown would end in SIGKILL, and a SIGKILL mid-claim leaves the
    document skipped as "already claimed" on every later poll.
    """
    deadline = time.monotonic() + wait_seconds
    while True:
        if is_shutdown_requested():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(1.0, remaining))
```

Rework `_create_with_compat`'s loop. The bounded `for` becomes an unbounded `while` whose *strip* budget is counted explicitly (the strip bound still holds — only flex-429 waits are unbounded). Replace the whole loop body (keep the docstring, extending it with a **Flex patience** paragraph: on a flex call, a `RateLimitError` is a capacity signal, not a model failure — wait and retry the same model indefinitely, aborting only on daemon shutdown; decision D5 in the spec):

```python
        params = self._pre_strip_known_rejected(params, model)
        strip_attempts = 0
        flex_wait = 1.0
        while True:
            try:
                self._record_attempt()
                return self._create_completion(**params)
            except openai.BadRequestError as error:
                strip_attempts += 1
                if strip_attempts > len(_STRIPPABLE_PARAMS):
                    log.warning("llm.request_rejected_after_strips", model=model)
                    self._record_api_error()
                    return None
                stripped_params = self._strip_rejected_param(error, params, model)
                if stripped_params is None:
                    log.warning("llm.request_rejected", model=model, error=str(error))
                    self._record_api_error()
                    return None
                params = stripped_params
            except openai.RateLimitError as error:
                if params.get("service_tier") != "flex":
                    log.warning("llm.model_failed", model=model, error=str(error))
                    self._record_api_error()
                    return None
                # Flex capacity shortage: unbilled, transient, and not a model
                # failure — advancing the fallback chain or error-tagging the
                # document would be wrong. Wait it out (spec D5).
                log.warning(
                    "llm.flex_capacity_wait",
                    model=model,
                    wait_seconds=flex_wait,
                    error=str(error),
                )
                if not _wait_for_flex_capacity(flex_wait):
                    log.warning("llm.flex_wait_aborted_by_shutdown", model=model)
                    self._record_api_error()
                    return None
                flex_wait = min(flex_wait * 2, _FLEX_BACKOFF_CAP_SECONDS)
            except openai.APIError as error:
                log.warning("llm.model_failed", model=model, error=str(error))
                self._record_api_error()
                return None
```

Exception-order note (add as a comment if not obvious in context): `RateLimitError` must be caught before the generic `APIError` (it subclasses it), and after `BadRequestError` (they're siblings — order between those two is immaterial, but keep BadRequest first to match the docstring's phase description). The `@retry` on `_create_completion` still burns its `MAX_RETRIES` budget inside every patient iteration — that's harmless (a few extra unbilled requests) and keeps the layers decoupled; note it in the docstring.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/common/test_llm.py tests/unit/common/test_model_compat.py -v` then `mypy src`
Expected: PASS, including the untouched `TestCreateWithCompat` strip tests (the rework must not change strip semantics — if any fail, the rework is wrong, not the test).

- [ ] **Step 5: Commit**

```bash
git add src/common/llm.py tests/unit/common/test_llm.py
git commit -m "feat(llm): wait out flex capacity 429s instead of failing the model"
```

---

### Task 6: Search stages send explicit `service_tier: "default"`

**Files:**
- Modify: `src/common/llm.py` (`_optional_completion_params`, `_complete_with_model_fallback`)
- Modify: `src/search/planner.py` (~line 215), `src/search/judge.py` (~line 131), `src/search/synthesizer.py` (~line 161)
- Test: `tests/unit/common/test_llm.py`, plus the planner/judge/synthesizer unit tests (`tests/unit/search/`) that capture outgoing params

**Interfaces:**
- Produces: `_complete_with_model_fallback(..., service_tier: str | None = None)`; `_optional_completion_params(..., service_tier: str | None)`. Callers pass `"default"` when their stage provider is `"openai"`, else `None` (param omitted).

- [ ] **Step 1: Failing tests**

In `tests/unit/common/test_llm.py`, extend the `_optional_completion_params` / fallback-chain tests: `service_tier="default"` appears in outgoing params; `service_tier=None` omits the key (the existing no-arg characterisation test must keep passing — `None` default means unchanged behaviour). In each of the three stage test files, add an assertion on the captured completion params: openai-provider stage → `params["service_tier"] == "default"`; ollama-provider stage → key absent. Follow how those tests already assert `reasoning_effort` gating — mirror one existing gating test per stage.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/common/test_llm.py tests/unit/search/test_planner.py tests/unit/search/test_judge.py tests/unit/search/test_synthesizer.py -v -k "service_tier"`
Expected: FAIL (unknown kwarg).

- [ ] **Step 3: Implement**

`_optional_completion_params` gains the candidate:

```python
    @staticmethod
    def _optional_completion_params(
        *,
        reasoning_effort: str | None,
        response_format: dict[str, object] | None,
        timeout: float | None,
        service_tier: str | None = None,
    ) -> dict[str, object]:
        """Build the dict of optional completion params, dropping every ``None``."""
        candidates: dict[str, object | None] = {
            "reasoning_effort": reasoning_effort,
            "response_format": response_format,
            "timeout": timeout,
            "service_tier": service_tier,
        }
        return {key: value for key, value in candidates.items() if value is not None}
```

`_complete_with_model_fallback` signature gains `service_tier: str | None = None` (after `timeout`), forwards it into `_optional_completion_params`, and its docstring's optional-params paragraph and Args section name it: always `"default"` from the search stages — never flex, a human is waiting (spec D3/D4); explicit because a live call with an effort but no tier was rejected 401 (2026-07-15).

Each of the three call sites adds one argument (planner shown; judge and synthesizer are identical with their own `SEARCH_*_PROVIDER`):

```python
            # Explicit standard tier on OpenAI — never flex here (a human is
            # waiting), and an explicit tier dodges the live-verified 401 on
            # tierless requests (spec D4). Omitted for non-OpenAI providers.
            service_tier=(
                "default"
                if self.settings.SEARCH_PLANNER_PROVIDER == "openai"
                else None
            ),
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/common/test_llm.py tests/unit/search/ -v` then `mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/common/llm.py src/search/planner.py src/search/judge.py src/search/synthesizer.py tests/unit/common/test_llm.py tests/unit/search/
git commit -m "feat(search): pin search stages to the standard service tier"
```

---

### Task 7: Pricing rows for the 5.6 family

**Files:**
- Modify: `src/search/pricing.py` (`MODEL_PRICES`, `SEED_PRICES_AS_OF`, the header comment)
- Test: `tests/unit/search/test_pricing.py`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.parametrize(
    ("model", "input_rate", "output_rate"),
    [
        ("gpt-5.6-sol", 5.0, 30.0),
        ("gpt-5.6-terra", 2.5, 15.0),
        ("gpt-5.6-luna", 1.0, 6.0),
    ],
)
def test_gpt56_family_is_priced(model, input_rate, output_rate):
    price = MODEL_PRICES[model]
    assert price.input_per_mtok == input_rate
    assert price.output_per_mtok == output_rate
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/search/test_pricing.py -v`
Expected: FAIL with `KeyError: 'gpt-5.6-sol'`.

- [ ] **Step 3: Implement**

Add three rows at the top of `MODEL_PRICES` (keep every existing row — prod still runs on them until the operator flips stored settings):

```python
MODEL_PRICES: dict[str, ModelPrice] = {
    "gpt-5.6-sol": ModelPrice(input_per_mtok=5.0, output_per_mtok=30.0),
    "gpt-5.6-terra": ModelPrice(input_per_mtok=2.5, output_per_mtok=15.0),
    "gpt-5.6-luna": ModelPrice(input_per_mtok=1.0, output_per_mtok=6.0),
    "gpt-5.5": ModelPrice(input_per_mtok=5.0, output_per_mtok=30.0),
    ...
```

Set `SEED_PRICES_AS_OF: str = "2026-07-14"`. Rewrite the header comment's provenance sentence: 5.4-era rows confirmed against the operator's account 2026-06-10; 5.6 rows taken from the live pricing docs 2026-07-14. Keep the cached-input-not-modelled paragraph. Add one sentence: Flex halves the actual OCR/classifier spend, but this table prices only the search path, which never uses Flex — no Flex modelling needed.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/search/test_pricing.py -v`
Expected: PASS (including `test_seed_prices_as_of_is_an_iso_date`).

- [ ] **Step 5: Commit**

```bash
git add src/search/pricing.py tests/unit/search/test_pricing.py
git commit -m "feat(pricing): seed gpt-5.6 family rates"
```

---

### Task 8: Web field model — options, toggle, docstrings

**Files:**
- Modify: `web/src/features/settings/fieldModel/sections.ts` (`MODEL_OPTIONS`, `REASONING_EFFORT_OPTIONS`, the OpenAI connections group)
- Test: `web/src/features/settings/fieldModel.test.ts`

- [ ] **Step 1: Failing tests**

Nothing currently pins the option arrays — add pins plus the toggle presence (follow the file's existing `fieldByKey` helpers):

```ts
test('MODEL_OPTIONS is exactly the gpt-5.6 family', () => {
  expect(MODEL_OPTIONS.map((o) => o.value)).toEqual([
    'gpt-5.6-luna',
    'gpt-5.6-terra',
    'gpt-5.6-sol',
  ]);
});

test('REASONING_EFFORT_OPTIONS matches the live OpenAI effort set', () => {
  expect(REASONING_EFFORT_OPTIONS.map((o) => o.value)).toEqual([
    'none',
    'low',
    'medium',
    'high',
    'xhigh',
  ]);
});

test('OPENAI_FLEX_TIER renders as a toggle in the OpenAI connections group', () => {
  const field = fieldByKey('OPENAI_FLEX_TIER');
  expect(field?.control.kind).toBe('toggle');
});
```

(`MODEL_OPTIONS`/`REASONING_EFFORT_OPTIONS` are exported from `sections.ts` via the `fieldModel.ts` barrel — import accordingly. If `fieldByKey` is test-local, reuse however the existing tests resolve `SEARCH_GATE_JUDGE`.)

- [ ] **Step 2: Run to verify failure**

Run: from `web/`: `npm run test -- fieldModel`
Expected: FAIL (old option values; no OPENAI_FLEX_TIER field).

- [ ] **Step 3: Implement**

`sections.ts`:

```ts
export const MODEL_OPTIONS = [
  { value: 'gpt-5.6-luna', label: 'gpt-5.6-luna' },
  { value: 'gpt-5.6-terra', label: 'gpt-5.6-terra' },
  { value: 'gpt-5.6-sol', label: 'gpt-5.6-sol' },
];

/**
 * OpenAI reasoning-effort tiers, matching the live API's supported set
 * (verified 2026-07-15; the SDK's `ReasoningEffort` literal lags it). Higher
 * tiers spend more reasoning tokens for better quality; OpenAI-only — the
 * value is ignored when the provider is Ollama. Reused by the OCR,
 * classifier, and search planner/answer/judge reasoning selects.
 */
export const REASONING_EFFORT_OPTIONS = [
  { value: 'none', label: 'None' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'xhigh', label: 'XHigh' },
];
```

In the Connections section's `openai` group (line ~113), after the `OPENAI_API_KEY` field:

```ts
          {
            key: 'OPENAI_FLEX_TIER',
            label: 'Flex processing',
            hint: 'Run OCR and classification on the ~50%-cheaper Flex tier. Slower; waits out capacity shortages. Search always uses the standard tier.',
            control: { kind: 'toggle' },
          },
```

- [ ] **Step 4: Run tests + typecheck**

Run: from `web/`: `npm run test && npm run typecheck && npm run lint`
Expected: PASS. (If a test pins `allFieldKeys()` count or snapshot, update it for the new key.)

- [ ] **Step 5: Commit**

```bash
git add web/src/features/settings/fieldModel/sections.ts web/src/features/settings/fieldModel.test.ts
git commit -m "feat(web): gpt-5.6 options, live effort set, flex toggle"
```

---

### Task 9: Boy-scout — three comments that lie about the code

**Files:**
- Modify: `src/common/config/_parsers.py` (`_resolve_search_max_refinements` docstring)
- Modify: `src/search/settings_service.py` (comment near line 249)
- Modify: `src/common/llm.py` (the `rationale` comment above `_STRIPPABLE_PARAMS`)

No behaviour change — comment-only; no new tests. Verify each claim against the code before writing (read `src/search/core.py`'s refinement loop for the budget formula; read `_resolve_embedding_provider` in `_parsers.py`).

- [ ] **Step 1: Fix the per-query budget docstring**

`_resolve_search_max_refinements` currently claims "the per-query budget is ``2 + SEARCH_MAX_REFINEMENTS``". Replace that sentence with the real ceiling (verify in `src/search/core.py` around the refinement loop, anchor `SEARCH_MAX_REFINEMENTS`): planner + optional judge + synthesiser per pass, so the chat-call ceiling is ``(2 + j) × (1 + SEARCH_MAX_REFINEMENTS)`` where ``j`` is 1 when ``SEARCH_GATE_JUDGE`` is on — 6 calls at shipped defaults, not 3.

- [ ] **Step 2: Fix the embedding-provider comment**

`src/search/settings_service.py` (~line 249) claims `EMBEDDING_PROVIDER` follows `LLM_PROVIDER`. It does not — `_resolve_embedding_provider` in `_parsers.py` hard-defaults it to `"openai"`. Rewrite the comment to state that, citing `_resolve_embedding_provider` by name.

- [ ] **Step 3: Update the matcher-verification rationale**

The comment above `_STRIPPABLE_PARAMS` says the `reasoning_effort`/`verbosity`/`max_completion_tokens` matchers "MUST be verified against a real openai~=1.35 400 response before relying on them in production". Update it: `reasoning_effort` and `temperature` matchers verified against live gpt-5.6 400s on 2026-07-15 (both messages name the param verbatim); `verbosity` and `max_completion_tokens` remain best-effort/unverified.

- [ ] **Step 4: Run ruff + commit**

Run: `ruff check src tests && ruff format --check src && python -m pytest tests/unit/common/test_config.py -q`
Expected: clean.

```bash
git add src/common/config/_parsers.py src/search/settings_service.py src/common/llm.py
git commit -m "docs(code): correct three comments that lie about behaviour"
```

---

### Task 10: KB — GATES.md + DECISIONS.md + INDEX row

**Files:**
- Create: `.claude/GATES.md`
- Modify: `.claude/INDEX.md` (registry row), `.claude/DECISIONS.md` (append entry)

- [ ] **Step 1: Create `.claude/GATES.md`**

Content (commands verified against `.claude/docs/TESTING.md` and `.github/workflows/ci.yml` — re-verify before writing):

```markdown
<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md.
The definition of "done" in this repo: every gate below green before a PR is
opened or work is declared complete. Removing or editing a gate requires a
/panel and a DECISIONS.md entry; adding one is free. -->
↑ [INDEX](INDEX.md)

# paperless-ai — Gates

Run from the repo root unless stated. All must pass.

| # | Gate | Command |
|---|------|---------|
| 1 | Python tests | `python -m pytest -n auto` |
| 2 | Types | `mypy src` |
| 3 | Lint | `ruff check src tests && ruff format --check src tests` |
| 4 | Security | `bandit -r src/ -ll` |
| 5 | Web types | `cd web && npm run typecheck` |
| 6 | Web lint | `cd web && npm run lint` |
| 7 | Web tests + coverage floor | `cd web && npm run test:coverage` |
| 8 | Web build | `cd web && npm run build` |

Coverage as CI enforces it (gate 1 alternative when touching coverage-gated
packages): `python -m pytest -q -n auto --cov=common --cov=ocr --cov=classifier
--cov=store --cov=indexer --cov=search --cov-report=term-missing
--cov-fail-under=70`.

Known skip: 6 poppler-dependent OCR integration tests skip silently without
`pdftoppm` on PATH (`brew install poppler`).
```

- [ ] **Step 2: Register in `.claude/INDEX.md`**

Add a row to the "KB docs" table (after MEMORY): `| [GATES](GATES.md) | gate runbook — the definition of "done" | 2026-07-15 @ <current short sha> |`

- [ ] **Step 3: Append to `.claude/DECISIONS.md`**

```markdown
## 2026-07-15 — Adopt GPT-5.6, refresh reasoning efforts, add Flex tier

**Spec:** `.claude/specs/20260715-flex-and-56-models.md`
**Affects:** common/config, common/llm, ocr, classifier, search, web settings

OpenAI defaults move to gpt-5.6-luna/terra (Sol selectable, never default);
reasoning-effort choices become the live-verified {none, low, medium, high,
xhigh} with stored "minimal" coerced to "none"; OCR + classifier run on the
Flex service tier behind OPENAI_FLEX_TIER (default on) with
retry-until-done capacity-429 semantics; every OpenAI call names its
service_tier explicitly. "max" excluded — docs list it, live API rejects it.
Batch API, Responses API migration, and any embedding change rejected — see
spec D3/D10.
```

- [ ] **Step 4: Commit**

```bash
git add .claude/GATES.md .claude/INDEX.md .claude/DECISIONS.md
git commit -m "docs(kb): add gates runbook and flex/5.6 decision entry"
```

---

### Task 11: Full gates + integration sanity

- [ ] **Step 1: Run every gate from `.claude/GATES.md`**

All eight, in order. Expected: green. The e2e suites (`tests/e2e/`) exercise the OCR/classifier lifecycles against a stateful fake Paperless with scripted LLMs — they must pass untouched; if one fails on `service_tier`, the scripted LLM helper (`tests/helpers/llm.py`) may need to tolerate the new param — tolerate, never assert it away.

- [ ] **Step 2: Grep for stragglers**

`rg -n "minimal" src/ web/src/ --glob '!*.test.*'` — no remaining reasoning-effort reference to the dead tier (OCR image-detail "low" etc. are unrelated; judge by context). `rg -n "gpt-5.4-mini" src/ web/src/` — remaining hits must be pricing rows or historical comments only.

- [ ] **Step 3: Fix anything red, re-run, commit fixups**

Small fixes fold into a `fix:`/`test:` commit; anything structural goes back to the relevant task's file set.

---

## Execution notes

- Tasks 1→3 are sequential (each builds on the previous). Tasks 4→6 sequential (llm.py contention). Tasks 7, 8, 9, 10 are independent of each other and of 4–6 (7/9/10 touch disjoint files; 8 touches only web) — parallelise if using subagents, but never two agents in `src/common/llm.py` at once.
- After the branch merges and deploys, the operator updates stored settings in the UI; stages with *unset* efforts pick up new defaults immediately on deploy.
- The push gate (kb-gate) will demand a KB receipt on push — spawn kb-updater in diff mode then; PIPELINES/CONFIGURATION/modules docs will need the new key and defaults reflected.
