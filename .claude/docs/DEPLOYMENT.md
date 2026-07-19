<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../INDEX.md)

# Deployment

## Facts

### One image, four processes

| Process | Console script | Command in the image | Source |
|---------|----------------|----------------------|--------|
| OCR daemon | `paperless-ai` | image default `CMD ["paperless-ai"]` | `pyproject.toml` (`[project.scripts]`), `Dockerfile` (final `CMD`) |
| Classifier daemon | `paperless-classifier-daemon` | `paperless-classifier-daemon` (or `python3 -m classifier.daemon`) | `pyproject.toml` (`[project.scripts]`) |
| Indexer daemon | `paperless-indexer-daemon` | `paperless-indexer-daemon` | `pyproject.toml` (`[project.scripts]`) |
| Search server | `paperless-search-server` | `paperless-search-server` (uvicorn, `SEARCH_SERVER_HOST` = `0.0.0.0`, `SEARCH_SERVER_PORT` = 8080) | `pyproject.toml` (`[project.scripts]`), `_parsers.py::_resolve_server_port`, `_settings.py` (`SEARCH_SERVER_HOST`) |

All four share one `/data` volume — by default it holds `app.db` (accounts, sessions, API keys, config, daemon heartbeats) and `index.db` (the search index). Exactly **one** indexer per `/data` (it takes an exclusive `flock`). OCR/classifier are stateless and may be replicated — set `STALE_LOCK_RECOVERY=false` when you do (it defaults to `true`, and the sweep is unconditional: a restarting replica would steal a peer's live processing lock, `src/common/stale_lock.py::recover_stale_locks`).

### Image build (`Dockerfile`, three stages)

| Stage | Base | Does |
|-------|------|------|
| `frontend-builder` | `node:22-slim` (pinned by digest, `--platform=$BUILDPLATFORM`) | `npm ci` + `npm run build` → `/web/dist` |
| `builder` | `python:3.11-slim` (pinned by digest, target platform) | Installs build toolchain (`build-essential`, `libjpeg-dev`, `zlib1g-dev`, `curl`) + `poppler-utils`, builds the production **wheelhouse** (`pip wheel --no-cache-dir --wheel-dir /wheels .`), then installs `requirements-dev.txt` + the wheelhouse and runs `pytest -n auto` when `RUN_TESTS=1` (the default; CI passes `RUN_TESTS=0`) |
| final | `python:3.11-slim` (same digest as `builder`) | Non-root `appuser`, `poppler-utils` only, installs from the wheelhouse with `--no-index` (no compiler, no PyPI), copies `web/dist` |

Runtime env baked in: `VIRTUAL_ENV=/opt/venv` (prepended to `PATH`), `FRONTEND_DIST=/app/web/dist`, `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1`, `MALLOC_ARENA_MAX=2`.

`poppler-utils` (`pdftoppm`) is a **hard runtime dependency** — PDF rasterisation goes through pdf2image.

### Bootstrap environment

| Var | Default | Note | Source |
|-----|---------|------|--------|
| `APP_DB_PATH` | `/data/app.db` | Environment-only; never stored in the config table | `src/common/config/_catalogue.py` (`BOOTSTRAP_KEYS`), `_settings.py` (`APP_DB_PATH`) |
| `INDEX_DB_PATH` | `/data/index.db` | Environment-only; the writer lock is `<INDEX_DB_PATH>.lock` | `_settings.py` (`INDEX_DB_PATH`), `src/indexer/lock.py::acquire_writer_lock` |
| `FRONTEND_DIST` | `/app/web/dist` (set in the image) | Resolved at *import* time of `search.api`; falls back to `<repo>/web/dist` when unset | `src/search/api.py` (`_FRONTEND_DIST`) |
| every `CONFIG_KEYS` key (`PAPERLESS_URL`, `PAPERLESS_TOKEN`, `OPENAI_API_KEY`, …) | see [CONFIGURATION](CONFIGURATION.md) | Any catalogue key present in the environment is seeded into the `config` table on first boot — **only while that table is empty** (no-op afterwards); thereafter edited in the Settings screen | `src/appdb/config.py` (`seed_from_env`), `src/common/config/_catalogue.py` (`CONFIG_KEYS`) |

### CI → registry (`.github/workflows/ci.yml`)

| Job | Runs |
|-----|------|
| `tests` | `pytest -q -n auto --cov=... --cov-fail-under=70`, then `mypy src` |
| `lint` | `ruff check src tests`, `ruff format --check src tests` |
| `security-scan` | `bandit -r src/ -ll -f txt` (pinned `bandit[toml]==1.9.4`) |
| `dependency-audit` | `pip-audit` over the installed env (no lockfile) |
| `frontend` | Node 22, working-dir `web`: `npm ci` → `npm audit --omit=dev --audit-level=high` → `typecheck` → `lint` → `test:coverage` → `build` |
| `docker` | Matrix `linux/amd64` (ubuntu-latest) + `linux/arm64` (ubuntu-24.04-arm) — **native runners, no QEMU**; both build with `RUN_TESTS=0`; PRs build only, `main` pushes by digest. Needs all five check jobs |
| `docker-merge` | Push-only. `docker buildx imagetools create` → `:latest` + `:sha-<GITHUB_SHA>` multi-arch manifest on Docker Hub, image name `${{ secrets.DOCKERHUB_USERNAME }}/paperless-ai` (published as `rossetv/paperless-ai` — the image name in `README.md`'s docker-run quick-start) |
| `cloudflare-refresh` | Dev-mode + purge, push on the canonical repo only (`github.repository == 'rossetv/paperless-ai'`); each call retried 3× |

Provenance/SBOM attestations are deliberately disabled on both docker jobs (they break the push-by-digest → imagetools flow).

## Procedures

1. **Build the image locally** — `docker build -t paperless-ai .` (runs the test suite inside the build; `--build-arg RUN_TESTS=0` skips it).
2. **First run** — start the search server and read the one-time setup token from its log (WARNING, event `search.setup_mode`, in the `is_setup_needed` block of `src/search/api.py`), then open `/setup` in the SPA to create the first admin. The token lives only in memory — a restart before setup completes mints a new one.
3. **Deploy** — a push to `main` runs the full CI lane and publishes `rossetv/paperless-ai:latest` (+ a `sha-<GITHUB_SHA>` tag) as a multi-arch manifest on Docker Hub.
4. **Reverse proxy** — run uvicorn behind the proxy and keep its port unreachable from anywhere else. `SEARCH_FORWARDED_ALLOW_IPS` defaults to `*` (uvicorn trusts `X-Forwarded-For`/`-Proto` from any peer; `src/search/api.py::main`, `forwarded_allow_ips`); pin it to the proxy CIDR if that port can be reached directly.

## Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `pdftoppm` errors / every PDF fails conversion | `poppler-utils` missing (custom image or bare-metal run) | Install poppler; it is a hard runtime dependency |
| SPA 404s at `/` but the API works | `web/dist` absent (`FRONTEND_DIST` wrong, or the Node stage was skipped) | `register_spa` is a no-op without the directory (`src/search/spa.py`) — rebuild the image |
| Second indexer container exits immediately (code 1), logging `indexer.lock_contended` | Writer `flock` contention on `<INDEX_DB_PATH>.lock` (`LOCK_EX \| LOCK_NB`) | Run one indexer per `/data` (`src/indexer/daemon/_boot.py::main`, `indexer.lock_contended`) |
| Accounts/config lost after an index rebuild | Would mean `app.db` lived inside the index — it does not | `app.db` and `index.db` are separate files on `/data`; a rebuild wipes only `index.db` (`src/search/index_sentinel.py::request_index_rebuild`) |
| Search server binds to every interface | `SEARCH_SERVER_HOST` defaults to `0.0.0.0` (intentional, `# nosec B104`, `src/common/config/_settings.py` (`SEARCH_SERVER_HOST`)) | Restrict exposure at the reverse proxy / container network |

## Related

- [OPERATIONS](OPERATIONS.md) · [CONFIGURATION](CONFIGURATION.md) · [SECURITY](SECURITY.md) · [TESTING](TESTING.md)
- Human docs: `docs/deployment.md`, `README.md`
