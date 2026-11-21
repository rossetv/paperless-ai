"""Shared test object factories.

Each factory fills irrelevant fields with deterministic defaults, so a test
spells out only the field it cares about. ``_core`` holds settings, Paperless
and store-write shapes; ``_search`` holds the search-pipeline shapes. Import
everything from this package.
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
    make_judge_candidate,
    make_judge_verdict,
    make_needs_more,
    make_planned_spec,
    make_relevance_thresholds,
    make_retrieval_plan,
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
    "make_judge_candidate",
    "make_judge_verdict",
    "make_needs_more",
    "make_paperless_document",
    "make_planned_spec",
    "make_png_bytes",
    "make_relevance_thresholds",
    "make_retrieval_plan",
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
