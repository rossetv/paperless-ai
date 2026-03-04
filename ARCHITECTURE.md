# Architecture & Module Design

**Date:** 2026-03-04
**Purpose:** Target architecture for the refactored codebase based on AUDIT.md findings.

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Daemon Entry Points                    │
│  ocr.daemon:main()        classifier.daemon:main()       │
│         │                           │                     │
│         └─────────┐    ┌────────────┘                     │
│                   ▼    ▼                                  │
│           common.daemon_loop.run_polling_threadpool()     │
│                        │                                  │
│         ┌──────────────┼──────────────┐                   │
│         ▼              ▼              ▼                   │
│   fetch_work    before_batch    process_item              │
│   (per-poll)    (per-batch)     (per-document)            │
└─────────────────────────────────────────────────────────┘
```

## 2. Module Map — Current vs Target

### 2.1 `common/` — Shared Infrastructure

| Module | Status | Notes |
|--------|--------|-------|
| `config.py` | **Refactor** | Extract repeated patterns, add type annotations |
| `paperless.py` | **Keep** | Clean client, minor type fixes |
| `daemon_loop.py` | **Keep** | Well-structured, no changes needed |
| `llm.py` | **Keep** | Clean mixin pattern |
| `retry.py` | **Keep** | Well-designed decorator |
| `tags.py` | **Keep** | Good separation of concerns |
| `claims.py` | **Keep** | Clean claim workflow |
| `utils.py` | **Keep** | Focused utility functions |
| `shutdown.py` | **Keep** | Simple and correct |
| `stale_lock.py` | **Keep** | Clean recovery logic |
| `preflight.py` | **Keep** | Good startup validation |
| `concurrency.py` | **Keep** | Simple semaphore wrapper |
| `library_setup.py` | **Refactor** | Fix leaked httpx client |
| `logging_config.py` | **Keep** | Clean structured logging setup |

### 2.2 `ocr/` — OCR Pipeline

| Module | Status | Notes |
|--------|--------|-------|
| `daemon.py` | **Refactor** | Extract shared bootstrap, DRY iteration |
| `worker.py` | **Keep** | Well-orchestrated, minor type fix |
| `provider.py` | **Refactor** | Fix thread-safety of stats |
| `image_converter.py` | **Keep** | Pure, stateless, well-tested |
| `text_assembly.py` | **Keep** | Pure, stateless, well-tested |
| `prompts.py` | **Keep** | Simple constant |

### 2.3 `classifier/` — Classification Pipeline

| Module | Status | Notes |
|--------|--------|-------|
| `daemon.py` | **Refactor** | Extract shared bootstrap, DRY iteration |
| `worker.py` | **Refactor** | Add type annotation for `result` parameter |
| `provider.py` | **Keep** | Well-structured compat handling |
| `prompts.py` | **Keep** | Constants and schemas |
| `result.py` | **Keep** | Clean frozen dataclass + parser |
| `taxonomy.py` | **Refactor** | Cache sorted names during refresh |
| `content_prep.py` | **Keep** | Pure functions, well-tested |
| `metadata.py` | **Keep** | Pure functions, well-tested |
| `tag_filters.py` | **Keep** | Pure functions, well-tested |
| `normalizers.py` | **Keep** | Pure functions, well-tested |
| `constants.py` | **Keep** | Centralized constants |

## 3. Refactoring Plan

### 3.1 Fix thread-safety of `_stats` in OCR provider

**File:** `src/ocr/provider.py`
**Change:** Use `threading.Lock` to protect `_stats` mutations, or switch to per-thread stats collection.

### 3.2 Extract repeated tag-ID nullification in `Settings`

**File:** `src/common/config.py`
**Change:** Add a private `_get_optional_positive_int_env` helper that returns `None` for values ≤ 0. Apply to all four tag-ID fields.

### 3.3 Extract shared daemon bootstrap

**Files:** `src/ocr/daemon.py`, `src/classifier/daemon.py`
**Change:** Create `common.bootstrap.bootstrap_daemon()` that handles Settings → logging → libraries → signals → semaphore → preflight → stale locks. Both daemons call this, then pass daemon-specific config to `run_polling_threadpool`.

### 3.4 Extract shared document-iteration logic

**Files:** `src/ocr/daemon.py`, `src/classifier/daemon.py`
**Change:** Create `common.iteration.iter_documents_by_tag()` that encapsulates the pattern: iterate by tag → skip processed → skip claimed → yield. Both daemons supply their specific tag IDs.

### 3.5 Add type annotation for `_apply_classification.result`

**File:** `src/classifier/worker.py`
**Change:** Add `result: ClassificationResult` annotation.

### 3.6 Cache sorted taxonomy names during refresh

**File:** `src/classifier/taxonomy.py`
**Change:** Compute `_cached_correspondent_names`, `_cached_document_type_names`, and `_cached_tag_names` during `refresh()` so `*_names()` methods return the cached list instantly.

### 3.7 Fix leaked httpx client in `library_setup`

**File:** `src/common/library_setup.py`
**Change:** Store the httpx client reference so it can be closed at shutdown, or use `atexit.register`.

### 3.8 Add `_create_named_item` explicit return guard

**File:** `src/common/paperless.py`
**Change:** Add an explicit `return` (or `raise`) after the for loop to satisfy type checkers and make the control flow explicit.

### 3.9 Add `clean_pipeline_tags` type annotation

**File:** `src/common/tags.py`
**Change:** Type the `settings` parameter as `Settings`.

## 4. Configuration Flow

```
Environment Variables
       │
       ▼
   Settings()  ←── config.py (loads, validates, groups)
       │
       ├──▶ configure_logging()      ←── logging_config.py
       ├──▶ setup_libraries()        ←── library_setup.py
       ├──▶ init_llm_semaphore()     ←── concurrency.py
       ├──▶ register_signal_handlers() ←── shutdown.py
       ├──▶ run_preflight_checks()   ←── preflight.py
       ├──▶ recover_stale_locks()    ←── stale_lock.py
       │
       └──▶ run_polling_threadpool() ←── daemon_loop.py
                    │
                    ├──▶ PaperlessClient(settings)
                    ├──▶ OcrProvider(settings) / ClassificationProvider(settings)
                    └──▶ DocumentProcessor / ClassificationProcessor
```

## 5. Error Propagation Strategy

```
Exception in page OCR
  └──▶ Caught in _ocr_pages_in_parallel → OCR_ERROR_MARKER in result
        └──▶ _update_paperless_document detects marker → _finalize_with_error
              └──▶ clean_pipeline_tags + ERROR_TAG_ID → update_document_metadata

Exception in document download
  └──▶ Propagates up through process() → caught by daemon_loop
        └──▶ Logged, document retried next poll cycle

Exception in LLM call
  └──▶ Caught by retry decorator → exponential backoff → re-raise on exhaustion
        └──▶ Caught by model fallback loop → try next model
              └──▶ All models exhausted → return error marker / None

Exception in Paperless API
  └──▶ Caught by retry decorator → exponential backoff → re-raise on exhaustion
        └──▶ Caught by process() or daemon_loop → logged, retried next cycle

Exception in processing-tag release
  └──▶ Caught internally by release_processing_tag → logged, never propagated
        └──▶ Stale lock recovered on next daemon startup
```

## 6. Constraints and Non-Goals

**Preserved as-is:**
- All existing functionality and behavior.
- All public interfaces consumed by external callers.
- Tag-driven state machine design.
- Thread-pool concurrency model.
- OpenAI-compatible API integration.
- All 350 existing tests continue to pass.

**Not in scope:**
- Async/await migration (would require rewriting all I/O code).
- Database-backed state (external dependency, architectural change).
- gRPC or message-queue integration (architectural change).
- Multi-process architecture (current threading model is adequate).

---

*End of architecture document.*
