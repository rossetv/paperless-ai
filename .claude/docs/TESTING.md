<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../INDEX.md)

# Testing

## Facts

### Python suite

| Item | Value | Source |
|------|-------|--------|
| Runner | pytest; `pythonpath = ["src"]`, `testpaths = ["tests"]`, `addopts = "-q --tb=short"` | `pyproject.toml` |
| Markers | `unit`, `integration`, `e2e`, `anyio`; the tier markers are applied by path in `pytest_collection_modifyitems` — never hand-marked | `pyproject.toml`, `tests/conftest.py` |
| Layout | `tests/unit/<package>/`, `tests/integration/`, `tests/e2e/`, `tests/helpers/` (`factories/`, `mocks.py`, `llm.py`, `search.py`, `store.py`) | repo tree |
| Size | 201 `test_*.py` files, 3342 tests collected | `pytest --collect-only` |
| Dev env | `pip install -r requirements-dev.txt && pip install .` — pins pytest 9.0.3, pytest-xdist 3.8.0, pytest-cov 7.1.0, pytest-mock 3.15.1, pytest-asyncio 1.4.0, respx 0.23.1, mypy 2.1.0, ruff 0.15.16, bandit[toml] 1.9.4, pip-audit 2.10.1 | `requirements-dev.txt`, `.github/workflows/ci.yml` |
| Coverage gate (CI) | `--cov=common --cov=ocr --cov=classifier --cov=store --cov=indexer --cov=search --cov-fail-under=70` — `appdb` is **not** in the gate | `.github/workflows/ci.yml` |
| Type check | `mypy src` (whole tree) in CI. Note `docs/development.md` still says only `store`/`indexer`/`search` — the workflow is authoritative | `.github/workflows/ci.yml`, `docs/development.md` |
| Lint | `ruff check src tests` + `ruff format --check src tests` (ruff pinned 0.15.16 in both CI and dev deps) | `.github/workflows/ci.yml`, `requirements-dev.txt` |
| Security | `bandit -r src/ -ll -f txt` (MEDIUM+), `pip-audit` over the installed env. Both are now pinned in `requirements-dev.txt` too (for local gate parity), but the `security-scan` / `dependency-audit` CI jobs still install their own copy inline rather than from it — same pins (`bandit[toml]==1.9.4`, `pip-audit==2.10.1`), two install paths | `.github/workflows/ci.yml`, `requirements-dev.txt` |
| CI runtimes | Python 3.11 (all Python jobs), Node 22 (frontend job) | `.github/workflows/ci.yml` |

**What the tiers mean here:** unit = mocked collaborators; integration = the *real* module against a real temp SQLite store (`tmp_path`) with only Paperless/LLM/embeddings mocked; e2e = full workflows — the OCR and classifier lifecycles run against a stateful fake Paperless (`tests/helpers/mocks.make_stateful_paperless`), and `tests/e2e/test_index_then_search.py` wires the real `Reconciler` + `StoreWriter` into a real `SearchCore` with a scripted LLM.

### Frontend suite (`web/`)

| Item | Value | Source |
|------|-------|--------|
| Runner | vitest 4 + jsdom, `pool: 'threads'`, `include: ['src/**/*.test.{ts,tsx}']` | `web/vitest.config.ts`, `web/package.json` |
| Coverage floor | statements 91 / branches 83 / functions 91 / lines 91 (v8 provider) — only enforced under `npm run test:coverage`, which is what CI runs; plain `npm run test` measures nothing | `web/vitest.config.ts`, `web/package.json`, `.github/workflows/ci.yml` |
| Lint | `npm run lint` = `eslint . && stylelint "src/**/*.css" --allow-empty-input`. eslint enforces the layer stack via `eslint-plugin-boundaries`; stylelint bans literal colours/sizes outside `src/styles/{tokens,themes,global}.css` | `web/package.json`, `web/eslint.config.js`, `web/.stylelintrc.json` |
| Dependency audit | `npm audit --omit=dev --audit-level=high` — production deps only; high/critical fails the CI `frontend` job (moderate and below are noise in a vite/react dev toolchain) | `.github/workflows/ci.yml` (`frontend` job) |
| Build | `npm run build` = `tsc -p tsconfig.json --noEmit && vite build` — a type error fails the build | `web/package.json` |
| Census | 150 test files, 100 stories, 113 CSS modules | repo tree |

### Known skips

`TestRealPopplerPdfStreaming` in `tests/integration/test_ocr_pipeline.py` (6 tests) is the only skip in the suite and the only place the real `pdftoppm` is driven; it is `@pytest.mark.skipif(shutil.which("pdftoppm") is None)` and silently skips on a machine without poppler.

## Procedures

1. **Whole Python suite** — `pytest -n auto` (pytest-xdist across cores).
2. **One tier** — `pytest tests/unit/`, `pytest tests/integration/`, `pytest tests/e2e/`.
3. **One package** — e.g. `pytest tests/unit/search/`; one test — `pytest "tests/unit/common/test_config.py::TestDefaults::test_classify_pre_tag_id_defaults_to_post_tag_id"`.
4. **Coverage as CI runs it** — `pytest -q -n auto --cov=common --cov=ocr --cov=classifier --cov=store --cov=indexer --cov=search --cov-report=term-missing --cov-fail-under=70`.
5. **Static gates** — `mypy src`, `ruff check src tests`, `ruff format --check src tests`, `bandit -r src/ -ll`, `pip-audit`.
6. **Frontend** — from `web/`: `npm audit --omit=dev --audit-level=high`, `npm run typecheck`, `npm run lint`, `npm run test` (or `npm run test:coverage` to enforce the floor as CI does), `npm run build`.

## Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `error: unrecognized arguments: -n` | The interpreter's env has no `pytest-xdist` | `pip install -r requirements-dev.txt` (pins `pytest-xdist==3.8.0`); or drop `-n auto` |
| `ModuleNotFoundError: openai` (or any `src/` package) under pytest | Interpreter without the project + dev deps installed | `pip install -r requirements-dev.txt && pip install .` into the venv, then run `python -m pytest` |
| 6 OCR integration tests skipped | `pdftoppm` not on PATH | Install poppler (`brew install poppler`) — the rest of the suite still passes |
| A test sees another test's config or `SearchCore` | `_SETTINGS_CACHE` (`src/common/config/_loader.py`) and `_CORE_CACHE` (`src/search/api.py`) are process-global and are **not** auto-reset | Pop your `app_db` key from `_SETTINGS_CACHE`; call `search.api._reset_core_cache_for_test()`. The login throttle, search-result cache and price book are already reset per-test by the autouse fixtures in `tests/conftest.py` |
| Frontend suite fails only when run together | Cross-file DOM/global pollution | Do **not** add `isolate: false` to `web/vitest.config.ts` — per-file isolation is load-bearing |
| "Where is the test for X?" comes up empty | Test files are split purely for the 500-line ceiling (CODE_GUIDELINES §3.1): `ocr/test_worker` + `test_worker_internals`; `classifier/test_worker` + `test_worker_metadata`; `classifier/test_provider` + `test_provider_compat`; `classifier/test_taxonomy` + `test_taxonomy_helpers`; `integration/test_search_pipeline` + `…_refinement`; `integration/test_indexer_pipeline` + `…_sweep` | Look in both halves before concluding it is untested |

## Related

- [DEPLOYMENT](DEPLOYMENT.md) (the CI lane and the in-image test gate) · [ARCHITECTURE](ARCHITECTURE.md)
- Human docs: `docs/development.md`; the law: `CODE_GUIDELINES.md`
