"""The SQLite search index store.

This package owns every sqlite3 call and every SQL string in the codebase.
It exposes two API classes — StoreWriter (write side, indexer only) and
StoreReader (read side, search server only) — backed by frozen dataclasses
defined in store.models.

Allowed deps: sqlite3, sqlite-vec, common/.
Forbidden: imports from indexer/, search/, or any daemon package;
           HTTP calls; LLM calls; business logic.

Public surface
--------------
``StoreError`` and ``SchemaNotReadyError`` — the store's exception hierarchy —
and ``SearchFilters`` — the store-boundary input shape — are re-exported here
so callers import them from the package's public surface rather than reaching
into the internal :mod:`store.migrations` / :mod:`store.models` modules
(``CODE_GUIDELINES.md`` §1.7).  ``StoreReader`` / ``StoreWriter`` keep their
own submodule imports so ``import store`` does not eagerly load ``sqlite-vec``.
"""

from __future__ import annotations

from store.migrations import SchemaNotReadyError, StoreError
from store.models import SearchFilters

__all__ = [
    "SchemaNotReadyError",
    "SearchFilters",
    "StoreError",
]
