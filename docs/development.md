# Development

This guide gets you from a fresh clone to a green test run, then explains how the project is built, tested, and shipped. The standards every change is held to live in [`CODE_GUIDELINES.md`](../CODE_GUIDELINES.md).

## The fastest path

Four commands take you from nothing to a passing test suite:

```bash
git clone https://github.com/rossetv/paperless-ai.git
cd paperless-ai

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install the project and the dev toolchain
pip install -e . -r requirements-dev.txt

# Run the test suite (parallel across cores)
pytest -n auto
```

If that ends green, your environment is good and you can start changing code. The tests never touch a live Paperless, OpenAI, or Ollama — every external boundary is mocked — so a green run needs no API keys and no network.

One caveat: if you intend to run the OCR daemon (not just the tests), you also need **Poppler** installed on the host. The rest of this page fills in the detail — the runtime dependencies, the frontend, the test tiers, the quality gates you should run before pushing, and what CI does.

> The repository is two halves: the Python backend (`src/`) and the React frontend (`web/`). They are tested, linted, and type-checked separately, then built together into one Docker image.

---

## Local setup — backend

The fastest path above is the whole backend setup. For reference:

```bash
git clone https://github.com/rossetv/paperless-ai.git
cd paperless-ai

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install the project and the dev toolchain
pip install -e . -r requirements-dev.txt

# Run the test suite (parallel across cores)
pytest -n auto
```

Once the virtual environment is active, the toolchain lives in `venv/bin/` (e.g. `venv/bin/pytest`, `venv/bin/ruff`) — call those directly if you'd rather not rely on your shell's `PATH`.

### Runtime dependencies

The tests run with no extra system software. To actually *run* a process outside Docker you need:

- **Python 3.11+**
- **Poppler** (`poppler-utils`) — converts PDFs to images for the OCR daemon

```bash
# macOS
brew install poppler
# Ubuntu / Debian
apt-get install poppler-utils
```

### Python runtime dependencies

These are pulled in automatically by `pip install -e .`. The table is here so you know what each one is for, not as something to install by hand. From `pyproject.toml`:

| Package | Constraint | Purpose |
|:---|:---|:---|
| `httpx` | `~=0.28` | HTTP client for the Paperless API |
| `openai` | `~=1.35` | OpenAI SDK — chat + embeddings (also drives Ollama via its compatible API) |
| `Pillow` | `~=12.2` | Image processing (PIL) |
| `pdf2image` | `~=1.17` | PDF → image (wraps Poppler) |
| `structlog` | `~=24.2` | Structured logging |
| `sqlite-vec` | `~=0.1` | Vector search extension for the index |
| `fastapi` | `~=0.136` | The search server's HTTP framework |
| `uvicorn[standard]` | `~=0.47` | ASGI server for the search server |
| `mcp` | `~=1.27` | The MCP endpoint |
| `argon2-cffi` | `~=23.1` | Password hashing for `app.db` accounts |

---

## Running a process locally

Configuration is read from `app.db`'s config table layered over the environment, so for a bare local run the environment alone is enough. There are four entry points (from `pyproject.toml` `[project.scripts]`):

```bash
export PAPERLESS_URL="http://localhost:8000"
export PAPERLESS_TOKEN="your-token"
export OPENAI_API_KEY="sk-your-key"   # required even with Ollama — embeddings always use OpenAI

# Tag daemons
python3 -m ocr.daemon            # or: paperless-ai
python3 -m classifier.daemon     # or: paperless-classifier-daemon

# Search subsystem (needs a built frontend for the UI — see below)
python3 -m indexer.daemon        # or: paperless-indexer-daemon
python3 -m search.api            # or: paperless-search-server
```

These run against a *live* Paperless and a *live* model provider. That is the one place real services come into play — the tests, by contrast, always mock those boundaries (see below).

---

## Local setup — frontend

You only need this if you're working on the search UI; the backend tests don't require it.

```bash
cd web
npm ci
npm run dev        # Vite dev server with hot reload
```

The frontend talks to the search API, so point it at a running `paperless-search-server` (or rely on its mock handlers in tests). The package scripts (`web/package.json`):

| Script | Command | Purpose |
|:---|:---|:---|
| `npm run dev` | `vite` | Dev server |
| `npm run typecheck` | `tsc --noEmit` | Type-check only |
| `npm run lint` | `eslint . && stylelint …` | Boundary + style lint |
| `npm run test` | `vitest run` | Component / hook tests |
| `npm run build` | `tsc --noEmit && vite build` | Type-check then build `web/dist` |
| `npm run storybook` | `storybook dev` | The component catalogue |

---

## Running the tests

The single most important thing to know: **no test touches a live Paperless, OpenAI, or Ollama.** The LLM, the embeddings, and Paperless are always mocked. That is why the suite runs offline, needs no secrets, and is safe to run on every save.

The backend suite is split into three tiers — the test pyramid (`CODE_GUIDELINES.md` §11):

```bash
# Everything, parallel across cores (pytest-xdist)
pytest -n auto

# By tier
pytest tests/unit/            # fast, no I/O
pytest tests/integration/     # module boundaries (real temp store, mock LLM/Paperless)
pytest tests/e2e/             # full workflows against mocks

# By package
pytest tests/unit/search/
pytest tests/unit/indexer/

# A single file or test
pytest tests/unit/common/test_config.py
pytest "tests/unit/common/test_config.py::TestDefaults::test_classify_pre_tag_id_defaults_to_post_tag_id"

# Coverage (CI gate is 70%)
pytest -n auto --cov=common --cov=ocr --cov=classifier --cov=store --cov=indexer --cov=search \
  --cov-report=term-missing --cov-fail-under=70
```

### Test markers

The three tiers each have a marker, declared in `pyproject.toml` and applied by directory:

- `unit` — fast, no I/O, one cohesive unit
- `integration` — module boundaries, real temporary store
- `e2e` — full workflow against mocks
- `anyio` — async tests on the anyio loop (the search API and MCP)

### Test layout

Tests mirror the source tree one-to-one (`src/indexer/chunker.py` ↔ `tests/unit/indexer/test_chunker.py`), so a moved function moves its test in the same change. Rather than hand-building objects, use the shared builders in `tests/helpers/` (`make_document`, `make_settings_obj`, `make_classification_result`, the mock-Paperless builders).

### Known gap — no real-frontend → real-backend e2e test

There is no test that wires a real React build against a real running FastAPI server. Each side is tested independently — the backend via FastAPI's `TestClient`, the frontend against MSW mock handlers under Vitest — and the wire contract between them is held by keeping the TypeScript types in `web/src/api/types/` in deliberate correspondence with the Pydantic models in `src/search/wire/`, policed by per-wave review. A Playwright login → search → preview scenario is tracked as a follow-up but is not required for release.

---

## Quality gates (run them before pushing)

CI runs all of these, so running them locally first saves a round-trip. With the virtual environment active, each tool is on your `PATH` (or call it as `venv/bin/<tool>`):

```bash
# Backend
pytest -n auto
mypy src/store src/indexer src/search   # the type-checked packages
ruff check src tests
ruff format --check src tests
bandit -r src/ -ll                       # MEDIUM+ severity
pip-audit                                # dependency CVEs

# Frontend (from web/)
npm run typecheck
npm run lint
npm run test
npm run build
```

A few notes on the backend gates:

- `mypy` is enforced only on `store`, `indexer`, and `search` — the subsystems held to full typing from their first commit.
- `bandit -ll` reports MEDIUM severity and above.
- `pip-audit` scans the installed environment (there is no lockfile), so install it on demand — it is not part of `requirements-dev.txt`.

---

## CI/CD pipeline

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and pull request to `main`. An in-flight run for the same ref is cancelled when a new one starts, so only the latest commit's checks matter.

The pipeline is a set of independent check jobs, and an image build that depends on all of them passing:

| Job | What it does |
|:---|:---|
| **Tests** | Python 3.11, install project + dev deps, `pytest -n auto` with `--cov-fail-under=70`, then `mypy src/store src/indexer src/search` |
| **Lint (ruff)** | `ruff check` and `ruff format --check` over `src tests` |
| **Security scan (bandit)** | `bandit -r src/ -ll` |
| **Dependency audit (pip-audit)** | Install the project, audit the resolved environment |
| **Frontend** | Node 22, `npm ci`, then `typecheck` → `lint` → `test` → `build` |
| **Docker** | Builds the image; gated on **all** the check jobs above |
| **Docker manifest** | (push only) Assembles the multi-arch manifest from the per-arch digests |

### The image build

The `Docker` job builds **each architecture on its native runner** — `amd64` on `ubuntu-latest`, `arm64` on `ubuntu-24.04-arm` — with no QEMU emulation. On a pull request each arch is built only to validate the Dockerfile, and nothing is pushed. On a push to `main` each arch is built and pushed *by digest*, and `Docker manifest` then assembles the tagged multi-arch manifest (`:latest`, `:sha-<sha>`) on Docker Hub.

CI passes `RUN_TESTS=0` to the image build because the dedicated `Tests` job already ran `pytest` once, natively — re-running it inside the emulated build per architecture would be slow and redundant. A plain local `docker build` defaults to `RUN_TESTS=1` and keeps the in-image test gate.

See [Deployment](deployment.md) for the Dockerfile's stages and how to run the image.
