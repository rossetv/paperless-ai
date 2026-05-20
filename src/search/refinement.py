"""Plan-adjustment helpers for the bounded refinement loop (spec §6.3).

These two pure functions serve the two branches of the refinement loop in
core.py:

- ``broaden_plan`` — used when filtered retrieval returns nothing: drop the
  (possibly mis-resolved) filters and retry without them.
- ``adjust_plan`` — used when the synthesiser returns ``NeedsMore``: fold the
  adjustment hint into the plan as an additional semantic query so the next
  retrieval round explores the suggested direction.

Both functions are pure (no I/O, no LLM calls) and return new ``QueryPlan``
instances via ``dataclasses.replace``.  The frozen-dataclass contract means
the input is structurally immutable; these functions make the immutability
explicit by always returning a fresh instance.

Depends on: search/models.py only.
"""

from __future__ import annotations

from dataclasses import replace

from search.models import FilterCandidates, QueryPlan

# The empty sentinel used by broaden_plan so callers can rely on a single
# well-known «no filters» value rather than constructing one ad hoc.
_EMPTY_FILTER_CANDIDATES = FilterCandidates(
    correspondent=None,
    document_type=None,
    tags=(),
    date_from=None,
    date_to=None,
)


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
    return replace(plan, filter_candidates=_EMPTY_FILTER_CANDIDATES)


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
