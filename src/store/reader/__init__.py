"""Read API for the search index, used by the search pipeline and server.

:class:`StoreReader` (in ``_reader``) owns the connection and delegates to
``_ranked`` (vector and keyword search), ``_lookups`` (look-ups, facets, stats)
and ``_browse`` (the Library listing). It has no write methods.
"""

from __future__ import annotations

from store.models import SearchFilters
from store.reader._reader import StoreReader

__all__ = [
    "SearchFilters",
    "StoreReader",
]
