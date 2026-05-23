"""Read API for the search index store.

The ``store.reader`` package is the sole read-side interface to the SQLite
search index.  The search pipeline and the search server use it to run vector
search, keyword search, document and chunk look-ups, taxonomy and facet
queries, index statistics, and the integrity check.

The package is split by concept (CODE_GUIDELINES §3.2):

- :mod:`store.reader._ranked` — ranked retrieval (``vector_search``,
  ``keyword_search``) and its SQL filter helpers.
- :mod:`store.reader._lookups` — look-ups and introspection
  (``get_documents``, ``get_chunks``, ``get_taxonomy``, ``list_facets``,
  ``get_stats``, ``quick_check``).
- :mod:`store.reader._browse` — the Library document-browse query
  (``list_documents``).
- :mod:`store.reader._reader` — the :class:`StoreReader` facade that owns the
  connection and the query lock and delegates to the three concept-modules.

No write method exists on :class:`StoreReader`.  Read-only access is enforced
structurally: the API has no write surface, and the indexer's flock makes it
the sole writer (SPEC §3.2).

:class:`~store.models.SearchFilters` is re-exported here for convenience — it
is a store-boundary input shape and its canonical definition lives in
:mod:`store.models` alongside the other boundary dataclasses.

Allowed deps: sqlite3, sqlite_vec, store.schema, store.migrations,
    store.models, common.config.
Forbidden: imports from indexer/, search/, or any package above store/.
No HTTP, no LLM calls, no business logic.
"""

from __future__ import annotations

from store.models import SearchFilters
from store.reader._reader import StoreReader

__all__ = [
    "SearchFilters",
    "StoreReader",
]
