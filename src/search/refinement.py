"""Pure helpers for the bounded refinement loop (spec §6.3).

These pure functions serve the branches of the refinement loop in core.py:

- ``build_broad_semantic_plan`` — shared builder for the minimal single-spec
  plan used by both the trivial short-circuit and the planner fallback.
- ``broaden_plan`` — used when filtered retrieval returns nothing: drop every
  spec's (possibly mis-resolved) filter guess and retry without them.
- ``merge_chunks`` — used after the refined retrieval round: union the two
  rounds' retrieved chunks so the final synthesise sees both.
- ``trivial_plan`` — the RAG-08 short-circuit: build the planner-fallback-shaped
  plan in code when a trivial query lets the core skip the planner LLM call.

Every function is pure (no I/O, no LLM calls).  The plan helpers return new
``RetrievalPlan`` instances; the frozen-dataclass contract means the input is
structurally immutable, and they make that immutability explicit by always
returning a fresh instance.

Depends on: search/models.py only.
"""

from __future__ import annotations

from dataclasses import replace

from search.models import (
    EMPTY_FILTER_CANDIDATES,
    PlannedSpec,
    RetrievalPlan,
    RetrievedChunk,
)


def broaden_plan(plan: RetrievalPlan) -> RetrievalPlan:
    """Return a new RetrievalPlan with every spec's filter guess cleared.

    Used in the empty-retrieval branch: when a filtered search finds nothing,
    the filters may be the problem (e.g. the planner hallucinated a
    correspondent that does not exist in the taxonomy).  Dropping them and
    retrying gives the retriever the best chance of surfacing any relevant
    result.

    Each spec's mode, semantic text, keywords, and rationale are preserved
    unchanged; only its ``filter_guess`` is reset to
    :data:`~search.models.EMPTY_FILTER_CANDIDATES`.  The plan's ``clarify`` is
    carried over verbatim.

    Args:
        plan: The original multi-spec plan produced by the planner.

    Returns:
        A new ``RetrievalPlan`` whose every spec carries empty filter guesses.
    """
    broadened_specs = tuple(
        replace(spec, filter_guess=EMPTY_FILTER_CANDIDATES) for spec in plan.specs
    )
    return RetrievalPlan(specs=broadened_specs, clarify=plan.clarify)


def build_broad_semantic_plan(query: str, rationale: str) -> RetrievalPlan:
    """Return a single-spec broad semantic ``RetrievalPlan`` on *query*.

    The shared builder for every code path that needs the minimal safe plan
    (one semantic spec, no filters, no clarify signal).  Using one builder
    keeps the shape consistent: both the trivial short-circuit and the planner
    fallback always produce the same structure, differing only in their rationale
    label.

    Args:
        query: The raw user search query used as the semantic text.
        rationale: A short label describing why this broad plan was chosen
            (e.g. ``"trivial: broad semantic search"``).

    Returns:
        A frozen ``RetrievalPlan`` containing one broad semantic spec.
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


def trivial_plan(query: str) -> RetrievalPlan:
    """Build the planner-fallback-shaped plan for a trivial query (RAG-08).

    Delegates to :func:`build_broad_semantic_plan` with the trivial rationale.
    Used by the core when the ``SEARCH_SKIP_PLANNER_FOR_TRIVIAL`` short-circuit
    fires — retrieval runs a vector search on the raw query exactly as it would
    for the planner's own fallback, so skipping the planner LLM costs nothing
    for a query the planner would only have restated.

    Args:
        query: The raw user search query.

    Returns:
        A frozen ``RetrievalPlan`` containing one broad semantic spec.
    """
    return build_broad_semantic_plan(query, rationale="trivial: broad semantic search")


def merge_chunks(
    previous: list[RetrievedChunk],
    new: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """Merge two retrieved-chunk lists, de-duplicating by chunk id.

    The refinement pass synthesises over the union of both retrieval rounds
    (spec §6.3).  A chunk surfaced by both rounds is kept once; the first
    occurrence — the higher-ranked one, since *previous* leads — is retained.
    The merged list is ordered by fused score, highest first.

    Args:
        previous: The chunks from the first retrieval round.
        new: The chunks from the refined retrieval round.

    Returns:
        The de-duplicated union, ordered by ``rrf_score`` descending.
    """
    merged_by_id: dict[int, RetrievedChunk] = {}
    for chunk in [*previous, *new]:
        if chunk.chunk_id not in merged_by_id:
            merged_by_id[chunk.chunk_id] = chunk
    merged = list(merged_by_id.values())
    merged.sort(key=lambda chunk: chunk.rrf_score, reverse=True)
    return merged
