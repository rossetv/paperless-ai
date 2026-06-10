"""Tests for search.core — the bounded agentic pipeline (answer() contract).

Verifies the SearchCore.answer contract (spec §6.3):
- A normal query makes exactly plan + one synthesise = 2 LLM calls.
- A query whose exploratory synthesis returns NeedsMore triggers one
  refinement → exactly 3 LLM calls, and SearchStats.refined is True.
- The LLM call count NEVER exceeds 3 under any path — the worst case is
  tested with the refinement budget deliberately raised.
- Empty retrieval (even after broaden_plan) returns a "no matches"
  SearchResult with NO synthesis call — only the planner ran.

Source assembly, retrieve(), UI filters, and embedding-failure degradation are
covered in :mod:`test_core_sources` — this file would otherwise pass the
500-line ceiling (CODE_GUIDELINES §3.1).

The scripted LLM driver (``ScriptedLLMClient``) distinguishes a planner call
from a synthesiser call by the system prompt, so one driver serves the whole
pipeline while the test asserts how many calls of each kind were made.  The
core is assembled by ``build_search_core`` (see conftest.py): real planner,
retriever, and synthesiser stages over mock store / embedding clients.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from search.models import SearchResult
from tests.helpers.factories import (
    make_chunk_hit,
    make_facet_set,
    make_indexed_document,
    make_search_settings,
)
from tests.helpers.llm import (
    ScriptedLLMClient,
    _make_spec,
    answered_response_json,
    needs_more_response_json,
    planner_response_json,
)
from tests.unit.search.conftest import build_search_core


def _store_reader_with_hits(
    *,
    vector_hits: list | None = None,
    documents: list | None = None,
) -> MagicMock:
    """Build a mock StoreReader returning canned hits and indexed documents.

    *vector_hits* defaults to one hit for chunk 1 / document 1; *documents*
    defaults to a single indexed document for id 1.  keyword_search returns
    nothing — these tests exercise the vector path.
    """
    store_reader = MagicMock()
    store_reader.list_facets.return_value = make_facet_set()
    store_reader.vector_search.return_value = (
        vector_hits
        if vector_hits is not None
        else [make_chunk_hit(chunk_id=1, document_id=1)]
    )
    store_reader.keyword_search.return_value = []
    if documents is not None:
        store_reader.get_documents.return_value = documents
    return store_reader


def _embedding_client() -> MagicMock:
    """Build a mock EmbeddingClient returning one deterministic vector."""
    embedding_client = MagicMock()
    embedding_client.embed.return_value = [[0.1, 0.2, 0.3]]
    return embedding_client


# ---------------------------------------------------------------------------
# Normal query — plan + one synthesise = exactly 2 LLM calls
# ---------------------------------------------------------------------------


class TestNormalQuery:
    """A query answerable on the first pass costs exactly 2 LLM calls."""

    def test_normal_query_makes_exactly_two_llm_calls(self) -> None:
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json(
                    "The warranty expires in 2028 [1].", citations=[1]
                )
            ],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=_store_reader_with_hits(),
            embedding_client=_embedding_client(),
        )
        core.answer("when does my boiler warranty expire?")

        assert llm_client.total_calls == 2
        assert llm_client.planner_calls == 1
        assert llm_client.synthesiser_calls == 1

    def test_normal_query_reports_two_llm_calls_in_stats(self) -> None:
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=_store_reader_with_hits(),
            embedding_client=_embedding_client(),
        )
        result = core.answer("a normal query")

        assert result.stats.llm_calls == 2

    def test_normal_query_is_not_marked_refined(self) -> None:
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=_store_reader_with_hits(),
            embedding_client=_embedding_client(),
        )
        result = core.answer("a normal query")

        assert result.stats.refined is False

    def test_normal_query_returns_search_result(self) -> None:
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("The answer is 42 [1].", citations=[1])
            ],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=_store_reader_with_hits(),
            embedding_client=_embedding_client(),
        )
        result = core.answer("a normal query")

        assert isinstance(result, SearchResult)
        assert result.answer == "The answer is 42 [1]."
        assert len(result.sources) == 1


# ---------------------------------------------------------------------------
# Refinement — exploratory NeedsMore → exactly 3 LLM calls, refined=True
# ---------------------------------------------------------------------------


class TestRefinement:
    """An exploratory NeedsMore triggers one refinement: 3 LLM calls total."""

    def test_needs_more_triggers_exactly_three_llm_calls(self) -> None:
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                needs_more_response_json("Look for the 2028 warranty certificate."),
                answered_response_json(
                    "The warranty expires in 2028 [2].", citations=[2]
                ),
            ],
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_MAX_REFINEMENTS=1),
            llm_client=llm_client,
            store_reader=_store_reader_with_hits(
                vector_hits=[make_chunk_hit(chunk_id=2, document_id=2)]
            ),
            embedding_client=_embedding_client(),
        )
        core.answer("when does my boiler warranty expire?")

        assert llm_client.planner_calls == 1
        assert llm_client.synthesiser_calls == 2
        assert llm_client.total_calls == 3

    def test_refinement_sets_refined_flag_true(self) -> None:
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                needs_more_response_json("Broaden the date range."),
                answered_response_json("Final answer [2].", citations=[2]),
            ],
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_MAX_REFINEMENTS=1),
            llm_client=llm_client,
            store_reader=_store_reader_with_hits(
                vector_hits=[make_chunk_hit(chunk_id=2, document_id=2)]
            ),
            embedding_client=_embedding_client(),
        )
        result = core.answer("a query needing refinement")

        assert result.stats.refined is True
        assert result.stats.llm_calls == 3

    def test_refinement_returns_the_final_pass_answer(self) -> None:
        """The result answer is the final synthesise, not the exploratory one."""
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                needs_more_response_json("Need the warranty certificate."),
                answered_response_json(
                    "Resolved on the second pass [2].", citations=[2]
                ),
            ],
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_MAX_REFINEMENTS=1),
            llm_client=llm_client,
            store_reader=_store_reader_with_hits(
                vector_hits=[make_chunk_hit(chunk_id=2, document_id=2)]
            ),
            embedding_client=_embedding_client(),
        )
        result = core.answer("a query")

        assert result.answer == "Resolved on the second pass [2]."

    def test_zero_budget_does_not_refine(self) -> None:
        """With SEARCH_MAX_REFINEMENTS=0 a NeedsMore does NOT trigger a refine."""
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                needs_more_response_json("Would refine, but the budget is zero."),
            ],
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_MAX_REFINEMENTS=0),
            llm_client=llm_client,
            store_reader=_store_reader_with_hits(),
            embedding_client=_embedding_client(),
        )
        result = core.answer("a query")

        # Only planner + the single exploratory synthesise.
        assert llm_client.total_calls == 2
        assert result.stats.refined is False


# ---------------------------------------------------------------------------
# Hard ceiling — the LLM call count NEVER exceeds 3 under any path
# ---------------------------------------------------------------------------


class TestPerQueryBudget:
    """The pipeline never exceeds 2 + SEARCH_MAX_REFINEMENTS LLM calls, and the
    refinement loop genuinely runs that many passes (spec §6.3)."""

    def test_call_count_equals_two_plus_max_refinements(self) -> None:
        """With an always-NeedsMore synth, the loop runs exactly the configured
        number of refinements and stops at 2 + SEARCH_MAX_REFINEMENTS — the
        budget backstop bounds it (it would loop forever otherwise).
        """
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            # Always NeedsMore — would loop forever without the bound.
            synthesiser_responses=[needs_more_response_json("more, always more")],
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_MAX_REFINEMENTS=3),
            llm_client=llm_client,
            store_reader=_store_reader_with_hits(),
            embedding_client=_embedding_client(),
        )
        result = core.answer("a query that always needs more")

        # planner + exploratory + 3 refinements = 5 = 2 + SEARCH_MAX_REFINEMENTS.
        assert llm_client.total_calls == 5
        assert result.stats.llm_calls == 5

    def test_worst_case_makes_two_plus_max_refinements_calls(self) -> None:
        """A lower setting bounds the calls lower: plan + exploratory + one
        synthesise per refinement pass."""
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[needs_more_response_json("more")],
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_MAX_REFINEMENTS=2),
            llm_client=llm_client,
            store_reader=_store_reader_with_hits(),
            embedding_client=_embedding_client(),
        )
        core.answer("worst case query")

        # plan + exploratory + 2 refinements = 4.
        assert llm_client.total_calls == 4

    def test_stats_llm_calls_matches_actual_calls_made(self) -> None:
        """SearchStats.llm_calls is the TRUE total, not a hardcoded constant."""
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[needs_more_response_json("more")],
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_MAX_REFINEMENTS=99),
            llm_client=llm_client,
            store_reader=_store_reader_with_hits(),
            embedding_client=_embedding_client(),
        )
        result = core.answer("a query")

        assert result.stats.llm_calls == llm_client.total_calls


# ---------------------------------------------------------------------------
# Empty retrieval — no-match short-circuit, no synthesis call
# ---------------------------------------------------------------------------


class TestEmptyRetrieval:
    """Empty retrieval (even after broaden_plan) costs only the planner call."""

    def _empty_store_reader(self) -> MagicMock:
        """A StoreReader whose filtered and broadened retrievals both find nothing."""
        store_reader = MagicMock()
        store_reader.list_facets.return_value = make_facet_set()
        store_reader.vector_search.return_value = []
        store_reader.keyword_search.return_value = []
        return store_reader

    def test_empty_retrieval_makes_no_synthesis_call(self) -> None:
        """Empty retrieval even after broadening: only the planner ran."""
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(
                specs=[_make_spec(correspondent="npower")]
            ),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=self._empty_store_reader(),
            embedding_client=_embedding_client(),
        )
        core.answer("a query matching nothing at all")

        assert llm_client.planner_calls == 1
        assert llm_client.synthesiser_calls == 0
        assert llm_client.total_calls == 1

    def test_empty_retrieval_reports_one_llm_call(self) -> None:
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=self._empty_store_reader(),
            embedding_client=_embedding_client(),
        )
        result = core.answer("nothing matches")

        assert result.stats.llm_calls == 1

    def test_empty_retrieval_returns_no_sources(self) -> None:
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=self._empty_store_reader(),
            embedding_client=_embedding_client(),
        )
        result = core.answer("nothing matches")

        assert result.sources == ()
        assert isinstance(result, SearchResult)

    def test_empty_retrieval_answer_states_no_matches(self) -> None:
        """The no-match SearchResult carries a non-empty answer for the UI."""
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=self._empty_store_reader(),
            embedding_client=_embedding_client(),
        )
        result = core.answer("nothing matches")

        assert result.answer != ""

    def test_broaden_retry_runs_before_giving_up(self) -> None:
        """A filtered retrieval that finds nothing is retried broadened; if
        the broadened retrieval finds chunks, synthesis proceeds normally."""
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(
                specs=[_make_spec(correspondent="npower")]
            ),
            synthesiser_responses=[
                answered_response_json("Found after broadening [1].", citations=[1])
            ],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = make_facet_set()
        # First call (filtered) → nothing; second call (broadened) → a hit.
        store_reader.vector_search.side_effect = [
            [],
            [make_chunk_hit(chunk_id=1, document_id=1)],
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [make_indexed_document()]
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=_embedding_client(),
        )
        result = core.answer("npower bill query")

        # planner + one synthesise — the broaden retry is not an LLM call.
        assert llm_client.total_calls == 2
        assert result.answer == "Found after broadening [1]."
        assert len(result.sources) == 1
