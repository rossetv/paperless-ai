"""Tests for search.core: the SearchCore.answer() contract.

Retrieval, source assembly, UI filters and embedding-failure degradation are in
:mod:`test_core_sources`. ``ScriptedLLMClient`` tells planner calls from
synthesiser calls by the system prompt, so one driver serves the whole pipeline.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from search.core import _spec_search_key, _specs_equal
from search.models import RetrievalSpec, SearchResult
from store.models import SearchFilters
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
    make_chat_completion,
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

    def test_list_facets_fetched_exactly_once_per_query(self) -> None:
        """Facets are fetched once (before planning) and reused for resolution.

        The planner sees the live taxonomy and the retrieve phase reuses the same
        facets — there must be no second ``list_facets`` round-trip.
        """
        store_reader = _store_reader_with_hits()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=_embedding_client(),
        )
        core.answer("a normal query")

        store_reader.list_facets.assert_called_once()

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


class TestRefinement:
    """An exploratory NeedsMore triggers one refinement: 4 LLM calls total."""

    def test_needs_more_triggers_one_refinement_pass(self) -> None:
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

        # With no scripted re-plan response the re-plan is a no-op (same specs as
        # pass 1): planner + exploratory synth + re-plan + final synth = 4.
        assert llm_client.planner_calls == 1
        assert llm_client.replan_calls == 1
        assert llm_client.synthesiser_calls == 2
        assert llm_client.total_calls == 4

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
        # planner + exploratory synth + re-plan (no-op) + final synth = 4.
        assert result.stats.llm_calls == 4

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


class _ModeAwareLLM(ScriptedLLMClient):
    """Answers a final-mode synthesis with an answer and any other with needs_more."""

    def __init__(self) -> None:
        super().__init__(
            planner_response=planner_response_json(), synthesiser_responses=[]
        )
        self.synthesiser_modes: list[str] = []

    def route(self, *, model, messages, **kwargs):  # type: ignore[no-untyped-def]
        user = next((m["content"] for m in messages if m["role"] == "user"), "")
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "search-query planning engine" in system:
            return super().route(model=model, messages=messages, **kwargs)
        self.synthesiser_calls += 1
        is_final = "FINAL \u2014 you must answer" in user
        self.synthesiser_modes.append("final" if is_final else "exploratory")
        return make_chat_completion(
            answered_response_json("The final-mode answer [2].", citations=[2])
            if is_final
            else needs_more_response_json("More, please.")
        )


class TestFirstSynthesisMode:
    """The first synthesis runs final only when no refinement is allowed."""

    def _run(self, refinements: int) -> tuple[_ModeAwareLLM, SearchResult]:
        llm_client = _ModeAwareLLM()
        core = build_search_core(
            settings=make_search_settings(SEARCH_MAX_REFINEMENTS=refinements),
            llm_client=llm_client,
            store_reader=_store_reader_with_hits(
                vector_hits=[make_chunk_hit(chunk_id=2, document_id=2)]
            ),
            embedding_client=_embedding_client(),
        )
        return llm_client, core.answer("a query")

    def test_zero_refinements_answers_in_final_mode_not_blank(self) -> None:
        llm_client, result = self._run(0)

        assert llm_client.synthesiser_modes == ["final"]
        assert result.answer == "The final-mode answer [2]."

    def test_refinements_allowed_keeps_first_synthesis_exploratory(self) -> None:
        llm_client, _ = self._run(1)

        assert llm_client.synthesiser_modes[0] == "exploratory"
        assert llm_client.synthesiser_modes[-1] == "final"


class TestPerQueryBudget:
    """The pipeline never exceeds the per-query LLM-call ceiling.

    Each refinement pass costs a re-plan plus a synthesise (plus a re-judge when
    that gate is on), so with the judge off the ceiling is
    ``2 + 2 * SEARCH_MAX_REFINEMENTS``. No re-plan response is scripted, so every
    pass is a no-op re-plan + synthesise with no second retrieve.
    """

    def test_call_count_equals_ceiling(self) -> None:
        """With an always-NeedsMore synth, the loop runs exactly the configured
        number of refinements and stops at the per-query ceiling — the budget
        backstop bounds it (it would loop forever otherwise).
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

        # planner + exploratory + 3 * (re-plan + synth) = 2 + 6 = 8.
        assert llm_client.total_calls == 8
        assert result.stats.llm_calls == 8

    def test_worst_case_makes_ceiling_calls(self) -> None:
        """A lower setting bounds the calls lower: plan + exploratory + one
        (re-plan + synthesise) per refinement pass."""
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

        # plan + exploratory + 2 * (re-plan + synth) = 2 + 4 = 6.
        assert llm_client.total_calls == 6

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

    def test_empty_retrieval_no_match_reason_is_empty_retrieval(self) -> None:
        """Empty retrieval sets no_match_reason='empty_retrieval'."""
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
        assert result.no_match_reason == "empty_retrieval"

    def test_empty_retrieval_candidate_count_is_zero(self) -> None:
        """Empty retrieval sets candidate_count=0 (no documents retrieved)."""
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
        assert result.candidate_count == 0

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


def _no_filter() -> SearchFilters:
    """A SearchFilters with all fields set to 'no restriction'."""
    return SearchFilters(
        date_from=None,
        date_to=None,
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(),
    )


def _make_retrieval_spec(
    *,
    mode: str = "semantic",
    semantic: str | None = "find payslip",
    keywords: tuple[str, ...] = (),
    filters: SearchFilters | None = None,
    rationale: str = "default rationale",
) -> RetrievalSpec:
    return RetrievalSpec(
        mode=mode,  # type: ignore[arg-type]
        semantic=semantic,
        keywords=keywords,
        filters=filters if filters is not None else _no_filter(),
        rationale=rationale,
    )


class TestSpecsEqual:
    """_specs_equal compares only search-determining fields; rationale is excluded.

    The re-plan regenerates rationale on every call, so comparing it would stop the
    no-op guard in SearchCore._refine from ever firing.
    """

    def test_equal_specs_with_identical_rationale(self) -> None:
        """Two identical specs compare as equal."""
        spec = _make_retrieval_spec(rationale="because A")
        assert _specs_equal((spec,), (spec,)) is True

    def test_equal_specs_differing_only_in_rationale(self) -> None:
        """Specs with the same search fields but different rationale are equal."""
        spec_a = _make_retrieval_spec(rationale="first explanation")
        spec_b = _make_retrieval_spec(rationale="completely different explanation")
        assert _specs_equal((spec_a,), (spec_b,)) is True

    def test_different_semantic_makes_specs_unequal(self) -> None:
        """Different semantic text is a different search — specs must be unequal."""
        spec_a = _make_retrieval_spec(semantic="find payslip")
        spec_b = _make_retrieval_spec(semantic="find invoice")
        assert _specs_equal((spec_a,), (spec_b,)) is False

    def test_different_mode_makes_specs_unequal(self) -> None:
        """Different mode (semantic vs keyword) is a different search."""
        spec_a = _make_retrieval_spec(mode="semantic", semantic="payslip", keywords=())
        spec_b = _make_retrieval_spec(
            mode="keyword", semantic=None, keywords=("payslip",)
        )
        assert _specs_equal((spec_a,), (spec_b,)) is False

    def test_different_date_filter_makes_specs_unequal(self) -> None:
        """Different date filter is a different search."""
        filters_a = SearchFilters(
            date_from="2025-04-01",
            date_to="2025-04-30",
            correspondent_id=None,
            document_type_id=None,
            tag_ids=(),
        )
        filters_b = SearchFilters(
            date_from="2025-05-01",
            date_to="2025-05-31",
            correspondent_id=None,
            document_type_id=None,
            tag_ids=(),
        )
        spec_a = _make_retrieval_spec(filters=filters_a, rationale="april")
        spec_b = _make_retrieval_spec(
            filters=filters_b, rationale="may — different text"
        )
        assert _specs_equal((spec_a,), (spec_b,)) is False

    def test_tag_order_normalised(self) -> None:
        """Tag order difference does not count as a different search."""
        filters_a = SearchFilters(
            date_from=None,
            date_to=None,
            correspondent_id=None,
            document_type_id=None,
            tag_ids=(7, 42),
        )
        filters_b = SearchFilters(
            date_from=None,
            date_to=None,
            correspondent_id=None,
            document_type_id=None,
            tag_ids=(42, 7),
        )
        spec_a = _make_retrieval_spec(filters=filters_a, rationale="x")
        spec_b = _make_retrieval_spec(filters=filters_b, rationale="y")
        assert _specs_equal((spec_a,), (spec_b,)) is True

    def test_different_length_tuples_are_unequal(self) -> None:
        """A tuple of two specs is never equal to a tuple of one."""
        spec = _make_retrieval_spec()
        assert _specs_equal((spec,), (spec, spec)) is False

    def test_spec_search_key_excludes_rationale(self) -> None:
        """_spec_search_key returns the same key for two specs that differ only in rationale."""
        spec_a = _make_retrieval_spec(rationale="rationale A")
        spec_b = _make_retrieval_spec(rationale="rationale B")
        assert _spec_search_key(spec_a) == _spec_search_key(spec_b)
