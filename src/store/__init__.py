"""The SQLite search index store.

The only package that talks to SQLite. ``StoreWriter`` (indexer) and
``StoreReader`` (search server) live in submodules so ``import store`` does not
eagerly load ``sqlite-vec``.
"""

from __future__ import annotations

from store.migrations import SchemaNotReadyError, StoreError
from store.models import SearchFilters

__all__ = [
    "SchemaNotReadyError",
    "SearchFilters",
    "StoreError",
]
