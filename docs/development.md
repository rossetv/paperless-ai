# Development

This is the guide to building, testing, and shipping `paperless-ai` locally and
in CI. The standards every change is held to live in
[`CODE_GUIDELINES.md`](../CODE_GUIDELINES.md).

The repository is two halves: the Python backend (`src/`) and the React frontend
(`web/`). They are tested, linted, and type-checked separately and built together
into one Docker image.

---

## Local setup — backend

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

### Runtime dependencies

Outside Docker you need:

- **Python 3.11+**
- **Poppler** (`poppler-utils`) — for PDF-to-image conversion (the OCR daemon)

```bash
# macOS
brew install poppler
# Ubuntu / Debian
apt-get install poppler-utils
```

### Python runtime dependencies

From `pyproject.toml`:

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

Configuration is read from `app.db`'s config table layered over the environment,
so for a bare local run the environment alone is enough. The four entry points
(from `pyproject.toml` `[project.scripts]`):

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

The daemons run against a live Paperless and a live model provider; for tests
those boundaries are always mocked (see below).

---

## Local setup — frontend

```bash
cd web
npm ci
npm run dev        # Vite dev server with hot reload
```

The frontend talks to the search API; point it at a running
`paperless-search-server` (or its mock handlers in tests). The package scripts
(`web/package.json`):

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

The backend suite is split into unit, integration, and end-to-end tiers (the
pyramid — `CODE_GUIDELINES.md` §11). No test touches a live Paperless, OpenAI,
or Ollama; the LLM, the embeddings, and Paperless are always mocked.

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

Markers are declared in `pyproject.toml` and applied by directory:

- `unit` — fast, no I/O, one cohesive unit
- `integration` — module boundaries, real temporary store
- `e2e` — full workflow against mocks
- `anyio` — async tests on the anyio loop (the search API and MCP)

### Test layout

Tests mirror the source tree one-to-one (`src/indexer/chunker.py` ↔
`tests/unit/indexer/test_chunker.py`); a moved function moves its test in the
same change. Use the shared builders in `tests/helpers/` (`make_document`,
`make_settings_obj`, `make_classification_result`, the mock-Paperless builders)
rather than hand-building objects.

### Known gap — no real-frontend → real-backend e2e test

There is no test that wires a real React build against a real running FastAPI
server. Each side is tested independently — the backend via FastAPI's
`TestClient`, the frontend against MSW mock handlers under Vitest — and the wire
contract between them is held by keeping the TypeScript types in
`web/src/api/types/` in deliberate correspondence with the Pydantic models in
`src/search/wire/`, policed by per-wave review. A Playwright login → search →
preview scenario is tracked as a follow-up but is not required for release.

---

## Quality gates (run them before pushing)

CI runs these, so run them locally first:

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

`mypy` is enforced on `store`, `indexer`, and `search` (the subsystems held to
full typing from their first commit). `bandit -ll` reports MEDIUM severity and
above; `pip-audit` scans the installed environment (there is no lockfile).

---

## CI/CD pipeline

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and pull request
to `main`. An in-flight run for the same ref is cancelled when a new one starts.

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

The `Docker` job builds **each architecture on its native runner** — `amd64` on
`ubuntu-latest`, `arm64` on `ubuntu-24.04-arm` — no QEMU emulation. On a pull
request each arch is built to validate the Dockerfile and nothing is pushed; on a
push each arch is built and pushed *by digest*, and `Docker manifest` then
assembles the tagged multi-arch manifest (`:latest`, `:sha-<sha>`) on Docker Hub.

CI passes `RUN_TESTS=0` to the image build because the dedicated `Tests` job
already ran `pytest` once, natively — re-running it inside the emulated build per
architecture would be slow and redundant. A plain local `docker build` defaults
to `RUN_TESTS=1` and keeps the in-image test gate.

See [Deployment](deployment.md) for the Dockerfile's stages and how to run the
image.
