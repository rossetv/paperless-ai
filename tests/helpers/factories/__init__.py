"""Shared test object factories.

Every test that needs a domain object — a ``Settings``, a Paperless document,
a ``QueryPlan``, a ``SearchResult`` — builds it through a factory here, so the
one field a test actually cares about is the only one it has to spell out
(CODE_GUIDELINES §11.5).  Irrelevant fields carry deterministic defaults.
Hand-rolled per-file builders are a smell: they drift, and the same literal
ends up copied across modules.

The package is split by concept:

- :mod:`tests.helpers.factories._core` — ``Settings``, Paperless documents,
  ``ClassificationResult``, and the store-boundary write shapes.
- :mod:`tests.helpers.factories._search` — the search-pipeline shapes
  (``QueryPlan``, ``RetrievedChunk``, ``SearchResult``, …) and the store
  read-shapes the search tests consume.

Both submodules' factories are re-exported here, so a test imports everything
from ``tests.helpers.factories`` regardless of which submodule defines it.
"""

from __future__ import annotations

from tests.helpers.factories._core import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    make_chunk_input,
    make_chunks,
    make_classification_result,
    make_document,
    make_document_meta,
    make_embedding,
    make_paperless_document,
    make_png_bytes,
    make_search_filters,
    make_settings,
    make_settings_obj,
    make_store_settings,
)
from tests.helpers.factories._search import (
    make_answered,
    make_chunk_hit,
    make_facet_set,
    make_filter_candidates,
    make_index_stats,
    make_indexed_document,
    make_needs_more,
    make_query_plan,
    make_retrieved_chunk,
    make_search_result,
    make_search_settings,
    make_search_stats,
    make_source_document,
    make_taxonomy_entry,
)

__all__ = [
    "DEFAULT_EMBEDDING_DIMENSIONS",
    "make_answered",
    "make_chunk_hit",
    "make_chunk_input",
    "make_chunks",
    "make_classification_result",
    "make_document",
    "make_document_meta",
    "make_embedding",
    "make_facet_set",
    "make_filter_candidates",
    "make_index_stats",
    "make_indexed_document",
    "make_needs_more",
    "make_paperless_document",
    "make_png_bytes",
    "make_query_plan",
    "make_retrieved_chunk",
    "make_search_filters",
    "make_search_result",
    "make_search_settings",
    "make_search_stats",
    "make_settings",
    "make_settings_obj",
    "make_source_document",
    "make_store_settings",
    "make_taxonomy_entry",
]
