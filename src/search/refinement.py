"""Pure plan and chunk helpers for the refinement loop in :mod:`search.core`."""

from __future__ import annotations

from dataclasses import replace

from search.models import (
    EMPTY_FILTER_CANDIDATES,
    PlannedSpec,
    RetrievalPlan,
    RetrievedChunk,
)


def broaden_plan(plan: RetrievalPlan) -> RetrievalPlan:
    """Return a copy of *plan* with every spec's filter guess cleared.

    Used when a filtered search finds nothing: the filters may be the problem
    (e.g. the planner hallucinated a correspondent), so retry without them.
    """
    broadened_specs = tuple(
        replace(spec, filter_guess=EMPTY_FILTER_CANDIDATES) for spec in plan.specs
    )
    return RetrievalPlan(specs=broadened_specs, clarify=plan.clarify)


def build_broad_semantic_plan(query: str, rationale: str) -> RetrievalPlan:
    """Return the minimal safe plan: one semantic spec on *query*, no filters.

    Shared by the trivial short-circuit and the planner fallback so both produce
    the same shape.
    """
    return RetrievalPlan(
        specs=(
            PlannedSpec(
                mode="semantic",
                semantic=query,
                keywords=(),
                filter_guess=EMPTY_FILTER_CANDIDATES,
                rationale=rationale,
            ),
        ),
        clarify=None,
    )


def raw_rag_plan(query: str) -> RetrievalPlan:
    """Return a deterministic hybrid (vector + FTS) RetrievalPlan — no LLM call.

    Two specs on the raw *query*: one ``semantic`` spec (the retriever's vector
    pass) and one ``keyword`` spec (its FTS/BM25 pass). The retriever runs the
    vector pass only for semantic specs and the FTS pass only for keyword specs,
    so genuine hybrid retrieval needs both spelled out — a single broad-semantic
    spec (:func:`build_broad_semantic_plan`) would be vector-only. Backs
    :meth:`~search.core.SearchCore.retrieve`, and thus the MCP ``semantic_search``
    tool, which must cost zero chat LLM calls.
    """
    # Naive whitespace tokens: FTS5/BM25 already down-weights common terms, so
    # a stopword strip waits until recall measurably suffers.
    return RetrievalPlan(
        specs=(
            PlannedSpec(
                mode="semantic",
                semantic=query,
                keywords=(),
                filter_guess=EMPTY_FILTER_CANDIDATES,
                rationale="raw RAG: vector pass on the raw query",
            ),
            PlannedSpec(
                mode="keyword",
                semantic=None,
                keywords=tuple(query.split()),
                filter_guess=EMPTY_FILTER_CANDIDATES,
                rationale="raw RAG: FTS pass on the raw query",
            ),
        ),
        clarify=None,
    )


def trivial_plan(query: str) -> RetrievalPlan:
    """Build the planner-fallback-shaped plan for a trivial query.

    Used when ``SEARCH_SKIP_PLANNER_FOR_TRIVIAL`` fires: retrieval runs exactly
    as for the planner's own fallback, so skipping the planner LLM loses nothing.
    """
    return build_broad_semantic_plan(query, rationale="trivial: broad semantic search")


def merge_chunks(
    previous: list[RetrievedChunk],
    new: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """Union two retrieval rounds by chunk id, ordered by ``rrf_score`` descending.

    A chunk in both rounds keeps its occurrence from *previous*.
    """
    merged_by_id: dict[int, RetrievedChunk] = {}
    for chunk in [*previous, *new]:
        if chunk.chunk_id not in merged_by_id:
            merged_by_id[chunk.chunk_id] = chunk
    merged = list(merged_by_id.values())
    merged.sort(key=lambda chunk: chunk.rrf_score, reverse=True)
    return merged
