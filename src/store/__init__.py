"""The SQLite search index store.

This package owns every sqlite3 call and every SQL string in the codebase.
It exposes two API classes — StoreWriter (write side, indexer only) and
StoreReader (read side, search server only) — backed by frozen dataclasses
defined in store.models.

Allowed deps: sqlite3, sqlite-vec, common/.
Forbidden: imports from indexer/, search/, or any daemon package;
           HTTP calls; LLM calls; business logic.
"""
