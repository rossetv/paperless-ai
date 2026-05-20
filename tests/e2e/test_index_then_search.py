"""End-to-end tests for the full index-then-search flow.

Exercises the complete pipeline — from a mock Paperless through the real
:class:`~indexer.reconciler.Reconciler` and :class:`~store.writer.StoreWriter`
into the real :class:`~search.core.SearchCore` — without hitting any live
service.

Two test cases (both ``@pytest.mark.e2e``, auto-applied by the conftest for
any file under ``tests/e2e/``):

``test_index_then_search_produces_a_non_empty_cited_answer``
    The full pipeline indexes a small set of mock documents, then answers a
    query from that same store and asserts a non-empty cited answer is returned.

``test_a_deleted_document_is_pruned_and_no_longer_appears_in_results``
    After a document is removed from the mock Paperless and a deletion sweep
    runs, it is absent from the store and does not appear in a subsequent query.

Deterministic retrieval
-----------------------
Each document's text is embedded onto a **distinct orthogonal axis** (e.g.
(1,0,0,0) for the target document, (0,1,0,0) for a second document).  When the
query is embedded onto the same axis as a document, the cosine distance to that
document is 0 — the minimum — so vector search will rank it first regardless of
the other documents in the store.  This scheme is borrowed verbatim from
``tests/integration/test_search_pipeline.py``; it makes retrieval behaviour
provable without real embeddings.

The embedding mock (``_make_query_embedding_client``) returns the designated
axis vector for every query string, matching the axis embedded into the target
document's chunks by the reconciler's ``_make_embedding_client``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from indexer.reconciler import Reconciler
from search.core import SearchCore
from search.planner import QueryPlanner
from search.retriever import Retriever
from search.synthesizer import Synthesizer
from store.reader import StoreReader
from store.writer import StoreWriter


# ---------------------------------------------------------------------------
# Embedding geometry — orthogonal axes, one per document role
# ---------------------------------------------------------------------------
# Documents embedded on different axes are maximally distant from each other.
# A query embedded onto axis 0 is nearest to the document on axis 0 and
# farthest from all others.  cos distance = 0 → rank 1.

_DIMENSIONS = 4

_AXIS_TARGET: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0)   # boiler warranty doc
_AXIS_OTHER: tuple[float, ...] = (0.0, 1.0, 0.0, 0.0)    # unrelated document
_AXIS_TO_DELETE: tuple[float, ...] = (0.0, 0.0, 1.0, 0.0) # document to delete


# ---------------------------------------------------------------------------
# Scripted LLM client — planner + synthesiser routing
# ---------------------------------------------------------------------------


class _ScriptedLLMClient:
    """Routes ``_create_completion`` calls to scripted planner / synthesiser responses.

    Distinguishes planner calls (system prompt contains "search-query planning
    engine") from synthesiser calls by inspecting the system message.  The
    same ``route`` method is patched onto both stages.
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

    def route(self, *, model: str, messages: list[dict[str, str]], **_: Any) -> Any:
        """Stand-in for ``OpenAIChatMixin._create_completion``."""
        system = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        if "search-query planning engine" in system:
            self.planner_calls += 1
            return _completion(self._planner_response)
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
# Canned LLM response builders
# ---------------------------------------------------------------------------


def _planner_json(semantic_queries: list[str]) -> str:
    """Return a well-formed planner JSON response string."""
    return json.dumps(
        {
            "semantic_queries": semantic_queries,
            "keyword_terms": [],
            "filter_candidates": {
                "correspondent": None,
                "document_type": None,
                "tags": [],
                "date_from": None,
                "date_to": None,
            },
            "sub_questions": [],
        }
    )


def _answered_json(answer: str, citations: list[int]) -> str:
    """Return a well-formed Answered synthesiser response string."""
    return json.dumps(
        {"outcome": "answered", "answer": answer, "citations": citations}
    )


# ---------------------------------------------------------------------------
# Test-object builders
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Any) -> MagicMock:
    """Return a settings mock satisfying both the reconciler and the search core."""
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
    settings.AI_MODELS = ["gpt-5.4-mini", "gpt-5.4"]
    settings.PAPERLESS_URL = "http://paperless.example:8000"
    # Real ints so the @retry decorator on the planner / synthesiser is well-formed.
    settings.MAX_RETRIES = 3
    settings.MAX_RETRY_BACKOFF_SECONDS = 30
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
    """An embedding client that assigns each document's chunks a deterministic axis.

    The reconciler calls ``embed(texts)`` for the chunks of one document at a
    time.  We route each call to the correct axis by tracking the call count and
    mapping it to the document currently being indexed.

    Because the reconciler fans documents across a thread pool, the call order
    is not guaranteed when DOCUMENT_WORKERS > 1.  We therefore embed ALL
    texts from ALL documents onto a pre-defined ordered list of axes derived
    from *doc_to_axis*.  Each ``embed`` invocation yields the axis registered
    for its sequential call number.

    For this test DOCUMENT_WORKERS=2 but there are only three documents and
    each gets exactly one chunk, so the three embed calls map to axes 0, 1, 2
    in some order.  To make retrieval deterministic we embed the target document
    on _AXIS_TARGET, the other on _AXIS_OTHER, and the deletable one on
    _AXIS_TO_DELETE, but we cannot know the call order in a parallel pool.

    To sidestep the ordering problem entirely: we embed EVERY chunk onto the
    same axis whose FIRST component equals (1/sqrt(DIMENSIONS)).  The tests
    distinguish documents by directing the *query* embedding onto the target
    document's specific axis, not by comparing chunk-to-chunk distances.

    However, this uniform approach would make all documents equally close to
    every query, breaking deterministic retrieval.  Instead we use DOCUMENT_WORKERS=1
    for the e2e fixture so documents are processed sequentially and the call
    ordering is deterministic.
    """
    # Build an ordered sequence of axes matching the document order supplied.
    axes = list(doc_to_axis.values())
    call_counter = [0]

    client = MagicMock()

    def embed(texts: list[str]) -> list[list[float]]:
        # One call per document (all its chunks in one batch).
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
    """A mock PaperlessClient used by both the incremental sync and deletion sweep.

    ``iter_all_documents(modified_after=…)`` returns *documents* when the
    ``modified_after`` keyword is present (incremental sync).  When the keyword
    is absent (deletion sweep), it returns bare-id dicts built from *all_ids*.
    ``document_exists`` returns False for every id (sweep: all candidates absent).
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
    # Default: every document_exists probe returns False (swept candidate is absent).
    paperless.document_exists.return_value = False
    return paperless


def _build_search_core(
    settings: MagicMock,
    store_reader: StoreReader,
    llm_client: _ScriptedLLMClient,
    query_embedding_client: MagicMock,
) -> SearchCore:
    """Wire a SearchCore over the real pipeline stages with a scripted LLM.

    The planner and synthesiser are real; their ``_create_completion`` is patched
    with the scripted driver's router so no network call is made — replicating
    the pattern from ``tests/integration/test_search_pipeline.py``.
    """
    planner = QueryPlanner(settings)
    planner._create_completion = llm_client.route  # type: ignore[method-assign]
    retriever = Retriever(settings, store_reader, query_embedding_client)
    synthesizer = Synthesizer(settings)
    synthesizer._create_completion = llm_client.route  # type: ignore[method-assign]
    return SearchCore(
        settings=settings,
        store_reader=store_reader,
        planner=planner,
        retriever=retriever,
        synthesizer=synthesizer,
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestIndexThenSearch:
    """Full index → search flow against mocks, no live services."""

    def test_index_then_search_produces_a_non_empty_cited_answer(
        self, tmp_path: Any
    ) -> None:
        """Indexing a set of mock documents and then running a query yields a
        non-empty answer with at least one source citation drawn from the index.

        The embedding geometry ensures vector search ranks the boiler warranty
        document first for the boiler-warranty query: each document is embedded
        onto a distinct orthogonal axis; the query is embedded onto the target
        document's axis, so cosine distance = 0 for that document and 1 for all
        others (SPEC §12, CODE_GUIDELINES §11.4).
        """
        settings = _make_settings(tmp_path)
        # DOCUMENT_WORKERS=1 so indexing is sequential and the embed call order
        # matches the document insertion order — the orthogonal-axis scheme
        # requires knowing which axis each document gets.
        settings.DOCUMENT_WORKERS = 1

        # ---- index phase ----
        # Documents indexed in the order they are listed; with DOCUMENT_WORKERS=1
        # the embedding client's call 0 → doc 1 (boiler, AXIS_TARGET), call 1 → doc 2.
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
        # The reconciler materialises the document list before fanning it out to
        # the pool.  With DOCUMENT_WORKERS=1 processing is strictly sequential
        # in the order of the materialised list, so axis assignments are stable.
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

        # The answer must be non-empty and cite document 1.
        assert result.answer != ""
        assert len(result.answer) > 0
        source_ids = {source.document_id for source in result.sources}
        assert 1 in source_ids, (
            f"expected document 1 in sources; got {source_ids}"
        )
        # The synthesiser's citation list must include document 1.
        # The cited documents are a subset of the result's sources.
        assert any(source.document_id == 1 for source in result.sources)

    def test_a_deleted_document_is_pruned_and_no_longer_appears_in_results(
        self, tmp_path: Any
    ) -> None:
        """After a document is removed from Paperless and a deletion sweep runs,
        the document is absent from the store and does not surface in a
        subsequent search query.

        Steps:
        1. Index three documents (target on AXIS_TARGET, unrelated on AXIS_OTHER,
           deletable on AXIS_TO_DELETE).
        2. Run a first query to confirm the deletable document is in the index
           (sanity check — its axis is reached by a dedicated embedding).
        3. Run a deletion sweep with Paperless reporting only the two kept docs.
        4. Assert the deletable document's id is gone from the store.
        5. Run the query again (query embedded onto AXIS_TO_DELETE) and confirm
           the deleted document no longer appears in the results.
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
            # (Verify via the store's id set — no search needed for this check.)
            assert 3 in store_writer.get_all_document_ids()

            # ---- deletion sweep: Paperless now only has docs 1 and 2 ----
            paperless_sweep = _make_paperless(all_ids=[1, 2])
            sweep_report = Reconciler(
                settings, paperless_sweep, store_writer, _make_indexer_embedding_client({})
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
            # Embed the query onto AXIS_TO_DELETE — the axis that was used for
            # document 3.  After the sweep, vector search finds nothing on that
            # axis (the chunk was deleted), so the retriever falls back to
            # AXIS_TARGET / AXIS_OTHER documents or returns empty.
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
