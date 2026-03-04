# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- `AUDIT.md` — Comprehensive codebase audit report covering architecture, bugs,
  code smells, error handling, performance, security, testing, and dependencies.
- `ARCHITECTURE.md` — Target architecture and module design document.
- `CHANGELOG.md` — This changelog file.
- `common.bootstrap` module — Shared daemon startup sequence extracted from
  `ocr.daemon.main()` and `classifier.daemon.main()`, eliminating duplicate
  bootstrap code.
- `Settings._get_optional_positive_int_env()` — Reusable helper for tag ID
  env vars that treats values <= 0 as `None`.
- Thread-safe stats in `ocr.provider.OpenAIProvider` — `_inc_stat()` with
  `threading.Lock` protects concurrent page-worker stat updates.
- `atexit` handler for the OpenAI httpx client in `library_setup` to prevent
  connection pool leak on daemon shutdown.
- Test suite for `common.bootstrap` (4 tests covering success, config error,
  preflight failure, and stale lock recovery).
- Additional unit tests for `Settings._get_optional_positive_int_env` (zero values).
- Additional unit tests for `OpenAIProvider` thread-safe stats.

### Changed
- `ocr.daemon.main()` and `classifier.daemon.main()` now delegate startup to
  `common.bootstrap.bootstrap_daemon()` instead of duplicating the sequence.
- `Settings` uses `_get_optional_positive_int_env()` for `OCR_PROCESSING_TAG_ID`,
  `CLASSIFY_POST_TAG_ID`, `CLASSIFY_PROCESSING_TAG_ID`, and `ERROR_TAG_ID`,
  replacing four separate `if x <= 0: x = None` blocks.
- `classifier.taxonomy.TaxonomyCache` now caches sorted name lists during
  `refresh()` so `*_names()` calls return a pre-computed list instead of
  re-sorting on every invocation.
- `classifier.worker._apply_classification` now has an explicit
  `result: ClassificationResult` type annotation.
- `common.tags.clean_pipeline_tags` now has an explicit `settings: Settings`
  type annotation (via `TYPE_CHECKING`).
- `common.paperless._create_named_item` now has an explicit unreachable-code
  guard after the for loop to satisfy type checkers.

### Fixed
- `ocr.provider.OpenAIProvider._stats` dict was mutated via `+=` from
  concurrent page-worker threads without synchronization. Now uses a
  `threading.Lock`-protected `_inc_stat()` method.
- `common.library_setup.setup_libraries` created an `httpx.Client` that was
  never closed. Now registered with `atexit` for cleanup.
