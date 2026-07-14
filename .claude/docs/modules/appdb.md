<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../../INDEX.md)

# Module: appdb

## Purpose

Owns `app.db` — the SQLite application database (accounts, sessions, API keys, config, daemon heartbeats, activity log, model prices), deliberately separate from the search index (`index.db`) so rebuilding the index never destroys user accounts, keys or configuration. It is the only place `app.db` SQL is written: every higher layer calls typed functions here.

It sits at the bottom of the import graph — it may not import `store`, `search`, `indexer`, `ocr`, `classifier`, `common` or FastAPI — which is precisely what lets the OCR/classifier daemons (barred from `store`) read `app.db` config. The migration machinery is copied from `store.migrations`, not shared, so the two databases version independently.

## Key files

| File | Role |
|------|------|
| `src/appdb/__init__.py` | Package docstring only — states the `app.db` charter and the allowed/forbidden dependency list. Exports no names; callers import submodules (`from appdb import config`, `from appdb.connection import connect`). |
| `src/appdb/connection.py` | Connection factory + shared primitives. `connect(db_path)` sets WAL, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000ms`, `sqlite3.Row`, `check_same_thread=False`. `transaction(conn)` is the `BEGIN IMMEDIATE` context manager (commits on clean exit, rolls back on `BaseException`, guards on `conn.in_transaction` so a committing callee is tolerated). `utc_now_iso()` is the single timestamp helper for every table. `RowVanishedError` is the shared typed fault for "the row I just inserted is gone". |
| `src/appdb/schema.py` | All DDL as `SCHEMA_V1`–`V5`, `V7`, `V8` string constants (no `V6` — that migration is data-only), plus `SCHEMA_VERSION: int = 8` (schema.py:25) and `ensure_schema(conn)`, which delegates to `migrations.run_migrations`. Tables: `meta`, `users`, `sessions` (v1), `recent_searches` (v2), `api_keys` (v3), `config` (v4), `daemon_status` + `reconcile_activity` (v5), `api_key_usage` (v7), `model_pricing` (v8). |
| `src/appdb/migrations.py` | Forward-only versioned runner. `MIGRATIONS` is the ordered `[(1,_migrate_v1) … (8,_migrate_v8)]` list (migrations.py:286-295); `run_migrations` applies each pending migration inside its own explicit `BEGIN…COMMIT` with the `schema_version` bump in the same transaction. `_apply_schema_string` strips `--` comment lines then splits on `;` and executes statements one by one (`executescript` is avoided — it issues an implicit `COMMIT`). `AppDbError` is raised when the stored `schema_version` exceeds the highest known migration. `_read_schema_version` returns 0 only for a genuine "no such table" error; any other `OperationalError` propagates. |
| `src/appdb/users.py` | `User` frozen dataclass + CRUD: `create` (raises `UsernameTakenError`), `get_by_username`, `get_by_id`, `create_initial_admin` (atomic `INSERT…SELECT…WHERE NOT EXISTS` — first-run setup), `list_all`, `update` (partial), `delete` (cascades sessions/keys/searches), `count_all` (0 ⇒ setup mode), `count_admins` (active admins only — the last-admin guard), `record_login`. |
| `src/appdb/sessions.py` | `Session` dataclass + `create` / `get_by_token_hash` / `touch_last_seen` / `delete` (logout) / `delete_for_user` (instant revocation) / `prune_expired`. Stores only `sha256(cookie token)`; hashing is the search layer's job. |
| `src/appdb/recent_searches.py` | `recent_searches` (v2) — per-user search history, capped at `MAX_PER_USER` (20, recent_searches.py:36). `record` deletes any identical prior query for the user, inserts the new row, then `_trim_to_cap` keeps only the newest `MAX_PER_USER`; `list_for_user` reads back newest-first (`ORDER BY created_at DESC, id DESC`). |
| `src/appdb/passwords.py` | Argon2id wrappers over a single module-level `PasswordHasher()` with library defaults: `hash_password`, `verify_password`. `verify_password` fails closed — a wrong password, a malformed hash and an empty hash all return `False`, never raise. |
| `src/appdb/api_keys.py` | `ApiKey` dataclass + `create` (`DuplicateKeyHashError`), `get_by_hash` (the bearer-auth lookup), `get_by_id`, `list_all`, `list_for_user`, `revoke` (soft delete, keeps history), `delete` (hard), `touch` (caller-throttled `last_used_at` + `request_count` bump), `update` (uses a module-private `_UNSET` sentinel, api_keys.py:331, so `expires_at=None` clears an expiry rather than meaning "unchanged"). Stores `sha256(key)` + a display prefix only. |
| `src/appdb/config.py` | Flat key/value store keyed by canonical env-var name; strings in, strings out (parsing/validation is `common.config`'s job). `get_all`, `get`, `set_value` → `set_many`, `set_many_in_transaction` (for callers who already hold a `BEGIN IMMEDIATE`), `seed_from_env` (first-run env import, only when the table is entirely empty), `get_config_version`, `snapshot_config_with_version` (`BEGIN DEFERRED` so the hot-load reader gets version + data from one consistent snapshot). Every write bumps `meta.config_version` in the same transaction. |
| `src/appdb/key_usage.py` | `api_key_usage` (v7) — per-key, per-UTC-day LLM spend bucket behind `SEARCH_KEY_DAILY_TOKEN_QUOTA`. `utc_today()` formats the `usage_date` key; `get_tokens_used` returns 0 for an absent bucket; `add_usage` upserts with `tokens = tokens + excluded.tokens` inside `BEGIN IMMEDIATE` (no-op when `tokens` and `calls` are both 0). |
| `src/appdb/model_pricing.py` | `model_pricing` (v8) — the cached USD price book. `CachedModelPrice` / `CachedPriceBook` dataclasses (plain floats, deliberately `search`-free since appdb cannot import `search`). `load_cached_prices` returns `None` (not an empty book) when the table is empty, so the caller can fall back to the bundled seed. `save_cached_prices` DELETEs then re-INSERTs the whole cache in one `BEGIN IMMEDIATE`, stamping one `(as_of, source, fetched_at)` on every row. |
| `src/appdb/daemon_status.py` | `daemon_status` (v5) — one heartbeat row per daemon (`ocr`/`classifier`/`indexer`/`search`, CHECK-constrained). `record_heartbeat` upserts on `name`. `read_statuses` **derives** state at read time: heartbeat older than `DEFAULT_STALE_AFTER_SECONDS` (90, daemon_status.py:46) ⇒ `stopped`; fresh + `detail == IDLE_DETAIL` (`"idle"`) ⇒ `idle`; otherwise `running`. |
| `src/appdb/reconcile_activity.py` | `reconcile_activity` (v5) — append-only log of the indexer's sync/sweep cycles, kept in `app.db` precisely so the destructive index Rebuild does not erase it. `record_cycle` inserts and trims to the newest `_ACTIVITY_CAP` (500, reconcile_activity.py:41) rows via `id <= MAX(id) - cap`. `read_recent(limit)` returns newest-first. `_parse_summary` decodes the JSON count map defensively — a corrupt blob logs a warning and yields `{}` rather than breaking the dashboard. |
| `tests/unit/appdb/test_migrations.py` | Locks the migration contract: a fresh DB reaches `SCHEMA_VERSION`, `MIGRATIONS` is ordered + unique, a future `schema_version` raises `AppDbError`, a corrupt-DB `OperationalError` is not masked as version 0, a failing migration rolls back atomically. |
| `tests/unit/appdb/test_connection.py` | Locks WAL / `foreign_keys` / `row_factory` / `busy_timeout`, that concurrent writers on separate connections lose no writes, and that `transaction()` tolerates a callee that commits. |
| `tests/unit/appdb/test_config.py` | Config-store tests plus the **only** coverage of migration v6 (`AI_MODELS` → `OCR_MODELS`/`CLASSIFY_MODELS` split), including the end-to-end `run_migrations` path over a legacy row. |

## Entry points

| Caller | Site | Shape |
|--------|------|-------|
| `search.appdb_setup.open_app_db` | src/search/appdb_setup.py:43-44, called from src/search/api.py:415-429 | `connect` + `ensure_schema` at server startup; the connection is closed in the same block (short-lived). |
| `common.config._loader` | src/common/config/_loader.py:66-76, 129-143 | Deferred imports, transient connection per load/hot-load — **this is the path every process takes to read config**, including the OCR/classifier/indexer daemons. |
| `search.deps.get_app_db` | src/search/deps.py:96 | Per-request connection: `connect` per request, closed in a `finally`. |
| Daemon heartbeat bootstrap | src/ocr/daemon.py:166-167, src/classifier/daemon.py:195-196, src/indexer/daemon/_boot.py:202-203 | `connect` + `ensure_schema` once at daemon start; the connection is **long-lived** and handed to `common.heartbeat.Heartbeat` for the process's lifetime. |

Downstream module-level consumers: `search.api` (startup migration + `model_pricing` cache), `search.deps`, `search.accounts` / `sessions` / `passwords_login` / `api_keys` / `setup` / `account_routes` / `api_key_routes` / `settings_routes` / `index_service` / `index_routes` / `spend_quota` / `pricing_book` / `mcp_server`, `search.routes` and `search.document_routes._documents` (→ `recent_searches`); `common.heartbeat` → `daemon_status`; `indexer.activity` → `reconcile_activity`; `common.config` → `appdb.config`.

## Invariants

- **Dependency floor.** appdb imports only `sqlite3`, `json`, `datetime`, `dataclasses`, `typing`, `collections`/`contextlib`, `structlog` and `argon2`. It never imports `store`, `search`, `indexer`, `ocr`, `classifier`, `common`, FastAPI, `httpx` or `openai` — verified by grep over every `src/appdb/*.py` import line. This is what lets the daemons (barred from `store`) read `app.db` config.
- `SCHEMA_VERSION` (schema.py:25, currently **8**) must equal the last `MIGRATIONS` entry's version (migrations.py:294). `run_migrations` compares the stored version against `MIGRATIONS[-1][0]` (migrations.py:316) and raises `AppDbError` when the stored version is higher — a database written by newer code fails loud rather than being re-migrated.
- **Migrations are forward-only and append-only.** A new schema version is a new `MIGRATIONS` entry, never an edit to an existing one. Each migration runs in its own explicit `BEGIN…COMMIT`, and the `schema_version` `INSERT OR REPLACE` happens inside that same transaction, so a mid-migration crash rolls the whole step back.
- **No raw secret is ever stored.** `sessions` hold `sha256(cookie token)`; `api_keys` hold `sha256(raw key)` plus a ~12-char display prefix; `users` hold an argon2id encoded hash. Hashing of session tokens and API keys is done by the search layer — appdb persists the already-hashed value.
- **All `app.db` SQL lives in appdb.** Higher layers call typed functions and never build `app.db` SQL themselves.
- Every timestamp appdb stamps itself goes through `connection.utc_now_iso()` (ISO-8601 with a `+00:00` offset), so all tables' timestamps compare as plain strings. The writers that take the timestamp as an argument instead — `sessions.touch_last_seen` / `prune_expired`, `api_keys.revoke` / `touch`, `reconcile_activity.record_cycle` — trust the caller; every current caller builds it with the same `datetime.now(timezone.utc).isoformat()` (e.g. src/search/deps.py:410, 432).
- **Every config write bumps `meta.config_version` in the same transaction as the write** — via `config._bump_config_version` (config.py:73, called from `set_many_in_transaction`), and via the same `UPDATE meta …` inlined in `_migrate_v6` (migrations.py:237-240, which stays free of any `appdb.config` import). This monotonic counter is the whole hot-load mechanism: a process re-reads it and rebuilds `Settings` only when it moves.
- The `config` table is a **dumb string store** — no parsing, typing, validation or defaults. That belongs to `common.config`, which is what allows the daemons to read config without importing the validation logic.
- `connect()` always sets `PRAGMA foreign_keys=ON`, so the `ON DELETE CASCADE` chains fire: deleting a user removes their sessions, api_keys and recent_searches; deleting an api_key removes its api_key_usage rows.
- **`daemon_status` state (`running`/`idle`/`stopped`) is never stored** — it is derived at read time from `last_heartbeat` recency. A crashed daemon cannot write `stopped`, so a stored state would lie forever.
- `passwords.verify_password` fails closed: it catches `InvalidHashError` and `Argon2Error` and returns `False`, so a corrupt stored hash degrades a login to a clean failure, never a 500.
- `users.count_admins` counts only `role='admin' AND status='active'` — a suspended sole admin counts as zero live admins for the last-admin guard.
- **`config.seed_from_env` is idempotent** and only seeds when the config table is completely empty (`SELECT 1 FROM config LIMIT 1`). src/common/config/_loader.py:164-171 (COMMON-04) depends on this: on a fresh deployment every process boots at once and all call `seed_from_env` concurrently. Do not relax that idempotency.

## Gotchas

- **Bug-shaped (verified by running it): `IntegrityError` is over-mapped.** `api_keys.create` maps **any** `sqlite3.IntegrityError` to `DuplicateKeyHashError` (src/appdb/api_keys.py:155-157), but `api_keys` also has a `FOREIGN KEY` on `owner_user_id`. `create(..., owner_user_id=999)` on a DB with no such user raises `DuplicateKeyHashError: an API key with this hash already exists`. Misleading, and would surface as a wrong HTTP status if any caller ever passed an unvalidated owner id. `users.create` has the same shape (src/appdb/users.py:152-154): any `IntegrityError` — including a CHECK violation on `role`/`status` — becomes `UsernameTakenError`.
- **`transaction()` is not re-entrant.** It issues `BEGIN IMMEDIATE`, and SQLite forbids nesting that on one connection. `config.set_many`, `key_usage.add_usage` and `model_pricing.save_cached_prices` each take it internally, so calling any of them from inside an existing `with transaction(conn):` raises *"cannot start a transaction within a transaction"*. `config.set_many_in_transaction` exists precisely as the escape hatch for a caller holding its own wider transaction (the Settings PUT).
- **`users.update` cannot clear a column to NULL**: `None` means "leave unchanged", so `email=None` is a no-op, not a clear. Documented as a known Wave-1 limitation in the docstring (src/appdb/users.py:310-319). `api_keys.update` solves the same problem properly with the `_UNSET` sentinel — the two writers are inconsistent on purpose.
- **`migrations._apply_schema_string` splits DDL naively on `;`** after stripping `--` comment lines. A semicolon inside a SQL string literal in any `SCHEMA_Vn` constant would silently shatter the migration into broken fragments. Same limitation as `store.migrations`, kept deliberately in sync by hand (CODE_GUIDELINES §2.2.1).
- **There is no `SCHEMA_V6` constant.** Migration v6 (`_migrate_v6`, migrations.py:197-242) is a pure **data** migration — it copies a legacy `AI_MODELS` config row into `OCR_MODELS` and `CLASSIFY_MODELS` (only where absent), deletes `AI_MODELS`, and bumps `config_version`. Its only test coverage lives in `tests/unit/appdb/test_config.py`, not in the `test_migrations_v*.py` files.
- **`sessions.get_by_token_hash` deliberately does NOT enforce expiry** — it returns a row whose `expires_at` is in the past so the caller can both reject the request and prune the dead row. Any new caller must do its own expiry check.
- `sessions.create` does not wrap `sqlite3.IntegrityError` — a duplicate `token_hash` (UNIQUE) propagates raw, unlike `users.create`/`api_keys.create`, which map it to a typed error.
- `recent_searches.record` uses `int(cursor.lastrowid or 0)` (src/appdb/recent_searches.py:106) — a `None` lastrowid silently yields id `0` instead of raising `RowVanishedError` as the sibling writers (users/sessions/api_keys) do.
- **`connect()` passes `check_same_thread=False`.** It is only safe because no connection is ever driven by two threads at once: the search server opens one per request (`search.deps.get_app_db`), its heartbeat thread opens its own (src/search/api.py:100-137), and each daemon's long-lived connection is used only by that daemon's own loop. The comment at src/appdb/connection.py:78-88 records that the previous shared-connection-on-`app.state` model made this flag a latent data-corruption bug. **Never reintroduce a connection shared across concurrent request threads.**
- `api_key_usage` cascades on `api_keys` delete: `api_keys.revoke` (soft delete) preserves the usage history; `api_keys.delete` (hard) destroys it. Choose accordingly.
- `reconcile_activity` is capped at 500 rows (`_ACTIVITY_CAP`) and trimmed on every `record_cycle` via `id <= MAX(id) - cap`; the table uses `AUTOINCREMENT` so ids are never reused and the arithmetic holds.
- `daemon_status._derive_state` treats a tz-naive `last_heartbeat` as UTC and an unparseable one as `stopped`. A daemon that never wrote a row simply **does not appear** in `read_statuses` — filling it in as `stopped` is the caller's job (`search.index_service`).
- `appdb/__init__.py` exports **no names at all** (docstring + `from __future__ import annotations`). `import appdb` gives you nothing; always import the submodule.
- `config.snapshot_config_with_version` issues a raw `BEGIN DEFERRED` (config.py:133) and commits in a `finally`. It relies on the connection being in the `sqlite3` module's legacy autocommit-ish mode; a caller already inside a transaction would break it.

## Extension points

| Change | Where |
|--------|-------|
| New table or column | Add a `SCHEMA_Vn` constant to `schema.py`, a `_migrate_vn` appending to `MIGRATIONS` in `migrations.py`, and bump `SCHEMA_VERSION`. Never edit an existing migration. |
| Data-only migration | A `_migrate_vn` with no `SCHEMA_Vn` constant — see `_migrate_v6` (migrations.py:197-242) for the pattern. |
| New config key | No appdb change: the `config` table is an untyped string store. Typing, defaults and validation land in `common.config`. |
| New daemon reporting a heartbeat | Extend the `CHECK (name IN (…))` constraint on `daemon_status` (schema.py, `SCHEMA_V5`) via a new migration. |
| New query against an existing table | A new typed function in the owning submodule — higher layers must never write `app.db` SQL. |

## External dependencies

| Dependency | Use |
|------------|-----|
| `sqlite3` (stdlib) | The only database driver; no ORM anywhere. |
| `structlog` ~=24.2 | Structured logging under `appdb.*` event names (e.g. `appdb.user_created`, `appdb.migration_applied`). |
| `argon2-cffi` ~=23.1 | argon2id password hashing in `appdb.passwords` (library-default cost parameters, deliberately not configurable). |

## Related

- Modules: [store](store.md) (owns `index.db`; the migration machinery here is a hand-synced copy of `store.migrations`), [common](common.md) (`common.config` is the only typed reader of the `config` table; `common.heartbeat` writes `daemon_status`), [search-api](search-api.md) (hashes session tokens and API keys before they reach appdb; opens a connection per request), [indexer](indexer.md) (`indexer.activity` → `reconcile_activity`), [ocr](ocr.md) and [classifier](classifier.md) (read `app.db` config via `common.config` precisely because appdb has no `store` dependency).
- Specs: `docs/superpowers/specs/2026-05-22-web-redesign-design.md` — the "web-redesign spec §5" the code cites throughout (config-in-database, the dashboard's `daemon_status`/`reconcile_activity`, api keys).
