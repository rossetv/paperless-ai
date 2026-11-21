"""End-to-end tests: index from a mock Paperless, then search the same store.

Each document is embedded onto its own orthogonal axis and the query onto the
target's axis, so vector search ranks the target first without real embeddings.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from indexer.reconciler import Reconciler
from search.core import SearchCore
from search.judge import RelevanceJudge
from search.planner import QueryPlanner
from search.retriever import Retriever
from search.synthesizer import Synthesizer
from store.reader import StoreReader
from store.writer import StoreWriter


_DIMENSIONS = 4

_AXIS_TARGET: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0)  # boiler warranty doc
_AXIS_OTHER: tuple[float, ...] = (0.0, 1.0, 0.0, 0.0)  # unrelated document
_AXIS_TO_DELETE: tuple[float, ...] = (0.0, 0.0, 1.0, 0.0)  # document to delete
# Orthogonal to every indexed document: similarity ≈ 0.5 to every chunk, below
# a 0.9 SEARCH_RELEVANCE_MIN_SIMILARITY floor.
_AXIS_OFFTOPIC: tuple[float, ...] = (0.0, 0.0, 0.0, 1.0)


class _ScriptedLLMClient:
    """Routes ``_create_completion`` calls by system prompt to scripted responses."""

    def __init__(
        self,
        planner_response: str,
        synthesiser_responses: list[str],
    ) -> None:
        self._planner_response = planner_response
        self._synthesiser_responses = synthesiser_responses
        self.planner_calls = 0
        self.synthesiser_calls = 0

    def route(self, *, model: str, messages: list[dict[str, str]], **_: Any) -> Any:
        """Stand-in for ``OpenAIChatMixin._create_completion``."""
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "search-query planning engine" in system:
            self.planner_calls += 1
            return _completion(self._planner_response)
        self.synthesiser_calls += 1
        index = min(self.synthesiser_calls - 1, len(self._synthesiser_responses) - 1)
        return _completion(self._synthesiser_responses[index])


def _completion(content: str) -> Any:
    """Wrap a raw content string in an OpenAI-shaped completion object."""
    choice = MagicMock()
    choice.message.content = content
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _planner_json(semantic_queries: list[str]) -> str:
    """Return a well-formed planner JSON response string (multi-spec shape)."""
    return json.dumps(
        {
            "specs": [
                {
                    "mode": "semantic",
                    "semantic": q,
                    "keywords": [],
                    "filter_guess": {
                        "correspondent": None,
                        "document_type": None,
                        "tags": [],
                        "date_from": None,
                        "date_to": None,
                    },
                    "rationale": "test spec",
                }
                for q in semantic_queries
            ],
            "clarify": None,
        }
    )


def _answered_json(answer: str, citations: list[int]) -> str:
    """Return a well-formed Answered synthesiser response string."""
    return json.dumps({"outcome": "answered", "answer": answer, "citations": citations})


def _clarify_json(reason: str) -> str:
    """Return a well-formed planner clarify response string (Layer 1)."""
    return json.dumps({"clarify": {"reason": reason}})


def _make_settings(tmp_path: Any) -> MagicMock:
    """Return a settings mock satisfying both the reconciler and the search core."""
    # A MagicMock turns unset attributes into truthy mocks, which silently break
    # comparisons, slices and flags, so every field the pipeline reads is pinned.
    settings = MagicMock()
    settings.INDEX_DB_PATH = str(tmp_path / "index.db")
    settings.EMBEDDING_MODEL = "text-embedding-3-small"
    settings.EMBEDDING_DIMENSIONS = _DIMENSIONS
    settings.DOCUMENT_WORKERS = 2
    settings.CHUNK_SIZE = 2000
    settings.CHUNK_OVERLAP = 256
    settings.ERROR_TAG_ID = 552
    settings.SEARCH_TOP_K = 10
    settings.SEARCH_MAX_REFINEMENTS = 1
    settings.SEARCH_PLANNER_MODEL = "gpt-5.4-mini"
    settings.SEARCH_ANSWER_MODEL = "gpt-5.4"
    settings.CLASSIFY_MODELS = ["gpt-5.4-mini", "gpt-5.4"]
    settings.PAPERLESS_URL = "http://paperless.example:8000"
    settings.MAX_RETRIES = 3
    settings.MAX_RETRY_BACKOFF_SECONDS = 30
    settings.SEARCH_CACHE_TTL_SECONDS = 0
    settings.SEARCH_SKIP_PLANNER_FOR_TRIVIAL = False
    settings.SEARCH_PLANNER_REASONING_EFFORT = "medium"
    settings.SEARCH_ANSWER_REASONING_EFFORT = "medium"
    settings.LLM_PROVIDER = "openai"
    settings.SEARCH_GATE_ADEQUACY = True
    settings.SEARCH_GATE_RELEVANCE = True
    settings.SEARCH_RELEVANCE_MIN_SIMILARITY = 0.0  # inert; offtopic test sets 0.9
    settings.SEARCH_RELEVANCE_TIER_STRONG = 0.70
    settings.SEARCH_RELEVANCE_TIER_GOOD = 0.66
    settings.SEARCH_RELEVANCE_TIER_PARTIAL = 0.60
    settings.SEARCH_MIN_QUERY_CHARS = 2
    # The judge is an extra LLM call; off unless a test opts in.
    settings.SEARCH_GATE_JUDGE = False
    settings.SEARCH_JUDGE_MODEL = "gpt-5.4-mini"
    settings.SEARCH_JUDGE_REASONING_EFFORT = "low"
    settings.SEARCH_JUDGE_RATIONALES = True
    settings.SEARCH_IDENTITY_AWARE = True
    settings.SEARCH_PER_SPEC_K = 10
    settings.SEARCH_MAX_CHUNKS_PER_DOC = 3
    settings.SEARCH_PLANNER_MAX_SPECS = 8
    settings.SEARCH_PLANNER_TAXONOMY_LIMIT = 100
    return settings


def _make_doc(
    *,
    doc_id: int,
    content: str,
    title: str,
    modified: str = "2024-06-01T12:00:00+00:00",
) -> dict:
    """Build a minimal Paperless document dict accepted by the reconciler."""
    return {
        "id": doc_id,
        "title": title,
        "content": content,
        "tags": [],
        "correspondent": None,
        "document_type": None,
        "created": "2024-01-15",
        "modified": modified,
    }


def _make_indexer_embedding_client(
    doc_to_axis: dict[int, tuple[float, ...]],
) -> MagicMock:
    """An embedding client that gives the *n*-th ``embed`` call the *n*-th axis.

    The reconciler embeds one document per call, so with DOCUMENT_WORKERS=1 the
    axes follow the order of *doc_to_axis*. A parallel pool would scramble it.
    """
    axes = list(doc_to_axis.values())
    call_counter = [0]

    client = MagicMock()

    def embed(texts: list[str]) -> list[list[float]]:
        idx = call_counter[0] % len(axes)
        call_counter[0] += 1
        return [list(axes[idx]) for _ in texts]

    client.embed.side_effect = embed
    return client


def _make_query_embedding_client(query_axis: tuple[float, ...]) -> MagicMock:
    """An embedding client that maps every query string onto *query_axis*."""
    client = MagicMock()
    client.embed.side_effect = lambda texts: [list(query_axis) for _ in texts]
    return client


def _make_paperless(
    *,
    documents: list[dict] | None = None,
    all_ids: list[int] | None = None,
) -> MagicMock:
    """A mock PaperlessClient for both the incremental sync and the deletion sweep.

    ``iter_all_documents`` returns *documents* when ``modified_after`` is passed
    (incremental sync) and bare-id dicts from *all_ids* when it is not (sweep).
    ``document_exists`` is False for every id.
    """
    paperless = MagicMock()
    docs = documents if documents is not None else []
    ids = all_ids if all_ids is not None else []

    def _iter_all_documents(**kwargs: object) -> list[dict]:
        if "modified_after" in kwargs:
            return docs
        return [{"id": doc_id} for doc_id in ids]

    paperless.iter_all_documents.side_effect = _iter_all_documents
    paperless.list_correspondents.return_value = []
    paperless.list_document_types.return_value = []
    paperless.list_tags.return_value = []
    paperless.document_exists.return_value = False
    return paperless


def _build_search_core(
    settings: MagicMock,
    store_reader: StoreReader,
    llm_client: _ScriptedLLMClient,
    query_embedding_client: MagicMock,
) -> SearchCore:
    """Wire a SearchCore over the real pipeline stages with a scripted LLM."""
    planner = QueryPlanner(settings)
    planner._create_completion = llm_client.route  # type: ignore[method-assign]
    retriever = Retriever(settings, store_reader, query_embedding_client)
    synthesizer = Synthesizer(settings)
    synthesizer._create_completion = llm_client.route  # type: ignore[method-assign]
    judge = RelevanceJudge(settings)
    judge._create_completion = llm_client.route  # type: ignore[method-assign]
    return SearchCore(
        settings=settings,
        store_reader=store_reader,
        planner=planner,
        retriever=retriever,
        synthesizer=synthesizer,
        judge=judge,
    )


class TestIndexThenSearch:
    """Full index → search flow against mocks, no live services."""

    def test_index_then_search_produces_a_non_empty_cited_answer(
        self, tmp_path: Any
    ) -> None:
        """Indexing mock documents then querying yields a cited, non-empty answer."""
        settings = _make_settings(tmp_path)
        # Sequential indexing keeps the embed call order equal to document order.
        settings.DOCUMENT_WORKERS = 1

        # ---- index phase ----
        documents = [
            _make_doc(
                doc_id=1,
                content="The boiler warranty certificate is valid until March 2028.",
                title="Worcester Bosch Boiler Warranty",
            ),
            _make_doc(
                doc_id=2,
                content="Your council tax band is D for the 2024 financial year.",
                title="Council Tax Letter",
            ),
        ]
        doc_to_axis = {1: _AXIS_TARGET, 2: _AXIS_OTHER}
        indexer_embedding_client = _make_indexer_embedding_client(doc_to_axis)

        store_writer = StoreWriter(settings)
        try:
            paperless_index = _make_paperless(documents=documents)
            report = Reconciler(
                settings, paperless_index, store_writer, indexer_embedding_client
            ).incremental_sync()

            # Both documents must land in the store.
            assert report.indexed == 2
            assert store_writer.get_all_document_ids() == {1, 2}
        finally:
            store_writer.close()

        # ---- search phase ----
        store_reader = StoreReader(settings)
        try:
            llm_client = _ScriptedLLMClient(
                planner_response=_planner_json(["boiler warranty expiry"]),
                synthesiser_responses=[
                    _answered_json(
                        "Your boiler warranty is valid until March 2028 [1].",
                        citations=[1],
                    )
                ],
            )
            # Query embedded onto AXIS_TARGET → nearest to document 1.
            core = _build_search_core(
                settings,
                store_reader,
                llm_client,
                _make_query_embedding_client(_AXIS_TARGET),
            )
            result = core.answer("when does my boiler warranty expire?")
        finally:
            store_reader.close()

        assert result.answer != ""
        assert len(result.answer) > 0
        source_ids = {source.document_id for source in result.sources}
        assert 1 in source_ids, f"expected document 1 in sources; got {source_ids}"
        assert any(source.document_id == 1 for source in result.sources)

    def test_a_deleted_document_is_pruned_and_no_longer_appears_in_results(
        self, tmp_path: Any
    ) -> None:
        """A document removed from Paperless is swept from the store and search.

        The query is embedded onto the deleted document's own axis, so it would
        be the nearest hit if any of its chunks survived.
        """
        settings = _make_settings(tmp_path)
        settings.DOCUMENT_WORKERS = 1

        documents = [
            _make_doc(
                doc_id=1,
                content="The boiler warranty certificate is valid until March 2028.",
                title="Worcester Bosch Boiler Warranty",
            ),
            _make_doc(
                doc_id=2,
                content="Your council tax band is D for the 2024 financial year.",
                title="Council Tax Letter",
            ),
            _make_doc(
                doc_id=3,
                content="The gas meter reading for March is 14523 cubic metres.",
                title="Gas Meter Reading",
                modified="2024-06-02T12:00:00+00:00",
            ),
        ]
        # Sequential assignment: call 0 → doc 1, call 1 → doc 2, call 2 → doc 3.
        doc_to_axis = {
            1: _AXIS_TARGET,
            2: _AXIS_OTHER,
            3: _AXIS_TO_DELETE,
        }
        indexer_embedding_client = _make_indexer_embedding_client(doc_to_axis)

        store_writer = StoreWriter(settings)
        try:
            paperless_index = _make_paperless(documents=documents)
            report = Reconciler(
                settings, paperless_index, store_writer, indexer_embedding_client
            ).incremental_sync()

            assert report.indexed == 3
            assert store_writer.get_all_document_ids() == {1, 2, 3}

            # ---- sanity: document 3 is in the index before deletion ----
            assert 3 in store_writer.get_all_document_ids()

            # ---- deletion sweep: Paperless now only has docs 1 and 2 ----
            paperless_sweep = _make_paperless(all_ids=[1, 2])
            sweep_report = Reconciler(
                settings,
                paperless_sweep,
                store_writer,
                _make_indexer_embedding_client({}),
            ).deletion_sweep()

            assert sweep_report.aborted is False
            assert sweep_report.pruned == 1
            assert store_writer.get_all_document_ids() == {1, 2}
        finally:
            store_writer.close()

        # ---- search after deletion: doc 3 must not appear ----
        store_reader = StoreReader(settings)
        try:
            llm_client = _ScriptedLLMClient(
                planner_response=_planner_json(["gas meter reading"]),
                synthesiser_responses=[
                    _answered_json(
                        "No relevant gas meter information was found [1].",
                        citations=[1],
                    )
                ],
            )
            core = _build_search_core(
                settings,
                store_reader,
                llm_client,
                _make_query_embedding_client(_AXIS_TO_DELETE),
            )
            result = core.answer("what is the gas meter reading?")
        finally:
            store_reader.close()

        # Document 3 must not be in the sources regardless of what was returned.
        source_ids = {source.document_id for source in result.sources}
        assert 3 not in source_ids, (
            f"deleted document 3 appeared in results: {source_ids}"
        )


class TestFailFastGates:
    """End-to-end coverage of the planner (Layer 1) and relevance (Layer 2) gates.

    The store and retriever are real, so the relevance signals are genuine.
    Layer 0 (degenerate input) is covered by unit tests.
    """

    def _seed_store(self, settings: MagicMock) -> None:
        """Index doc 1 (boiler) on ``_AXIS_TARGET`` and doc 2 on ``_AXIS_OTHER``."""
        settings.DOCUMENT_WORKERS = 1
        documents = [
            _make_doc(
                doc_id=1,
                content="The boiler warranty certificate is valid until March 2028.",
                title="Worcester Bosch Boiler Warranty",
            ),
            _make_doc(
                doc_id=2,
                content="Your council tax band is D for the 2024 financial year.",
                title="Council Tax Letter",
            ),
        ]
        doc_to_axis = {1: _AXIS_TARGET, 2: _AXIS_OTHER}
        indexer_embedding_client = _make_indexer_embedding_client(doc_to_axis)
        store_writer = StoreWriter(settings)
        try:
            paperless = _make_paperless(documents=documents)
            report = Reconciler(
                settings, paperless, store_writer, indexer_embedding_client
            ).incremental_sync()
            assert report.indexed == 2
        finally:
            store_writer.close()

    def test_vague_query_returns_clarify_outcome(self, tmp_path: Any) -> None:
        """A query the planner judges too vague returns 'clarify' with no synthesis.

        The store is seeded, so an empty result proves the gate fired first.
        """
        settings = _make_settings(tmp_path)
        self._seed_store(settings)

        store_reader = StoreReader(settings)
        try:
            llm_client = _ScriptedLLMClient(
                planner_response=_clarify_json(
                    "Query is too vague — add a document type or correspondent."
                ),
                # Synthesiser responses should never be reached for a clarify result.
                synthesiser_responses=["SHOULD NOT BE CALLED"],
            )
            core = _build_search_core(
                settings,
                store_reader,
                llm_client,
                _make_query_embedding_client(_AXIS_TARGET),
            )
            result = core.answer("life")
        finally:
            store_reader.close()

        assert result.outcome_kind == "clarify", (
            f"expected clarify, got {result.outcome_kind!r}"
        )
        assert len(result.sources) == 0, (
            f"clarify result must have no sources; got {result.sources}"
        )
        # The synthesiser must never have been called.
        assert llm_client.synthesiser_calls == 0, (
            f"synthesiser was called {llm_client.synthesiser_calls} time(s); "
            "expected 0 for a clarify short-circuit"
        )

    def test_offtopic_query_returns_no_match_outcome(self, tmp_path: Any) -> None:
        """An off-topic query whose retrieval signal is too weak returns 'no_match'.

        The planner returns a normal plan, so only Layer 2 can produce no_match.
        """
        settings = _make_settings(tmp_path)
        # Raise the relevance floor so the ≈0.5 off-topic signal falls below it.
        settings.SEARCH_RELEVANCE_MIN_SIMILARITY = 0.9
        self._seed_store(settings)

        store_reader = StoreReader(settings)
        try:
            llm_client = _ScriptedLLMClient(
                planner_response=_planner_json(["house deeds Spain"]),
                # Synthesiser must not be reached when Layer 2 fires.
                synthesiser_responses=["SHOULD NOT BE CALLED"],
            )
            core = _build_search_core(
                settings,
                store_reader,
                llm_client,
                # Off-topic axis: distance ≈ 1.0 to all stored chunks →
                # similarity ≈ 0.5, below the 0.9 floor.
                _make_query_embedding_client(_AXIS_OFFTOPIC),
            )
            result = core.answer("house deeds in Spain")
        finally:
            store_reader.close()

        assert result.outcome_kind == "no_match", (
            f"expected no_match, got {result.outcome_kind!r}"
        )
        assert len(result.sources) == 0, (
            f"no_match result must have no sources; got {result.sources}"
        )
        # The synthesiser must not have been called — Layer 2 short-circuits
        # before synthesis.
        assert llm_client.synthesiser_calls == 0, (
            f"synthesiser was called {llm_client.synthesiser_calls} time(s); "
            "expected 0 for a Layer-2 no_match short-circuit"
        )

    def test_ontopic_query_returns_answered_outcome_with_sources(
        self, tmp_path: Any
    ) -> None:
        """An on-topic query produces outcome_kind='answered' with sources."""
        settings = _make_settings(tmp_path)
        self._seed_store(settings)

        store_reader = StoreReader(settings)
        try:
            llm_client = _ScriptedLLMClient(
                planner_response=_planner_json(["boiler warranty expiry"]),
                synthesiser_responses=[
                    _answered_json(
                        "Your boiler warranty is valid until March 2028 [1].",
                        citations=[1],
                    )
                ],
            )
            core = _build_search_core(
                settings,
                store_reader,
                llm_client,
                _make_query_embedding_client(_AXIS_TARGET),
            )
            result = core.answer("when does my boiler warranty expire?")
        finally:
            store_reader.close()

        assert result.outcome_kind == "answered", (
            f"expected answered, got {result.outcome_kind!r}"
        )
        assert len(result.sources) > 0, "answered result must have at least one source"
        source_ids = {source.document_id for source in result.sources}
        assert 1 in source_ids, f"expected document 1 in sources; got {source_ids}"
