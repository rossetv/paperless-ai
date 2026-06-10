"""Tests for the multi-spec Retriever.retrieve — per-spec search and cross-spec RRF.

Verifies the multi-spec overhaul of ``Retriever.retrieve``:
- Each spec runs its own store search with its own ``SearchFilters``; the
  recorded per-call filters prove the right spec drove each call.
- A document hit by two specs out-ranks one hit by a single spec (RRF reward).
- The output is capped at ``SEARCH_MAX_CHUNKS_PER_DOC`` chunks per document,
  keeping the highest-scoring chunks.
- The output spans at most ``SEARCH_TOP_K`` documents and is sorted by rrf_score.
- Empty specs / no hits yield ``([], RetrievalSignal(None, False))``.
- A keyword-only chunk has ``vector_similarity is None``; a vector-found chunk
  carries a float similarity.
"""

from __future__ import annotations

from store.models import ChunkHit
from search.models import RetrievalSignal, RetrievalSpec
from search.retriever import Retriever
from store.reader import SearchFilters
from tests.helpers.factories import make_chunk_hit, make_search_settings


class _FakeStoreReader:
    """A store reader that returns canned hits and records the filters per call.

    ``vector_results`` / ``keyword_results`` map the *semantic text* / the
    *keyword tuple* to the ChunkHit list that search should return, so a test
    scripts each spec's hits independently.  Every call appends a
    ``(kind, query, filters)`` triple to ``calls`` for assertion.
    """

    def __init__(
        self,
        *,
        vector_results: dict[str, list[ChunkHit]] | None = None,
        keyword_results: dict[tuple[str, ...], list[ChunkHit]] | None = None,
    ) -> None:
        self._vector_results = vector_results or {}
        self._keyword_results = keyword_results or {}
        self.calls: list[tuple[str, object, SearchFilters]] = []

    def vector_search(
        self, embedding: list[float], k: int, filters: SearchFilters
    ) -> list[ChunkHit]:
        # The fake embedding client returns one vector per text; the test maps a
        # text to its hits via the embedding's first element (see _FakeEmbedder).
        text = _TEXT_BY_VECTOR.get(tuple(embedding), "")
        self.calls.append(("vector", text, filters))
        return self._vector_results.get(text, [])

    def keyword_search(
        self, terms: list[str], k: int, filters: SearchFilters
    ) -> list[ChunkHit]:
        key = tuple(terms)
        self.calls.append(("keyword", key, filters))
        return self._keyword_results.get(key, [])


# Maps a vector (as a tuple) back to the text that produced it, so the fake
# store can resolve which spec a vector_search call belongs to.
_TEXT_BY_VECTOR: dict[tuple[float, ...], str] = {}


class _FakeEmbedder:
    """Returns one deterministic vector per text and registers the mapping."""

    def __init__(self) -> None:
        self._counter = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            self._counter += 1
            vector = [float(self._counter)]
            _TEXT_BY_VECTOR[tuple(vector)] = text
            vectors.append(vector)
        return vectors


def _spec(
    *,
    mode: str = "semantic",
    semantic: str | None = "q",
    keywords: tuple[str, ...] = (),
    filters: SearchFilters | None = None,
    rationale: str = "r",
) -> RetrievalSpec:
    """Build a RetrievalSpec; filters default to an all-None SearchFilters."""
    return RetrievalSpec(
        mode=mode,  # type: ignore[arg-type]
        semantic=semantic,
        keywords=keywords,
        filters=filters
        if filters is not None
        else SearchFilters(
            date_from=None,
            date_to=None,
            correspondent_id=None,
            document_type_id=None,
            tag_ids=(),
        ),
        rationale=rationale,
    )


def _retriever(store: _FakeStoreReader, **settings_overrides: object) -> Retriever:
    defaults: dict[str, object] = {
        "SEARCH_TOP_K": 10,
        "SEARCH_PER_SPEC_K": 10,
        "SEARCH_MAX_CHUNKS_PER_DOC": 3,
    }
    defaults.update(settings_overrides)
    settings = make_search_settings(**defaults)
    return Retriever(settings, store, _FakeEmbedder())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Cross-spec fusion
# ---------------------------------------------------------------------------


def test_document_hit_by_two_specs_outranks_single_spec_hit() -> None:
    """A doc hit by two specs gets a higher fused rrf_score than a single-spec hit."""
    store = _FakeStoreReader(
        vector_results={
            "q1": [
                make_chunk_hit(chunk_id=1, document_id=10, score=0.1),
                make_chunk_hit(chunk_id=2, document_id=20, score=0.2),
            ],
            "q2": [make_chunk_hit(chunk_id=1, document_id=10, score=0.15)],
        }
    )
    retriever = _retriever(store)
    specs = (_spec(semantic="q1"), _spec(semantic="q2"))

    chunks, _ = retriever.retrieve(specs)

    score_by_doc = {c.document_id: c.rrf_score for c in chunks}
    assert score_by_doc[10] > score_by_doc[20]


def test_each_spec_passes_its_own_filters_to_the_store() -> None:
    """The distinct SearchFilters on each spec is the one used for that store call."""
    filters_a = SearchFilters(
        date_from="2025-01-01",
        date_to=None,
        correspondent_id=11,
        document_type_id=None,
        tag_ids=(),
    )
    filters_b = SearchFilters(
        date_from=None,
        date_to=None,
        correspondent_id=None,
        document_type_id=22,
        tag_ids=(),
    )
    filters_kw = SearchFilters(
        date_from=None,
        date_to=None,
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(33,),
    )
    store = _FakeStoreReader()
    retriever = _retriever(store)
    specs = (
        _spec(semantic="alpha", filters=filters_a),
        _spec(semantic="beta", filters=filters_b),
        _spec(mode="keyword", semantic=None, keywords=("kw",), filters=filters_kw),
    )

    retriever.retrieve(specs)

    by_query = {query: filters for _, query, filters in store.calls}
    assert by_query["alpha"] is filters_a
    assert by_query["beta"] is filters_b
    assert by_query[("kw",)] is filters_kw


# ---------------------------------------------------------------------------
# Per-document chunk cap
# ---------------------------------------------------------------------------


def test_per_document_chunk_cap_keeps_highest_scoring_chunks() -> None:
    """A doc with 5 candidate chunks yields at most SEARCH_MAX_CHUNKS_PER_DOC chunks.

    Hits are listed best-first (rank 1..5), so RRF gives chunk_id 1 the highest
    fused score and chunk_id 5 the lowest.  With the cap at 3 the kept chunks are
    the three highest-scoring (ids 1, 2, 3).
    """
    store = _FakeStoreReader(
        vector_results={
            "q": [
                make_chunk_hit(chunk_id=cid, document_id=10, score=0.1 * cid)
                for cid in range(1, 6)
            ]
        }
    )
    retriever = _retriever(store, SEARCH_MAX_CHUNKS_PER_DOC=3)

    chunks, _ = retriever.retrieve((_spec(semantic="q"),))

    doc_chunks = [c for c in chunks if c.document_id == 10]
    assert len(doc_chunks) == 3
    assert {c.chunk_id for c in doc_chunks} == {1, 2, 3}


def test_returns_at_most_top_k_documents_sorted_by_score() -> None:
    """The output spans <= SEARCH_TOP_K documents and is sorted by rrf_score desc."""
    store = _FakeStoreReader(
        vector_results={
            "q": [
                make_chunk_hit(chunk_id=cid, document_id=cid * 10, score=0.1 * cid)
                for cid in range(1, 6)
            ]
        }
    )
    retriever = _retriever(store, SEARCH_TOP_K=2)

    chunks, _ = retriever.retrieve((_spec(semantic="q"),))

    document_ids = {c.document_id for c in chunks}
    assert len(document_ids) <= 2
    scores = [c.rrf_score for c in chunks]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Empty / signal
# ---------------------------------------------------------------------------


def test_empty_specs_yield_empty_result_and_default_signal() -> None:
    """No specs at all → ([], RetrievalSignal(None, False))."""
    store = _FakeStoreReader()
    retriever = _retriever(store)

    chunks, signal = retriever.retrieve(())

    assert chunks == []
    assert signal == RetrievalSignal(best_vector_similarity=None, has_keyword_hit=False)


def test_no_hits_yield_empty_result_and_default_signal() -> None:
    """Specs that match nothing → ([], RetrievalSignal(None, False))."""
    store = _FakeStoreReader()
    retriever = _retriever(store)
    specs = (
        _spec(semantic="q"),
        _spec(mode="keyword", semantic=None, keywords=("kw",)),
    )

    chunks, signal = retriever.retrieve(specs)

    assert chunks == []
    assert signal.best_vector_similarity is None
    assert signal.has_keyword_hit is False


# ---------------------------------------------------------------------------
# Per-chunk vector_similarity
# ---------------------------------------------------------------------------


def test_keyword_only_chunk_has_no_vector_similarity_vector_chunk_does() -> None:
    """A keyword-only chunk has vector_similarity None; a vector chunk has a float."""
    store = _FakeStoreReader(
        vector_results={"q": [make_chunk_hit(chunk_id=1, document_id=10, score=0.2)]},
        keyword_results={
            ("kw",): [make_chunk_hit(chunk_id=2, document_id=20, score=0.0)]
        },
    )
    retriever = _retriever(store)
    specs = (
        _spec(semantic="q"),
        _spec(mode="keyword", semantic=None, keywords=("kw",)),
    )

    chunks, signal = retriever.retrieve(specs)

    similarity_by_chunk = {c.chunk_id: c.vector_similarity for c in chunks}
    assert similarity_by_chunk[2] is None
    assert isinstance(similarity_by_chunk[1], float)
    # The vector pass set the signal; the keyword pass set has_keyword_hit.
    assert signal.best_vector_similarity is not None
    assert signal.has_keyword_hit is True
