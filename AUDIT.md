# Codebase Audit Report

**Date:** 2026-03-04
**Scope:** Full audit of `paperless-ocr-daemon` — all source, test, configuration, and CI files.
**Baseline:** 350 tests passing, 99% line coverage, 0 failures.

---

## 1. Architecture Overview

The project ships two independent long-running daemons for Paperless-ngx:

1. **OCR Daemon** (`ocr.daemon:main`) — polls for documents tagged with `PRE_TAG_ID`, transcribes them via a vision LLM, and uploads the text back.
2. **Classification Daemon** (`classifier.daemon:main`) — polls for OCR'd documents tagged with `CLASSIFY_PRE_TAG_ID`, classifies metadata via an LLM, and updates Paperless fields.

Both share a `common` package providing: HTTP client (`PaperlessClient`), configuration (`Settings`), retry logic, tag lifecycle management, daemon loop, LLM helpers, concurrency limiting, structured logging, and graceful shutdown.

**Key architectural decisions (good):**
- Tag-driven state machine — no external state store needed.
- Per-document HTTP sessions — avoids connection sharing across threads.
- Processing-lock tags — optimistic locking for multi-instance deployments.
- Model fallback chains — resilience against single-model refusals/failures.
- Thread-pool concurrency with configurable worker counts.
- Clean separation of concerns into focused, testable modules.

**Package layout:**

```
src/
├── common/     (15 modules — shared infrastructure)
├── ocr/        (6 modules — OCR pipeline)
└── classifier/ (11 modules — classification pipeline)
tests/          (22 test files, 350 tests)
```

---

## 2. Critical Bugs Found

### 2.1 `_create_named_item` missing return statement (LOW severity, theoretical)

`src/common/paperless.py:83-124` — The `_create_named_item` method has an implicit `None` return if the `for` loop completes without returning. In practice this cannot happen because the last iteration always either returns or raises, but the function's return type annotation (`-> dict`) is technically violable. A static type checker would flag this.

### 2.2 `_stats` dict is not thread-safe in OCR provider

`src/ocr/provider.py:81-86` — `OpenAIProvider._stats` is a plain dict mutated via `self._stats["attempts"] += 1` from concurrent page-worker threads in `_ocr_pages_in_parallel`. The `+=` operation on a dict value is not atomic. In practice, stats are advisory and races here cause only minor count inaccuracies, but it's a correctness issue.

### 2.3 `library_setup` creates httpx client that is never closed

`src/common/library_setup.py:52` — `httpx.Client(trust_env=False)` is assigned to `openai.http_client` but is never closed during shutdown. This leaks a connection pool for the lifetime of the process. Since the process is a daemon that runs until SIGTERM, this is low-impact but technically a resource leak.

---

## 3. Code Smells and Anti-Patterns

### 3.1 God-object `Settings` class

`src/common/config.py` — The `Settings` class holds **all** configuration for both daemons (40+ attributes) in a single flat class. There is no grouping, no validation of cross-field constraints (e.g., `CLASSIFY_PRE_TAG_ID` defaults to `POST_TAG_ID`, creating a coupling), and no immutability guarantee after construction.

**Recommendation:** Group settings into dataclass-based sub-configs (e.g., `PaperlessConfig`, `OcrConfig`, `ClassifierConfig`, `LlmConfig`). Consider `@dataclass(frozen=True)` for immutability.

### 3.2 Repeated tag-ID nullification pattern

`src/common/config.py:132-152` — The pattern `if X is not None and X <= 0: X = None` is repeated four times for `OCR_PROCESSING_TAG_ID`, `CLASSIFY_POST_TAG_ID`, `CLASSIFY_PROCESSING_TAG_ID`, and `ERROR_TAG_ID`. This should be a reusable helper.

### 3.3 Duplicated daemon bootstrap

`src/ocr/daemon.py:95-151` and `src/classifier/daemon.py:75-147` — Both `main()` functions follow the same pattern: Settings → logging → libraries → signals → semaphore → preflight → stale locks → polling loop. The only differences are tag IDs and the process-item callback. This violates DRY.

### 3.4 Duplicated document-iteration logic

`src/ocr/daemon.py:58-92` and `src/classifier/daemon.py:33-72` — `_iter_docs_to_ocr` and `_iter_docs_to_classify` are structurally identical: iterate documents by tag, skip processed ones, skip claimed ones, yield the rest. Only the tag IDs differ.

### 3.5 Type annotations using `dict` instead of `TypedDict`

Throughout the codebase, Paperless API responses are typed as `dict` (e.g., `doc: dict`). This loses type safety — typos in key access are invisible until runtime. The document structure (`id`, `tags`, `title`, `content`, `created`, `custom_fields`) is well-defined and should be captured in `TypedDict`.

### 3.6 Mutable default state in module-level globals

`src/common/concurrency.py:29` — `_semaphore` is a module-level mutable global. While guarded by `init_llm_semaphore`, there's no protection against double initialization or re-initialization from different threads. Similarly, `src/common/shutdown.py:26` uses a module-level `threading.Event()`.

### 3.7 Mixed abstraction levels in `PaperlessClient`

`src/common/paperless.py` — The client mixes low-level HTTP concerns (`_get`, `_patch`, `_post`, `_raise_for_status_if_server_error`) with business-level operations (`get_documents_to_process`, `update_document`, `create_tag`). The `_create_named_item` method contains matching-algorithm fallback logic that is a business concern, not an HTTP concern.

---

## 4. Missing or Broken Error Handling

### 4.1 `_create_named_item` swallows non-400 errors from intermediate candidates

`src/common/paperless.py:119-124` — If the first `_post` call returns a 400 with a matching_algorithm error, the code retries with the alternate value. However, if `_post` raises a non-HTTP exception (e.g., network error), the `response.raise_for_status()` call will fail with an `UnboundLocalError` because `response` is only assigned if `_post` succeeds. Actually, looking more carefully, `_post` itself handles retries and would raise on exhaustion, so the response assignment is guaranteed here. This is fine.

### 4.2 `ClassificationProcessor._apply_classification` — result parameter untyped

`src/classifier/worker.py:253` — The `result` parameter is untyped (`result,` with no annotation). This should be `result: ClassificationResult`.

### 4.3 No timeout on taxonomy cache refresh

`src/classifier/taxonomy.py:154-162` — `refresh()` calls `list_correspondents()`, `list_document_types()`, and `list_tags()` serially with no aggregate timeout. If the Paperless API is slow, this blocks the entire polling batch for three paginated API calls under the RLock.

### 4.4 `TaxonomyCache.get_or_create_*` re-raises on creation failure after refresh

`src/classifier/taxonomy.py:196-207` — If `create_correspondent` fails, the code refreshes the cache and tries to match again. If the match fails, it `raise`s the original exception. But the `raise` is inside the `except` block, so it re-raises the caught exception — this is correct but the traceback points to the creation call, not the actual root cause (which may be a "name already exists" 400 that a concurrent worker resolved).

### 4.5 `process()` exception in `finally` block can mask original error

`src/ocr/worker.py:121-129` and `src/classifier/worker.py:146-154` — The `finally` block calls `release_processing_tag` and `_log_*_stats`. If `release_processing_tag` raises (despite internal exception handling), it would mask the original exception from the `try` body. The risk is low because `release_processing_tag` catches all exceptions internally, but `_log_*_stats` does not have the same protection.

---

## 5. Performance Concerns

### 5.1 Per-document HTTP client and OpenAI provider creation

`src/ocr/daemon.py:42-55` and `src/classifier/daemon.py:121-130` — A new `PaperlessClient` (with a new `httpx.Client`) and a new `OcrProvider`/`ClassificationProvider` are created for every single document. This means no HTTP connection reuse across documents. While this ensures thread safety, it creates unnecessary TCP connection overhead.

**Recommendation:** Use a connection pool shared across the thread pool, or create clients per-worker-thread rather than per-document.

### 5.2 Taxonomy cache holds RLock during API calls

`src/classifier/taxonomy.py:156-162` — `refresh()` holds the RLock while making three sequential HTTP calls. Any `get_or_create_*` call from another thread blocks for the entire duration. With a slow API, this serializes all classification work during cache refresh.

### 5.3 Full taxonomy loaded into LLM prompt every time

`src/classifier/provider.py:257-266` — The entire taxonomy (up to `CLASSIFY_TAXONOMY_LIMIT` items each for correspondents, types, and tags) is JSON-encoded into every classification prompt. For large Paperless instances, this wastes tokens.

### 5.4 `_top_names` re-sorts on every call

`src/classifier/taxonomy.py:98-122` — Called once per document classification (via `correspondent_names()`, etc.), this sorts the entire taxonomy list every time. The sorted result should be cached during `refresh()`.

---

## 6. Security Vulnerabilities

### 6.1 Pillow `MAX_IMAGE_PIXELS` disabled

`src/common/library_setup.py:47` — `Image.MAX_IMAGE_PIXELS = None` disables the decompression bomb protection. A malicious document with an extremely large image could cause OOM. This is a conscious trade-off for high-DPI scans but should be documented as a known risk.

### 6.2 API token in HTTP headers (acceptable)

`src/common/paperless.py:37` — The Paperless API token is passed via HTTP header. This is the standard Paperless-ngx authentication method and is fine as long as the connection is to a trusted local network or over HTTPS.

### 6.3 No content size limits on document download

`src/common/paperless.py:163-167` — `download_content` reads the entire response body into memory (`response.content`). A pathologically large document could exhaust memory. There is no configurable size limit.

### 6.4 Untrusted LLM output used to create Paperless taxonomy

`src/classifier/worker.py:286-296` — The classification LLM's suggested correspondent, document type, and tags are passed directly to `taxonomy_cache.get_or_create_*`, which creates new Paperless taxonomy items. A misbehaving LLM could inject arbitrary taxonomy entries. The `filter_blacklisted_tags` function only filters four specific tag names.

---

## 7. Test Coverage Analysis

**Current state: 350 tests, 99% line coverage (15 lines uncovered).**

### Uncovered lines:

| File | Lines | Description |
|------|-------|-------------|
| `classifier/daemon.py` | 108-111, 147 | `PreflightError` handling, `__main__` guard |
| `ocr/daemon.py` | 131-134, 154 | `PreflightError` handling, `__main__` guard |
| `common/paperless.py` | 292-294 | `ping` method body |
| `common/stale_lock.py` | 61 | Non-integer doc_id skip in recovery loop |
| `ocr/provider.py` | 68 | `raise NotImplementedError` in ABC |

### Coverage gaps (logical, not line-based):

1. **No integration tests** — all tests mock the HTTP layer and LLM. There are no tests that exercise the real `httpx.Client` or a real Paperless instance.
2. **No concurrency tests** — the thread pool behavior is not tested under actual concurrency (race conditions in claim/release, concurrent taxonomy creation).
3. **No signal handler tests** — `register_signal_handlers` is tested for registration but not for actual signal delivery.
4. **No large-document tests** — no tests exercise behavior with very large images, many pages, or large text content.
5. **No negative validation on Settings** — while there are tests for missing env vars and invalid values, there are no tests for integer overflow, extremely large values, or unicode in env vars.
6. **`_log_ocr_stats` and `_log_classification_stats`** — only tested for no-crash behavior, not for correct log output.

---

## 8. Documentation Gaps

### 8.1 No inline documentation for complex algorithms

- `src/classifier/content_prep.py:134-190` — The page-based truncation algorithm is non-trivial (head+tail page selection with segment slicing) but lacks inline comments explaining the segment-building logic.
- `src/classifier/taxonomy.py:267-282` — `_infer_matching_algorithm` inspects existing tags to decide between int and string format but doesn't explain *why* Paperless changed this between versions.

### 8.2 No API documentation

There is no generated API documentation (Sphinx, pdoc, etc.). The docstrings are generally good but not published.

### 8.3 Missing CHANGELOG

No `CHANGELOG.md` exists to track version history.

### 8.4 Missing CONTRIBUTING guide

No `CONTRIBUTING.md` or development setup instructions beyond what's in the README.

---

## 9. Dependency Concerns

### 9.1 Pinned to specific versions

`pyproject.toml` pins exact versions for `openai==1.35.10`, `Pillow==10.4.0`, `pdf2image==1.17.0`, `structlog==24.2.0`. Only `httpx>=0.27.0` uses a minimum version. Exact pins prevent security updates from being applied automatically.

**Recommendation:** Use compatible-release specifiers (`~=`) or minimum versions with upper bounds for security-critical packages.

### 9.2 OpenAI SDK version is old

`openai==1.35.10` is significantly behind current releases. The SDK has had many improvements and bug fixes since this version. The `_create_with_compat` workaround for parameter stripping suggests some issues may already be resolved in newer versions.

### 9.3 No dependency scanning

The CI pipeline has no dependency vulnerability scanning (e.g., `pip-audit`, `safety`, Dependabot).

### 9.4 `pdf2image` requires system-level `poppler`

The `pdf2image` library requires `poppler-utils` to be installed at the OS level. This dependency is handled in the Dockerfile but is not documented in the README's local development section.

---

## 10. Convention Deviations

### 10.1 Non-standard `src/` layout import paths

The `src/` layout requires `pip install -e .` or PYTHONPATH manipulation. The `tests/conftest.py` adds `src/` to `sys.path` as a workaround, which is non-standard. The setuptools `find_packages(where=["src"])` handles this for installed packages, but the test workaround is fragile.

### 10.2 Module-level `structlog.get_logger` in some modules

Most modules use `log = structlog.get_logger(__name__)` at module level, which is idiomatic for structlog. However, `src/ocr/daemon.py:67` and `src/classifier/daemon.py:44` create loggers *inside functions*, which is inconsistent.

### 10.3 Inconsistent use of `set()` vs `set[int]` annotations

Some functions annotate `tags` as `set[int]`, others accept or return `set` without type parameters. The `clean_pipeline_tags` function accepts `settings` typed as bare `settings` instead of `Settings`.

### 10.4 No `py.typed` marker

The package has type annotations throughout but doesn't include a `py.typed` marker file, so type checkers don't recognize it as a typed package.

### 10.5 No `__all__` in most modules

Only `__init__.py` files define `__all__` (implicitly via imports). Other modules export everything, which pollutes the namespace for IDE autocompletion.

---

## 11. Refactoring Priorities

Based on the audit findings, the recommended refactoring priorities are:

| Priority | Item | Impact |
|----------|------|--------|
| **P0** | Fix thread-safety of `_stats` in OCR provider | Correctness |
| **P0** | Add missing type annotation on `_apply_classification.result` | Type safety |
| **P1** | Extract duplicate daemon bootstrap into shared helper | DRY, maintainability |
| **P1** | Extract duplicate document-iteration logic | DRY, maintainability |
| **P1** | Extract repeated tag-ID nullification into helper | DRY |
| **P1** | Add `TypedDict` for Paperless document payloads | Type safety |
| **P1** | Cache sorted taxonomy names in `TaxonomyCache.refresh()` | Performance |
| **P2** | Group `Settings` into sub-config dataclasses | Maintainability |
| **P2** | Close leaked httpx client in `library_setup` | Resource hygiene |
| **P2** | Add explicit return type to `_create_named_item` | Type safety |
| **P2** | Add `py.typed` marker | Ecosystem compatibility |
| **P3** | Update dependency versions | Security |
| **P3** | Add dependency vulnerability scanning to CI | Security |
| **P3** | Add download size limit | Security hardening |

---

*End of audit report.*
