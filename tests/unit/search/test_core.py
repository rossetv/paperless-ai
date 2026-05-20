"""Tests for search.core — the bounded agentic pipeline orchestration.

Verifies the SearchCore contract (spec §6.3, §6.4):
- A normal query makes exactly plan + one synthesise = 2 LLM calls.
- A query whose exploratory synthesis returns NeedsMore triggers one
  refinement → exactly 3 LLM calls, and SearchStats.refined is True.
- The LLM call count NEVER exceeds 3 under any path — the worst case is
  tested with the refinement budget deliberately raised.
- Empty retrieval (even after broaden_plan) returns a "no matches"
  SearchResult with NO synthesis call — only the planner ran.
- retrieve() makes only the planner call and performs no synthesis.
- SourceDocuments carry resolved correspondent/type names and a correct
  paperless_url.

The mock LLM client distinguishes a planner call from a synthesiser call by
inspecting the system prompt (the planner prompt and the synthesiser prompt
have distinct, stable opening sentences).  This lets one mock client serve
the whole pipeline while the test asserts exactly how many calls of each
kind were made.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from search.core import SearchCore
from search.models import SearchResult, SourceDocument
from search.planner import QueryPlanner
from search.retriever import Retriever
from search.synthesizer import Synthesizer
from store.models import ChunkHit, FacetSet, IndexedDocument
from store.reader import SearchFilters


# ---------------------------------------------------------------------------
# A scripted LLM client that classifies each call as planner or synthesiser
# ---------------------------------------------------------------------------


class _ScriptedLLMClient:
    """A fake OpenAI-compatible client driving both pipeline LLM stages.

    The planner and synthesiser issue ``chat.completions.create`` calls with
    distinct system prompts.  This client inspects the system message to route
    each call to the planner response or the next synthesiser response, and
    records every call so the test can assert the exact LLM-call count.

    Args:
        planner_response: Raw JSON string the planner call returns.
        synthesiser_responses: Ordered raw JSON strings; the *n*-th synthesiser
            call returns the *n*-th entry.  If exhausted, the last entry is
            reused (so an over-eager loop is still observable, not crashed).
    """

    def __init__(
        self,
        planner_response: str,
        synthesiser_responses: list[str],
    ) -> None:
        self._planner_response = planner_response
        self._synthesiser_responses = synthesiser_responses
        self.planner_calls = 0
        self.synthesiser_calls = 0
        self.chat = MagicMock()
        self.chat.completions.create.side_effect = self._create

    @property
    def total_calls(self) -> int:
        """Total LLM chat calls made — planner plus synthesiser."""
        return self.planner_calls + self.synthesiser_calls

    def _create(self, *, model: str, messages: list[dict[str, str]]) -> Any:
        system = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        if "search-query planning engine" in system:
            self.planner_calls += 1
            return _completion(self._planner_response)

        # Anything else is a synthesiser call.
        self.synthesiser_calls += 1
        index = min(
            self.synthesiser_calls - 1, len(self._synthesiser_responses) - 1
        )
        return _completion(self._synthesiser_responses[index])


def _completion(content: str) -> Any:
    """Wrap a raw content string in an OpenAI-shaped completion object."""
    choice = MagicMock()
    choice.message.content = content
    completion = MagicMock()
    completion.choices = [choice]
    return completion


# ---------------------------------------------------------------------------
# Canned LLM payloads
# ---------------------------------------------------------------------------


def _planner_json(
    semantic_queries: list[str] | None = None,
    keyword_terms: list[str] | None = None,
    correspondent: str | None = None,
    document_type: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """A well-formed planner JSON response."""
    return json.dumps(
        {
            "semantic_queries": semantic_queries or ["boiler warranty"],
            "keyword_terms": keyword_terms or [],
            "filter_candidates": {
                "correspondent": correspondent,
                "document_type": document_type,
                "tags": tags or [],
                "date_from": None,
                "date_to": None,
            },
            "sub_questions": [],
        }
    )


def _answered_json(answer: str, citations: list[int]) -> str:
    """A well-formed Answered synthesiser response."""
    return json.dumps(
        {"outcome": "answered", "answer": answer, "citations": citations}
    )


def _needs_more_json(adjustment: str) -> str:
    """A well-formed NeedsMore synthesiser response."""
    return json.dumps({"outcome": "needs_more", "adjustment": adjustment})


# ---------------------------------------------------------------------------
# Settings / store / pipeline-stage builders
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    max_refinements: int = 1,
    top_k: int = 10,
    paperless_url: str = "http://paperless.example:8000",
) -> MagicMock:
    """Build a Settings-like mock with the fields the pipeline reads."""
    settings = MagicMock()
    settings.SEARCH_MAX_REFINEMENTS = max_refinements
    settings.SEARCH_TOP_K = top_k
    settings.PAPERLESS_URL = paperless_url
    settings.SEARCH_PLANNER_MODEL = "gpt-5.4-mini"
    settings.SEARCH_ANSWER_MODEL = "gpt-5.4"
    settings.AI_MODELS = ["gpt-5.4-mini", "gpt-5.4"]
    return settings


def _chunk_hit(
    chunk_id: int,
    document_id: int,
    text: str = "chunk text",
) -> ChunkHit:
    """Build a ChunkHit returned by a store search method."""
    return ChunkHit(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        page_hint=1,
        score=0.5,
    )


def _indexed_document(
    document_id: int,
    *,
    title: str | None = "A Document",
    correspondent: str | None = None,
    document_type: str | None = None,
    created: str | None = "2024-01-15T00:00:00+00:00",
) -> IndexedDocument:
    """Build an IndexedDocument returned by StoreReader.get_documents."""
    return IndexedDocument(
        id=document_id,
        title=title,
        correspondent=correspondent,
        document_type=document_type,
        tags=(),
        created=created,
    )


def _empty_facets() -> FacetSet:
    """A FacetSet with no taxonomy entries."""
    return FacetSet(
        correspondents=(),
        document_types=(),
        tags=(),
        earliest=None,
        latest=None,
    )


def _build_core(
    *,
    settings: MagicMock,
    llm_client: _ScriptedLLMClient,
    store_reader: MagicMock,
    embedding_client: MagicMock,
) -> SearchCore:
    """Assemble a SearchCore with real pipeline stages over the given mocks.

    The planner and synthesiser are real (driven by the scripted LLM client);
    the retriever is real (driven by the mock store and embedding client); only
    the store reader, embedding client, and LLM transport are mocks.
    """
    planner = QueryPlanner(settings, llm_client)
    retriever = Retriever(settings, store_reader, embedding_client)
    synthesizer = Synthesizer(settings, llm_client)
    return SearchCore(
        settings=settings,
        store_reader=store_reader,
        planner=planner,
        retriever=retriever,
        synthesizer=synthesizer,
    )


# ---------------------------------------------------------------------------
# Normal query — plan + one synthesise = exactly 2 LLM calls
# ---------------------------------------------------------------------------


class TestNormalQuery:
    """A query answerable on the first pass costs exactly 2 LLM calls."""

    def test_normal_query_makes_exactly_two_llm_calls(self) -> None:
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[
                _answered_json("The warranty expires in 2028 [1].", citations=[1])
            ],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=1)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(1)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1, 0.2, 0.3]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        core.answer("when does my boiler warranty expire?")

        assert llm_client.total_calls == 2
        assert llm_client.planner_calls == 1
        assert llm_client.synthesiser_calls == 1

    def test_normal_query_reports_two_llm_calls_in_stats(self) -> None:
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("Answer [1].", citations=[1])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=1)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(1)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("a normal query")

        assert result.stats.llm_calls == 2

    def test_normal_query_is_not_marked_refined(self) -> None:
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("Answer [1].", citations=[1])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=1)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(1)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("a normal query")

        assert result.stats.refined is False

    def test_normal_query_returns_search_result(self) -> None:
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[
                _answered_json("The answer is 42 [1].", citations=[1])
            ],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=1)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(1)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
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
        settings = _make_settings(max_refinements=1)
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[
                _needs_more_json("Look for the 2028 warranty certificate."),
                _answered_json("The warranty expires in 2028 [2].", citations=[2]),
            ],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        # Both retrieval rounds return chunks so the loop reaches synthesis.
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=2, document_id=2)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(2)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        core.answer("when does my boiler warranty expire?")

        assert llm_client.planner_calls == 1
        assert llm_client.synthesiser_calls == 2
        assert llm_client.total_calls == 3

    def test_refinement_sets_refined_flag_true(self) -> None:
        settings = _make_settings(max_refinements=1)
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[
                _needs_more_json("Broaden the date range."),
                _answered_json("Final answer [2].", citations=[2]),
            ],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=2, document_id=2)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(2)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("a query needing refinement")

        assert result.stats.refined is True
        assert result.stats.llm_calls == 3

    def test_refinement_returns_the_final_pass_answer(self) -> None:
        """The answer in the result is the final synthesise, not the exploratory."""
        settings = _make_settings(max_refinements=1)
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[
                _needs_more_json("Need the warranty certificate."),
                _answered_json("Resolved on the second pass [2].", citations=[2]),
            ],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=2, document_id=2)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(2)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("a query")

        assert result.answer == "Resolved on the second pass [2]."

    def test_zero_budget_does_not_refine(self) -> None:
        """With SEARCH_MAX_REFINEMENTS=0 a NeedsMore does NOT trigger a refine."""
        settings = _make_settings(max_refinements=0)
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[
                _needs_more_json("Would refine, but the budget is zero."),
            ],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=1)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(1)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("a query")

        # Only planner + the single exploratory synthesise.
        assert llm_client.total_calls == 2
        assert result.stats.refined is False


# ---------------------------------------------------------------------------
# Hard ceiling — the LLM call count NEVER exceeds 3 under any path
# ---------------------------------------------------------------------------


class TestHardCeiling:
    """No code path may make a 4th LLM call (spec §6.3 / CODE_GUIDELINES §14.3)."""

    def test_call_count_never_exceeds_three_with_inflated_budget(self) -> None:
        """Even with the budget raised absurdly high, the cap holds at 3.

        Every synthesiser response is NeedsMore, which would drive an unbounded
        refine loop if the ceiling were not enforced.  The pipeline must stop
        at 3 LLM calls regardless of the configured budget.
        """
        settings = _make_settings(max_refinements=99)
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            # Always NeedsMore — an unbounded loop without the hard cap.
            synthesiser_responses=[_needs_more_json("more, always more")],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=1)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(1)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("a query that always needs more")

        assert llm_client.total_calls <= 3
        assert result.stats.llm_calls <= 3

    def test_worst_case_makes_exactly_three_calls(self) -> None:
        """The worst case — plan, exploratory, one refine — is exactly 3."""
        settings = _make_settings(max_refinements=99)
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_needs_more_json("more")],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=1)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(1)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        core.answer("worst case query")

        assert llm_client.total_calls == 3

    def test_stats_llm_calls_matches_actual_calls_made(self) -> None:
        """SearchStats.llm_calls is the TRUE total, not a hardcoded constant."""
        settings = _make_settings(max_refinements=99)
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_needs_more_json("more")],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=1)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(1)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("a query")

        assert result.stats.llm_calls == llm_client.total_calls


# ---------------------------------------------------------------------------
# Empty retrieval — no-match short-circuit, no synthesis call
# ---------------------------------------------------------------------------


class TestEmptyRetrieval:
    """Empty retrieval (even after broaden_plan) costs only the planner call."""

    def test_empty_retrieval_makes_no_synthesis_call(self) -> None:
        """When retrieval is empty even after broadening, the synthesiser is
        never called — only the planner ran."""
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(correspondent="npower"),
            synthesiser_responses=[_answered_json("unreachable", citations=[])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        # Both the filtered retrieval and the broadened retrieval find nothing.
        store_reader.vector_search.return_value = []
        store_reader.keyword_search.return_value = []
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.0, 0.0]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        core.answer("a query matching nothing at all")

        assert llm_client.planner_calls == 1
        assert llm_client.synthesiser_calls == 0
        assert llm_client.total_calls == 1

    def test_empty_retrieval_reports_one_llm_call(self) -> None:
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("unreachable", citations=[])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = []
        store_reader.keyword_search.return_value = []
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.0]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("nothing matches")

        assert result.stats.llm_calls == 1

    def test_empty_retrieval_returns_no_sources(self) -> None:
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("unreachable", citations=[])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = []
        store_reader.keyword_search.return_value = []
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.0]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("nothing matches")

        assert result.sources == ()
        assert isinstance(result, SearchResult)

    def test_empty_retrieval_answer_states_no_matches(self) -> None:
        """The no-match SearchResult carries a non-empty 'no matching
        documents' answer for the UI to display."""
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("unreachable", citations=[])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = []
        store_reader.keyword_search.return_value = []
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.0]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("nothing matches")

        assert result.answer != ""

    def test_broaden_retry_runs_before_giving_up(self) -> None:
        """A filtered retrieval that finds nothing is retried broadened; if
        the broadened retrieval finds chunks, synthesis proceeds normally."""
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(correspondent="npower"),
            synthesiser_responses=[
                _answered_json("Found after broadening [1].", citations=[1])
            ],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        # First call (filtered) → nothing; second call (broadened) → a hit.
        store_reader.vector_search.side_effect = [
            [],
            [_chunk_hit(chunk_id=1, document_id=1)],
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(1)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("npower bill query")

        # planner + one synthesise — the broaden retry is not an LLM call.
        assert llm_client.total_calls == 2
        assert result.answer == "Found after broadening [1]."
        assert len(result.sources) == 1


# ---------------------------------------------------------------------------
# retrieve() — sources-only mode, only the planner call
# ---------------------------------------------------------------------------


class TestRetrieveOnly:
    """retrieve() plans and retrieves but never synthesises."""

    def test_retrieve_makes_only_the_planner_call(self) -> None:
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("must not happen", citations=[])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=1)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(1)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        core.retrieve("a sources-only query")

        assert llm_client.planner_calls == 1
        assert llm_client.synthesiser_calls == 0
        assert llm_client.total_calls == 1

    def test_retrieve_answer_field_is_empty(self) -> None:
        """retrieve() returns ranked sources but an empty answer string."""
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("nope", citations=[])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=1)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(1)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.retrieve("a sources-only query")

        assert result.answer == ""

    def test_retrieve_returns_ranked_sources(self) -> None:
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("nope", citations=[])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=7),
            _chunk_hit(chunk_id=2, document_id=8),
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [
            _indexed_document(7),
            _indexed_document(8),
        ]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.retrieve("a query")

        source_ids = {s.document_id for s in result.sources}
        assert source_ids == {7, 8}

    def test_retrieve_reports_one_llm_call_in_stats(self) -> None:
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("nope", citations=[])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=1)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(1)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.retrieve("a query")

        assert result.stats.llm_calls == 1
        assert result.stats.refined is False

    def test_retrieve_on_empty_returns_no_sources(self) -> None:
        """retrieve() with nothing found returns an empty sources tuple."""
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("nope", citations=[])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = []
        store_reader.keyword_search.return_value = []
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.0]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.retrieve("nothing matches")

        assert result.sources == ()
        assert result.stats.llm_calls == 1


# ---------------------------------------------------------------------------
# SourceDocument assembly — resolved names and a correct paperless_url
# ---------------------------------------------------------------------------


class TestSourceDocumentAssembly:
    """SourceDocuments carry resolved taxonomy names and a Paperless deep-link."""

    def test_source_carries_resolved_correspondent_and_type(self) -> None:
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("Answer [3].", citations=[3])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=3)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [
            _indexed_document(
                3,
                title="2024 Electricity Invoice",
                correspondent="npower",
                document_type="Invoice",
            )
        ]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("a query")

        source = result.sources[0]
        assert source.correspondent == "npower"
        assert source.document_type == "Invoice"
        assert source.title == "2024 Electricity Invoice"

    def test_source_paperless_url_joins_base_url_and_document_id(self) -> None:
        settings = _make_settings(paperless_url="http://paperless.example:8000")
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("Answer [42].", citations=[42])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=42)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(42)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("a query")

        source = result.sources[0]
        # The base URL and the document id both appear in the deep-link.
        assert source.paperless_url.startswith("http://paperless.example:8000")
        assert "42" in source.paperless_url

    def test_source_snippet_is_drawn_from_a_retrieved_chunk(self) -> None:
        """Each source carries a non-empty snippet for UI display."""
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("Answer [5].", citations=[5])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(
                chunk_id=1,
                document_id=5,
                text="The boiler warranty certificate is valid until 2028.",
            )
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(5)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("a query")

        source = result.sources[0]
        assert source.snippet != ""
        assert isinstance(source, SourceDocument)

    def test_source_with_no_taxonomy_has_none_names(self) -> None:
        """A document with no correspondent/type yields None on those fields."""
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(),
            synthesiser_responses=[_answered_json("Answer [9].", citations=[9])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=9)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [
            _indexed_document(9, correspondent=None, document_type=None)
        ]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        result = core.answer("a query")

        source = result.sources[0]
        assert source.correspondent is None
        assert source.document_type is None


# ---------------------------------------------------------------------------
# UI filters are threaded through to retrieval
# ---------------------------------------------------------------------------


class TestUiFilters:
    """ui_filters bypass free-text resolution and reach the retriever."""

    def test_ui_filters_are_passed_to_vector_search(self) -> None:
        settings = _make_settings()
        llm_client = _ScriptedLLMClient(
            planner_response=_planner_json(correspondent="npower"),
            synthesiser_responses=[_answered_json("Answer [1].", citations=[1])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = _empty_facets()
        store_reader.vector_search.return_value = [
            _chunk_hit(chunk_id=1, document_id=1)
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [_indexed_document(1)]
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.1]]

        ui_filters = SearchFilters(
            date_from=None,
            date_to=None,
            correspondent_id=55,
            document_type_id=None,
            tag_ids=(),
        )

        core = _build_core(
            settings=settings,
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        core.answer("a query", ui_filters=ui_filters)

        # The retriever forwards the resolved filters to vector_search; with
        # ui_filters set, resolution is bypassed and the UI filters are used.
        passed_filters = store_reader.vector_search.call_args[0][2]
        assert passed_filters is ui_filters
