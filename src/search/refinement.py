"""Pure helpers for the bounded refinement loop (spec §6.3).

These pure functions serve the branches of the refinement loop in core.py:

- ``broaden_plan`` — used when filtered retrieval returns nothing: drop the
  (possibly mis-resolved) filters and retry without them.
- ``adjust_plan`` — used when the synthesiser returns ``NeedsMore``: fold the
  adjustment hint into the plan as an additional semantic query so the next
  retrieval round explores the suggested direction.
- ``merge_chunks`` — used after the refined retrieval round: union the two
  rounds' retrieved chunks so the final synthesise sees both.
- ``trivial_plan`` — the RAG-08 short-circuit: build the planner-fallback-shaped
  plan in code when a trivial query lets the core skip the planner LLM call.
- ``is_weak_retrieval`` — the RAG-10 threshold test: whether the retrieved
  chunks are too few / too low-scoring to be worth the exploratory synth call.

Every function is pure (no I/O, no LLM calls).  The plan helpers return new
``QueryPlan`` instances via ``dataclasses.replace``; the frozen-dataclass
contract means the input is structurally immutable, and they make that
immutability explicit by always returning a fresh instance.

Depends on: search/models.py only.
"""

from __future__ import annotations

from dataclasses import replace

from search.models import EMPTY_FILTER_CANDIDATES, QueryPlan, RetrievedChunk


def broaden_plan(plan: QueryPlan) -> QueryPlan:
    """Return a new QueryPlan with all filter candidates cleared.

    Used in the empty-retrieval branch: when a filtered search finds nothing,
    the filters may be the problem (e.g. the planner hallucinated a
    correspondent that does not exist in the taxonomy).  Dropping them and
    retrying gives the retriever the best chance of surfacing any relevant
    result.

    The ``semantic_queries``, ``keyword_terms``, and ``sub_questions`` of the
    original plan are preserved unchanged.

    Args:
        plan: The original query plan produced by the planner.

    Returns:
        A new ``QueryPlan`` with an empty ``FilterCandidates`` and all other
        fields taken from *plan*.
    """
    return replace(plan, filter_candidates=EMPTY_FILTER_CANDIDATES)


def trivial_plan(query: str) -> QueryPlan:
    """Build the planner-fallback-shaped plan for a trivial query (RAG-08).

    Identical in shape to ``planner._fallback_plan``: the raw query is the sole
    semantic query, every other field empty. Used by the core when the
    ``SEARCH_SKIP_PLANNER_FOR_TRIVIAL`` short-circuit fires — retrieval runs
    vector + FTS on the raw query exactly as it would for the planner's own
    fallback, so skipping the planner LLM costs nothing for a query the planner
    would only have restated.

    Args:
        query: The raw user search query.

    Returns:
        A frozen ``QueryPlan`` containing only *query* as its semantic query.
    """
    return QueryPlan(
        semantic_queries=(query,),
        keyword_terms=(),
        filter_candidates=EMPTY_FILTER_CANDIDATES,
        sub_questions=(),
    )


def is_weak_retrieval(
    chunks: list[RetrievedChunk], *, min_chunks: int, min_score: float
) -> bool:
    """Return whether retrieval is too weak to be worth a synth call (RAG-10).

    Weak when fewer than *min_chunks* chunks were found, or the best fused (RRF)
    score is below *min_score*. The thresholds are passed in (not read off
    Settings) so this stays a pure helper with no config dependency — the core
    reads ``SEARCH_WEAK_RETRIEVAL_MIN_CHUNKS`` / ``SEARCH_WEAK_RETRIEVAL_MIN_SCORE``
    and passes them. With the defaults (1 and 0.0) this is inert; the whole gate
    sits behind the default-off ``SEARCH_SKIP_SYNTH_ON_WEAK_RETRIEVAL`` flag
    (spec §4.7).

    Args:
        chunks: The retrieved chunks (assumed non-empty by the caller).
        min_chunks: The minimum chunk count below which retrieval is weak.
        min_score: The minimum best-fused-score below which retrieval is weak.

    Returns:
        True when retrieval is below either floor.
    """
    if len(chunks) < min_chunks:
        return True
    best_score = max(chunk.rrf_score for chunk in chunks)
    return best_score < min_score


def adjust_plan(plan: QueryPlan, adjustment: str) -> QueryPlan:
    """Return a new QueryPlan extended with the synthesiser's adjustment hint.

    Used in the ``NeedsMore`` branch: the synthesiser has seen the retrieved
    chunks and determined that a different angle is required.  The *adjustment*
    string (``NeedsMore.adjustment``) is appended as an additional semantic
    query so the retriever explores that direction on the next pass.

    The original semantic queries and keyword terms are preserved; the
    adjustment is *added*, never replacing existing content.  Filter candidates
    and sub-questions are carried over unchanged.

    Args:
        plan: The original query plan to build upon.
        adjustment: Free-text hint from the synthesiser describing how the
            retrieval should change (e.g. "include documents from 2018–2022").

    Returns:
        A new ``QueryPlan`` with *adjustment* appended to ``semantic_queries``
        and all other fields taken from *plan*.
    """
    return replace(
        plan,
        semantic_queries=(*plan.semantic_queries, adjustment),
    )


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
