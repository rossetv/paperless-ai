"""Tests for Layer 0 (degenerate-input guard) and Layer 2 (relevance gate) in
search.core (Task 6 of the fail-fast feature).

Layer 0 — short query guard:
- A query under the char floor → outcome_kind=="clarify", planner NOT called.

Layer 2 — relevance gate (threshold must be set non-zero to exercise the gate;
  production defaults to 0.0, which makes it inert until Task 4 calibrates it):
- Low similarity + no keyword hit → outcome_kind=="no_match", synth NOT called.
- Low similarity + keyword hit → synth called (keyword-hit protection).
- best_vector_similarity is None → synth called (fail-open).
- SEARCH_GATE_RELEVANCE=False → synth called even when signal is weak.
- Normal high-similarity query → outcome_kind=="answered".

Ceiling: every path ≤ 3 LLM calls.

retrieve() must NOT apply Layer 2 (advisory only — spec §7): the relevance gate
is checked only in _answer_uncached, not in retrieve().
"""

from __future__ import annotations

from unittest.mock import MagicMock

from search.cache import reset_search_result_cache
from tests.helpers.factories import (
    make_chunk_hit,
    make_facet_set,
    make_index_stats,
    make_indexed_document,
    make_search_settings,
)
from tests.helpers.llm import (
    ScriptedLLMClient,
    _make_spec,
    answered_response_json,
    planner_response_json,
)
from tests.unit.search.conftest import build_search_core


# ---------------------------------------------------------------------------
# Store-reader helpers
# ---------------------------------------------------------------------------


def _store_reader_with_hits(
    *,
    vector_hits: list | None = None,
    keyword_hits: list | None = None,
) -> MagicMock:
    """A StoreReader returning the supplied hits; both default to a single hit."""
    store_reader = MagicMock()
    store_reader.list_facets.return_value = make_facet_set()
    store_reader.vector_search.return_value = (
        vector_hits
        if vector_hits is not None
        else [make_chunk_hit(chunk_id=1, document_id=1, score=0.1)]
    )
    store_reader.keyword_search.return_value = (
        keyword_hits if keyword_hits is not None else []
    )
    store_reader.get_documents.return_value = [make_indexed_document()]
    store_reader.get_stats.return_value = make_index_stats(
        document_count=1, chunk_count=3
    )
    return store_reader


def _empty_store_reader() -> MagicMock:
    """A StoreReader that returns no hits at all."""
    store_reader = MagicMock()
    store_reader.list_facets.return_value = make_facet_set()
    store_reader.vector_search.return_value = []
    store_reader.keyword_search.return_value = []
    return store_reader


def _embedding_client() -> MagicMock:
    client = MagicMock()
    client.embed.return_value = [[0.1, 0.2, 0.3]]
    return client


def _core(llm_client, store_reader, **overrides):
    settings = make_search_settings(**overrides)
    return build_search_core(
        settings=settings,
        llm_client=llm_client,
        store_reader=store_reader,
        embedding_client=_embedding_client(),
    )


def _answered_llm(*, planner_json: str | None = None) -> ScriptedLLMClient:
    """LLM client that returns a normal planner plan and a simple Answered."""
    return ScriptedLLMClient(
        planner_response=planner_json
        if planner_json is not None
        else planner_response_json(),
        synthesiser_responses=[
            answered_response_json("Good answer [1].", citations=[1])
        ],
    )


# ---------------------------------------------------------------------------
# Layer 0 — degenerate-input guard
# ---------------------------------------------------------------------------


class TestLayer0ShortQueryGuard:
    """A query shorter than SEARCH_MIN_QUERY_CHARS is rejected before the planner."""

    def setup_method(self) -> None:
        reset_search_result_cache()

    def test_single_char_query_returns_clarify_outcome(self) -> None:
        """A single-character query → outcome_kind == 'clarify'."""
        llm_client = _answered_llm()
        core = _core(llm_client, _store_reader_with_hits(), SEARCH_MIN_QUERY_CHARS=2)
        result = core.answer("a")
        assert result.outcome_kind == "clarify"

    def test_empty_query_returns_clarify_outcome(self) -> None:
        """An empty string → outcome_kind == 'clarify'."""
        llm_client = _answered_llm()
        core = _core(llm_client, _store_reader_with_hits(), SEARCH_MIN_QUERY_CHARS=2)
        result = core.answer("")
        assert result.outcome_kind == "clarify"

    def test_whitespace_only_query_returns_clarify_outcome(self) -> None:
        """Pure whitespace is treated as degenerate (strip() reduces it below floor)."""
        llm_client = _answered_llm()
        core = _core(llm_client, _store_reader_with_hits(), SEARCH_MIN_QUERY_CHARS=2)
        result = core.answer("   ")
        assert result.outcome_kind == "clarify"

    def test_short_query_planner_is_not_called(self) -> None:
        """Layer 0 fires before the planner — zero LLM calls."""
        llm_client = _answered_llm()
        core = _core(llm_client, _store_reader_with_hits(), SEARCH_MIN_QUERY_CHARS=2)
        core.answer("x")
        assert llm_client.planner_calls == 0

    def test_short_query_synthesiser_is_not_called(self) -> None:
        """Layer 0 fires before synthesis — zero LLM calls."""
        llm_client = _answered_llm()
        core = _core(llm_client, _store_reader_with_hits(), SEARCH_MIN_QUERY_CHARS=2)
        core.answer("x")
        assert llm_client.synthesiser_calls == 0

    def test_short_query_makes_zero_llm_calls(self) -> None:
        """Layer 0 costs absolutely no LLM calls."""
        llm_client = _answered_llm()
        core = _core(llm_client, _store_reader_with_hits(), SEARCH_MIN_QUERY_CHARS=2)
        result = core.answer("a")
        assert llm_client.total_calls == 0
        assert result.stats.llm_calls == 0

    def test_query_at_exactly_the_floor_proceeds(self) -> None:
        """A query of exactly SEARCH_MIN_QUERY_CHARS chars is NOT rejected."""
        llm_client = _answered_llm()
        store_reader = _store_reader_with_hits()
        core = _core(llm_client, store_reader, SEARCH_MIN_QUERY_CHARS=2)
        result = core.answer("ab")
        # Planner was called — Layer 0 did not fire.
        assert llm_client.planner_calls == 1
        assert result.outcome_kind != "clarify"

    def test_query_above_floor_proceeds(self) -> None:
        """A query well above the floor is answered normally."""
        llm_client = _answered_llm()
        core = _core(llm_client, _store_reader_with_hits(), SEARCH_MIN_QUERY_CHARS=2)
        result = core.answer("boiler warranty")
        assert result.outcome_kind == "answered"
        assert llm_client.total_calls == 2

    def test_short_query_has_no_sources(self) -> None:
        """Layer 0 clarify result carries no sources."""
        llm_client = _answered_llm()
        core = _core(llm_client, _store_reader_with_hits(), SEARCH_MIN_QUERY_CHARS=2)
        result = core.answer("z")
        assert result.sources == ()

    def test_layer0_in_retrieve_also_returns_clarify(self) -> None:
        """retrieve() also applies Layer 0 — short query → clarify, retriever not called."""
        llm_client = _answered_llm()
        store_reader = _store_reader_with_hits()
        core = _core(llm_client, store_reader, SEARCH_MIN_QUERY_CHARS=2)
        result = core.retrieve("a")
        assert result.outcome_kind == "clarify"
        assert llm_client.planner_calls == 0
        store_reader.vector_search.assert_not_called()

    def test_short_query_ceiling_respected(self) -> None:
        """Layer 0 path makes at most 3 LLM calls (actually 0)."""
        llm_client = _answered_llm()
        core = _core(llm_client, _store_reader_with_hits(), SEARCH_MIN_QUERY_CHARS=2)
        result = core.answer("a")
        assert result.stats.llm_calls <= 3


# ---------------------------------------------------------------------------
# H3 — an empty-specs plan + a dated query must not 500 the endpoint
# ---------------------------------------------------------------------------


class TestEmptyPlanDatedQuery:
    """A planner ``{"specs": []}`` response over a dated query is handled cleanly.

    With the adequacy gate off, ``{"specs": []}`` parses to
    ``RetrievalPlan(specs=())``; the deterministic date safety net then fires on
    the dated query with an empty resolved list. This used to raise an uncaught
    IndexError (a 500 on the billable search endpoint); the safety net now
    synthesises a broad-semantic base from the raw query instead.
    """

    def setup_method(self) -> None:
        reset_search_result_cache()

    def _empty_specs_llm(self) -> ScriptedLLMClient:
        return ScriptedLLMClient(
            planner_response=planner_response_json(specs=[]),
            synthesiser_responses=[
                answered_response_json("Found something [1].", citations=[1])
            ],
        )

    def test_answer_empty_plan_dated_query_does_not_500(self) -> None:
        """core.answer with an empty plan + a year in the query returns cleanly."""
        llm_client = self._empty_specs_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(),
            SEARCH_GATE_ADEQUACY=False,
            SEARCH_GATE_JUDGE=False,
        )

        # The reproduction query names an explicit period; the old code raised
        # IndexError here. It must now return a real SearchResult.
        result = core.answer("invoices 2025")

        assert result.outcome_kind in ("answered", "no_match")
        assert llm_client.planner_calls == 1

    def test_retrieve_empty_plan_dated_query_does_not_500(self) -> None:
        """core.retrieve with an empty plan + a dated query returns cleanly too."""
        llm_client = self._empty_specs_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(),
            SEARCH_GATE_ADEQUACY=False,
        )

        result = core.retrieve("invoices 2025")

        # retrieve() never synthesises; it returns sources (or none) without raising.
        assert result.outcome_kind in ("answered", "no_match")

    def test_answer_empty_plan_non_dated_query_no_match(self) -> None:
        """An empty plan + a non-temporal query yields a clean no-match, not a crash."""
        llm_client = self._empty_specs_llm()
        core = _core(
            llm_client,
            _empty_store_reader(),
            SEARCH_GATE_ADEQUACY=False,
        )

        result = core.answer("invoices")

        # No specs, no safety net, no hits — a no-match, never an exception.
        assert result.outcome_kind == "no_match"


# ---------------------------------------------------------------------------
# Layer 2 — relevance gate
# ---------------------------------------------------------------------------


class TestLayer2RelevanceGate:
    """Layer 2 rejects retrieval with low absolute similarity and no keyword hit.

    All tests set SEARCH_RELEVANCE_MIN_SIMILARITY=0.5 (non-zero) to exercise the
    gate — with the production default of 0.0 the gate is intentionally inert.

    The retriever converts distance → similarity via 1/(1+distance). With
    score=0.9 (distance) the similarity is 1/1.9 ≈ 0.526; with score=5.0
    the similarity is 1/6 ≈ 0.167.  We use score values that reliably land
    on the intended side of the 0.5 threshold.
    """

    _MIN_SIM = 0.5  # non-zero threshold used in all Layer-2 tests

    def setup_method(self) -> None:
        reset_search_result_cache()

    # --- core path: weak signal → no_match, synth NOT called ---

    def test_low_similarity_no_keyword_returns_no_match(self) -> None:
        """Low similarity + no keyword hit → outcome_kind == 'no_match'."""
        # score=5.0 → similarity=1/6≈0.167, which is below 0.5.
        weak_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=5.0)]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=weak_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("house deeds in Spain")
        assert result.outcome_kind == "no_match"

    def test_low_similarity_no_keyword_synth_not_called(self) -> None:
        """Layer 2 fires: synthesiser must not be called."""
        weak_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=5.0)]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=weak_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        core.answer("house deeds in Spain")
        assert llm_client.synthesiser_calls == 0

    def test_low_similarity_no_keyword_no_sources(self) -> None:
        """Layer 2 no_match result has no sources."""
        weak_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=5.0)]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=weak_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("house deeds in Spain")
        assert result.sources == ()

    def test_no_match_answer_is_the_spec_message(self) -> None:
        """The no_match answer carries the exact spec §11 message."""
        _EXPECTED = (
            "I couldn't find any documents matching that. "
            "Try rephrasing, or broaden your search."
        )
        weak_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=5.0)]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=weak_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("house deeds in Spain")
        assert result.answer == _EXPECTED

    def test_layer2_ceiling_respected(self) -> None:
        """Layer 2 path: at most 3 LLM calls (only planner ran)."""
        weak_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=5.0)]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=weak_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("house deeds in Spain")
        assert result.stats.llm_calls <= 3

    # --- keyword-hit protection: low similarity + keyword hit → synth called ---
    #
    # The retriever only runs keyword search when plan.keyword_terms is non-empty
    # (search/retriever.py).  We therefore use a planner JSON that includes a
    # keyword term so the retriever actually calls keyword_search and the mock
    # keyword_hits contribute has_keyword_hit=True to the RetrievalSignal.

    def test_low_similarity_with_keyword_hit_synth_is_called(self) -> None:
        """A keyword hit protects against Layer 2 rejection even when sim is low."""
        weak_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=5.0)]
        keyword_hit = [make_chunk_hit(chunk_id=2, document_id=1, score=1.0)]
        # Use a planner response with keyword_terms so the retriever runs
        # keyword_search and produces has_keyword_hit=True in the signal.
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(
                specs=[
                    _make_spec(),
                    _make_spec(mode="keyword", semantic=None, keywords=["warranty"]),
                ]
            ),
            synthesiser_responses=[
                answered_response_json("Found it [1].", citations=[1])
            ],
        )
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=weak_hits, keyword_hits=keyword_hit),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        core.answer("boiler warranty certificate")
        assert llm_client.synthesiser_calls == 1

    def test_low_similarity_with_keyword_hit_outcome_is_answered(self) -> None:
        """Keyword protection: outcome_kind is 'answered', not 'no_match'."""
        weak_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=5.0)]
        keyword_hit = [make_chunk_hit(chunk_id=2, document_id=1, score=1.0)]
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(
                specs=[
                    _make_spec(),
                    _make_spec(mode="keyword", semantic=None, keywords=["warranty"]),
                ]
            ),
            synthesiser_responses=[
                answered_response_json("Found it [1].", citations=[1])
            ],
        )
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=weak_hits, keyword_hits=keyword_hit),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("boiler warranty certificate")
        assert result.outcome_kind == "answered"

    # --- fail-open: None similarity → synth called ---

    def test_none_similarity_synth_is_called_fail_open(self) -> None:
        """When no vector search ran (sim is None), Layer 2 must NOT reject."""
        # No vector hits → best_vector_similarity is None.
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(
                specs=[
                    _make_spec(),
                    _make_spec(mode="keyword", semantic=None, keywords=["warranty"]),
                ]
            ),
            synthesiser_responses=[
                answered_response_json("Found it [1].", citations=[1])
            ],
        )
        # keyword_hits provides chunks so retrieval is non-empty.
        keyword_hit = [make_chunk_hit(chunk_id=1, document_id=1, score=1.0)]
        store_reader = _store_reader_with_hits(vector_hits=[], keyword_hits=keyword_hit)
        core = _core(
            llm_client,
            store_reader,
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        core.answer("warranty")
        assert llm_client.synthesiser_calls == 1

    def test_none_similarity_outcome_is_not_no_match(self) -> None:
        """Fail-open path: outcome_kind must not be 'no_match'."""
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(
                specs=[
                    _make_spec(),
                    _make_spec(mode="keyword", semantic=None, keywords=["warranty"]),
                ]
            ),
            synthesiser_responses=[
                answered_response_json("Found it [1].", citations=[1])
            ],
        )
        keyword_hit = [make_chunk_hit(chunk_id=1, document_id=1, score=1.0)]
        store_reader = _store_reader_with_hits(vector_hits=[], keyword_hits=keyword_hit)
        core = _core(
            llm_client,
            store_reader,
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("warranty")
        assert result.outcome_kind == "answered"

    # --- SEARCH_GATE_RELEVANCE=False: gate disabled, synth called ---

    def test_gate_disabled_synth_called_even_when_signal_weak(self) -> None:
        """When SEARCH_GATE_RELEVANCE=False the gate is bypassed unconditionally."""
        weak_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=5.0)]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=weak_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=False,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        core.answer("house deeds in Spain")
        assert llm_client.synthesiser_calls == 1

    def test_gate_disabled_outcome_is_answered(self) -> None:
        """Gate off: the result is 'answered', not 'no_match'."""
        weak_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=5.0)]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=weak_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=False,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("house deeds in Spain")
        assert result.outcome_kind == "answered"

    # --- high-similarity normal query → answered ---

    def test_high_similarity_normal_query_is_answered(self) -> None:
        """A genuine, relevant query follows the normal answered path."""
        # score=0.1 → similarity=1/1.1≈0.909, well above the 0.5 threshold.
        strong_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=0.1)]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=strong_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("when does my boiler warranty expire?")
        assert result.outcome_kind == "answered"
        assert llm_client.synthesiser_calls == 1

    def test_high_similarity_ceiling_respected(self) -> None:
        """Normal path: exactly 2 LLM calls (plan + synth) ≤ 3."""
        strong_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=0.1)]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=strong_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("when does my boiler warranty expire?")
        assert result.stats.llm_calls <= 3
        assert result.stats.llm_calls == 2

    # --- no_match_reason and candidate_count ---

    def test_layer2_no_match_reason_is_weak_relevance(self) -> None:
        """Layer 2 rejection sets no_match_reason='weak_relevance'."""
        weak_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=5.0)]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=weak_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("house deeds in Spain")
        assert result.no_match_reason == "weak_relevance"

    def test_layer2_candidate_count_is_distinct_document_count(self) -> None:
        """Layer 2 rejection sets candidate_count to the number of distinct retrieved documents."""
        # Two chunks from two different documents.
        weak_hits = [
            make_chunk_hit(chunk_id=1, document_id=1, score=5.0),
            make_chunk_hit(chunk_id=2, document_id=2, score=5.0),
        ]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=weak_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("house deeds in Spain")
        assert result.candidate_count == 2

    def test_layer2_candidate_count_deduplicates_same_document(self) -> None:
        """Two chunks from the same document count as one candidate."""
        weak_hits = [
            make_chunk_hit(chunk_id=1, document_id=1, score=5.0),
            make_chunk_hit(chunk_id=2, document_id=1, score=5.0),
        ]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=weak_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("house deeds in Spain")
        assert result.candidate_count == 1

    def test_answered_result_leaves_no_match_reason_none(self) -> None:
        """An answered result must leave no_match_reason as None."""
        strong_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=0.1)]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=strong_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("when does my boiler warranty expire?")
        assert result.no_match_reason is None

    def test_answered_result_leaves_candidate_count_none(self) -> None:
        """An answered result must leave candidate_count as None."""
        strong_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=0.1)]
        llm_client = _answered_llm()
        core = _core(
            llm_client,
            _store_reader_with_hits(vector_hits=strong_hits, keyword_hits=[]),
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.answer("when does my boiler warranty expire?")
        assert result.candidate_count is None

    # --- retrieve() does NOT apply Layer 2 ---

    def test_retrieve_does_not_apply_layer2(self) -> None:
        """retrieve() is advisory — weak retrieval signal does not short-circuit it."""
        # score=5.0 → similarity≈0.167, well below the 0.5 threshold.
        weak_hits = [make_chunk_hit(chunk_id=1, document_id=1, score=5.0)]
        llm_client = _answered_llm()
        store_reader = _store_reader_with_hits(vector_hits=weak_hits, keyword_hits=[])
        core = _core(
            llm_client,
            store_reader,
            SEARCH_GATE_RELEVANCE=True,
            SEARCH_RELEVANCE_MIN_SIMILARITY=self._MIN_SIM,
        )
        result = core.retrieve("house deeds in Spain")
        # retrieve() must NOT return no_match due to the relevance signal.
        assert result.outcome_kind != "no_match"
        # retrieve() is plan-free pure RAG — it makes NO chat LLM call.
        assert llm_client.planner_calls == 0
