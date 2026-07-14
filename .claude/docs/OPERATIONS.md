<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../INDEX.md)

# Operations

## Facts

### Observability

| Item | Value | Source |
|------|-------|--------|
| Logging | structlog + stdlib; `LOG_FORMAT` = `console` (default) or `json`; `httpx`/`openai` loggers pinned to WARNING | `src/common/logging_config.py`, `src/common/config/_parsers.py:209` |
| Heartbeats | Every process upserts a `daemon_status` row in `app.db` (`ocr`, `classifier`, `indexer`, `search`) | `src/common/heartbeat.py`, `src/appdb/daemon_status.py` |
| Heartbeat state | **Derived at read time**, never stored: last beat older than `DEFAULT_STALE_AFTER_SECONDS` (90 s) ⇒ `stopped`; fresh + `detail == "idle"` ⇒ `idle`; else `running` | `src/appdb/daemon_status.py:46,129` |
| Search-server beat | Background daemon thread, every 30 s | `src/search/api.py:97` |
| Indexer idle beat | Every 30 s during the inter-cycle wait | `src/indexer/daemon/_wait.py` |
| Heartbeat writes | Best-effort: every `sqlite3.Error` / `OSError` is swallowed at WARNING. A heartbeat must never crash a daemon | `src/common/heartbeat.py` |
| Reconcile activity log | Append-only in `app.db`, capped at the newest 500 rows — kept out of `index.db` so a Rebuild does not erase it | `src/appdb/reconcile_activity.py:41` |
| Dashboard | `GET /api/index/status` / `/activity` / `/failed` (readonly+) | `src/search/index_routes.py` |

### Health

| State (`GET /api/healthz`) | Meaning | HTTP |
|-------|---------|------|
| `ok` | Schema present, `last_reconcile_at` set, `PRAGMA quick_check` clean | 200 |
| `index-not-ready` | Index file/schema absent, or never reconciled, or `get_stats` failed | 503 |
| `index-corrupt` | Schema + reconcile present but `quick_check` failed | 503 |

`evaluate_index_health` (`src/search/routes.py:117`) is the pure decision function; healthz is public (no auth).

### Failure containment

| Mechanism | Behaviour | Source |
|-----------|-----------|--------|
| Write-back circuit breaker | 3 consecutive **permanent** Paperless write failures halt the OCR/classifier daemon (it stops pulling work and burning LLM tokens). Process-lifetime state; cleared only by a config change (`reset()`) or a restart | `src/common/circuit_breaker.py:27` |
| Per-document isolation | The indexer catches every exception per document, counts it in the persisted `failed_documents` map, and dead-letters at 5 consecutive failures (logged CRITICAL) | `src/indexer/reconciler/_failed_documents.py:43` |
| Cycle isolation | The indexer wraps rebuild + sync + sweep + checkpoint in one `try/except Exception` → `indexer.cycle_failed`; `last_sweep_at` advances only after a *successful* sweep | `src/indexer/daemon/_loop.py` |
| Deletion-sweep safety | Any failure enumerating Paperless ids prunes **nothing** (`SweepReport(aborted=True)`); each candidate is independently 404-confirmed, and a confirm that raises keeps the document | `src/indexer/reconciler/_sweep.py` |
| Stale-lock recovery | On daemon boot, orphaned processing-lock tags are stripped and the queue tag re-added. Unconditional — no age or owner check | `src/common/stale_lock.py` |
| Login throttle | 5 failures per (IP, username) or 20 per username in a 900 s window ⇒ 900 s lockout, denied before any argon2 work | `src/search/login_throttle.py:72-86` |

### Indexer exit codes

| Code | Cause | Source |
|------|-------|--------|
| 1 | `index.db` writer `flock` already held (another indexer is running) | `src/indexer/daemon/_boot.py:71` |
| 2 | Preflight failed (Paperless unreachable or the embedding backend rejected a probe) | `src/indexer/daemon/_boot.py:132` |
| 3 | `StoreError` opening the store / checking the embedding identity | `src/indexer/daemon/_boot.py:151` |

## Procedures

1. **Check what is running** — `GET /api/index/status` returns all four daemons (absentees synthesised as `stopped`) plus overall health `ok`/`degraded`/`down` (`src/search/index_service.py`).
2. **Force a reconcile** — `POST /api/reconcile` (member+) touches `reconcile.request` beside `index.db`; the indexer wakes from its wait and syncs on the next cycle.
3. **Rebuild the index** — `POST /api/index/rebuild` (admin) touches `rebuild.request` + `reconcile.request`; the indexer wipes `index.db` and re-indexes everything. Returns 503 if the data directory is unwritable. `app.db` (accounts, keys, config, activity) is untouched.
4. **Change configuration without a restart** — `PUT /api/settings` (admin). Every process picks it up at its next safe boundary; a `REINDEX_KEYS` change schedules the rebuild sentinel *before* the config write commits.
5. **Clear a halted daemon** — save any configuration change (the daemons call `WriteBackCircuitBreaker.reset()` on hot-reload) or restart the container. A late success alone does **not** lift the halt.
6. **Re-run a single document** — `POST /api/documents/{id}/retranscribe` or `/reclassify` (member+) swap the tags to re-queue it for the OCR or classifier daemon.

## Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Indexer exits immediately, code 1 | A second indexer holds the writer `flock` | Run exactly one indexer against a given `/data` |
| `healthz` 503 `never_reconciled` | Index schema exists but the indexer has not completed a first cycle | Wait for the first reconcile; check the indexer's logs/heartbeat |
| `healthz` 503 `schema_missing` | `index.db` present but empty — no indexer has ever run | Start the indexer daemon |
| Daemon heartbeat detail starts `halted:` (`HALTED_DETAIL`, `src/common/circuit_breaker.py:31`) | Write-back circuit breaker tripped: 3 consecutive permanent (4xx) Paperless write rejections — usually a deleted/invalid tag or custom-field id | Fix the offending id in Settings (the save resets the breaker) |
| Documents stuck with the pre-tag, nothing processed | Every document already carries the processing tag (stale locks from a hard kill) | Restart the daemon — the boot sweep strips orphaned lock tags (`STALE_LOCK_RECOVERY`) |
| A rolling restart re-OCRs documents a live peer is working on | The stale-lock sweep is unconditional and steals a peer's lock | Multi-replica deployments MUST set `STALE_LOCK_RECOVERY=false` |
| Search returns nothing after changing the embedding model | The index is stale until the wipe-and-re-embed finishes | Expected: a `REINDEX_KEYS` save schedules the rebuild; watch `/api/index/activity` |
| A document never appears in search | It was dead-lettered after 5 consecutive index failures, or its content is empty / it carries `ERROR_TAG_ID` (the worker skips and prunes it) | `GET /api/index/failed`; fix the document, then a content change re-queues it |
| Long searches die behind the proxy | Idle connection killed mid-synthesis | The stream already emits a blank keepalive line every 15 s — clients must skip blank lines |

## Related

- [ARCHITECTURE](ARCHITECTURE.md) · [DEPLOYMENT](DEPLOYMENT.md) · [CONFIGURATION](CONFIGURATION.md) · [PIPELINES](PIPELINES.md)
- Human docs: `docs/resilience.md`, `docs/deployment.md`
