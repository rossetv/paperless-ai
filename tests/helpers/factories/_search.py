"""Search-pipeline test factories.

The ``tests.helpers.factories`` package re-exports every factory from its
``__init__``; this submodule holds the builders for the search-pipeline shapes
— :class:`~search.models.FilterCandidates`, :class:`~search.models.PlannedSpec`,
:class:`~search.models.RetrievalPlan`,
:class:`~search.models.RetrievedChunk`, :class:`~search.models.SourceDocument`,
:class:`~search.models.SearchStats`, :class:`~search.models.SearchResult`,
:class:`~search.models.Answered`, :class:`~search.models.NeedsMore` — and the
store read-shapes the search tests need (:class:`~store.models.ChunkHit`,
:class:`~store.models.IndexedDocument`, :class:`~store.models.TaxonomyEntry`,
:class:`~store.models.FacetSet`, :class:`~store.models.IndexStats`).

Each factory fills every irrelevant field with a deterministic default so a
test spells out only the field under test (CODE_GUIDELINES §11.5).  These
replace the ~28 hand-rolled ``_make_*`` builders the search test files used to
each redeclare.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path
from typing import Any

from search.models import (
    Answered,
    DocVerdict,
    FilterCandidates,
    JudgeCandidate,
    JudgeVerdict,
    NeedsMore,
    PlannedSpec,
    RetrievalPlan,
    RetrievedChunk,
    SearchResult,
    SearchStats,
    SourceDocument,
)
from search.relevance import RelevanceThresholds, RelevanceTier
from store.models import (
    ChunkHit,
    FacetSet,
    IndexedDocument,
    IndexStats,
    TaxonomyEntry,
)


# ---------------------------------------------------------------------------
# Planner / retriever shapes
# ---------------------------------------------------------------------------


def make_filter_candidates(
    *,
    correspondent: str | None = None,
    document_type: str | None = None,
    tags: tuple[str, ...] = (),
    date_from: str | None = None,
    date_to: str | None = None,
) -> FilterCandidates:
    """Create a FilterCandidates; every field defaults to "no candidate".

    The all-default call models the planner emitting no filter guesses; a test
    that exercises one candidate passes only that keyword.
    """
    return FilterCandidates(
        correspondent=correspondent,
        document_type=document_type,
        tags=tags,
        date_from=date_from,
        date_to=date_to,
    )


def make_planned_spec(
    *,
    mode: str = "semantic",
    semantic: str | None = "test query",
    keywords: tuple[str, ...] = (),
    filter_guess: FilterCandidates | None = None,
    rationale: str = "test spec",
) -> PlannedSpec:
    """Create a PlannedSpec with a single semantic query and no filter guesses.

    *filter_guess* defaults to an all-``None`` :class:`FilterCandidates`
    (via :func:`make_filter_candidates`) so a test that does not care about
    filters need not spell one out.
    """
    return PlannedSpec(
        mode=mode,  # type: ignore[arg-type]
        semantic=semantic,
        keywords=keywords,
        filter_guess=(
            filter_guess if filter_guess is not None else make_filter_candidates()
        ),
        rationale=rationale,
    )


def make_retrieval_plan(
    *,
    specs: tuple[PlannedSpec, ...] | None = None,
    clarify: object | None = None,
) -> RetrievalPlan:
    """Create a RetrievalPlan with one broad semantic spec and no clarify.

    *specs* defaults to a single :func:`make_planned_spec` so a test that does
    not care about the plan shape need not spell one out.
    """
    return RetrievalPlan(
        specs=specs if specs is not None else (make_planned_spec(),),
        clarify=clarify,  # type: ignore[arg-type]
    )


def make_retrieved_chunk(
    *,
    chunk_id: int = 1,
    document_id: int = 1,
    text: str = "Retrieved chunk text.",
    page_hint: int | None = 1,
    rrf_score: float = 0.5,
    vector_similarity: float | None = None,
) -> RetrievedChunk:
    """Create a RetrievedChunk — one fused chunk as the retriever returns it."""
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        page_hint=page_hint,
        rrf_score=rrf_score,
        vector_similarity=vector_similarity,
    )


# ---------------------------------------------------------------------------
# Synthesiser outcome shapes
# ---------------------------------------------------------------------------


def make_answered(
    *,
    answer: str = "The synthesised answer.",
    citations: tuple[int, ...] = (1,),
) -> Answered:
    """Create an Answered synthesiser outcome with one citation by default."""
    return Answered(answer=answer, citations=citations)


def make_needs_more(
    *, adjustment: str = "Broaden the search to related documents."
) -> NeedsMore:
    """Create a NeedsMore synthesiser outcome with a generic adjustment hint."""
    return NeedsMore(adjustment=adjustment)


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


def make_source_document(
    *,
    document_id: int = 1,
    title: str | None = "Test Document",
    correspondent: str | None = None,
    document_type: str | None = None,
    created: str | None = "2024-01-15T00:00:00Z",
    snippet: str = "A representative snippet.",
    paperless_url: str | None = None,
    score: float = 0.9,
    relevance_tier: RelevanceTier = "good",
) -> SourceDocument:
    """Create a SourceDocument — one ranked source in a SearchResult.

    *paperless_url* defaults to a deep-link derived from *document_id* so a
    test that does not care about the URL need not spell one out.
    """
    return SourceDocument(
        document_id=document_id,
        title=title,
        correspondent=correspondent,
        document_type=document_type,
        created=created,
        snippet=snippet,
        paperless_url=(
            paperless_url
            if paperless_url is not None
            else f"http://paperless.example:8000/documents/{document_id}/"
        ),
        score=score,
        relevance_tier=relevance_tier,
    )


def make_search_stats(
    *,
    llm_calls: int = 2,
    latency_ms: int = 100,
    refined: bool = False,
) -> SearchStats:
    """Create a SearchStats — the default models a normal two-call query."""
    return SearchStats(llm_calls=llm_calls, latency_ms=latency_ms, refined=refined)


def make_search_result(
    *,
    answer: str = "The synthesised answer.",
    sources: tuple[SourceDocument, ...] | None = None,
    plan: RetrievalPlan | None = None,
    stats: SearchStats | None = None,
) -> SearchResult:
    """Create a SearchResult with one source, a default plan, and default stats.

    Each absent argument is filled from the matching factory, so a test asserts
    on only the field it cares about.
    """
    return SearchResult(
        answer=answer,
        sources=(sources if sources is not None else (make_source_document(),)),
        plan=plan if plan is not None else make_retrieval_plan(),
        stats=stats if stats is not None else make_search_stats(),
    )


# ---------------------------------------------------------------------------
# Store read-shapes the search tests consume
# ---------------------------------------------------------------------------


def make_chunk_hit(
    *,
    chunk_id: int = 1,
    document_id: int = 1,
    text: str = "Chunk hit text.",
    page_hint: int | None = 1,
    score: float = 0.5,
) -> ChunkHit:
    """Create a ChunkHit — one ranked hit as a StoreReader search returns it."""
    return ChunkHit(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        page_hint=page_hint,
        score=score,
    )


def make_taxonomy_entry(
    *,
    kind: str = "correspondent",
    entry_id: int = 1,
    name: str = "ACME Corp",
) -> TaxonomyEntry:
    """Create a TaxonomyEntry — one row of the store's taxonomy table."""
    return TaxonomyEntry(kind=kind, id=entry_id, name=name)


def make_indexed_document(
    *,
    document_id: int = 1,
    title: str | None = "A Document",
    correspondent: str | None = None,
    document_type: str | None = None,
    tags: tuple[str, ...] = (),
    created: str | None = "2024-01-15T00:00:00+00:00",
) -> IndexedDocument:
    """Create an IndexedDocument as StoreReader.get_documents returns it."""
    return IndexedDocument(
        id=document_id,
        title=title,
        correspondent=correspondent,
        document_type=document_type,
        tags=tags,
        created=created,
    )


def make_facet_set(
    *,
    correspondents: tuple[TaxonomyEntry, ...] = (),
    document_types: tuple[TaxonomyEntry, ...] = (),
    tags: tuple[TaxonomyEntry, ...] = (),
    earliest: str | None = None,
    latest: str | None = None,
) -> FacetSet:
    """Create a FacetSet; every facet group defaults to empty."""
    return FacetSet(
        correspondents=correspondents,
        document_types=document_types,
        tags=tags,
        earliest=earliest,
        latest=latest,
    )


def make_index_stats(
    *,
    document_count: int = 0,
    chunk_count: int = 0,
    last_reconcile_at: str | None = "2024-06-01T12:00:00Z",
    embedding_model: str | None = "text-embedding-3-small",
) -> IndexStats:
    """Create an IndexStats; defaults model a reconciled, empty index.

    ``last_reconcile_at`` defaults to a real timestamp so the common healthz
    "index is ready" path needs no override; pass ``None`` for the
    never-reconciled case.
    """
    return IndexStats(
        document_count=document_count,
        chunk_count=chunk_count,
        last_reconcile_at=last_reconcile_at,
        embedding_model=embedding_model,
    )


# ---------------------------------------------------------------------------
# Settings-like mock for the search pipeline
# ---------------------------------------------------------------------------


# A per-process temp directory for the unique ``APP_DB_PATH`` default below,
# removed when the test process exits.
_APP_DB_TMP_DIR = Path(tempfile.mkdtemp(prefix="paperless-ai-test-appdb-"))
atexit.register(shutil.rmtree, _APP_DB_TMP_DIR, ignore_errors=True)

# Counter giving every make_search_settings() call a distinct app.db path.
_app_db_counter = 0


def _unique_app_db_path() -> str:
    """Return a fresh, unused ``app.db`` path for a settings mock.

    ``search.api.create_app`` opens and migrates ``Settings.APP_DB_PATH`` at
    startup, then each request opens its own connection to it. A test that
    builds the app over the factory defaults therefore needs an ``app.db`` of
    its own — a shared path would let one test's users leak into another's
    first-run-setup state. Each call returns a distinct file under a
    process-scoped temp directory.
    """
    global _app_db_counter
    _app_db_counter += 1
    return str(_APP_DB_TMP_DIR / f"app-{_app_db_counter}.db")


def make_relevance_thresholds(
    *, strong: float = 0.70, good: float = 0.66, partial: float = 0.60
) -> RelevanceThresholds:
    """Build a :class:`RelevanceThresholds` with the calibrated defaults.

    Centralises the badge cut-points the source-assembly and relevance tests
    pass, so the default triple lives in one place. Override a band to exercise
    a custom configuration.
    """
    return RelevanceThresholds(strong=strong, good=good, partial=partial)


def make_judge_candidate(
    *,
    document_id: int = 1,
    snippet: str = "candidate snippet",
    title: str | None = None,
    created: str | None = None,
    correspondent: str | None = None,
    document_type: str | None = None,
) -> JudgeCandidate:
    """Build a JudgeCandidate for judge/core tests.

    Metadata fields default to ``None`` (the snippet-only judge candidate); a
    test exercising scope-aware judging passes the relevant metadata field.
    """
    return JudgeCandidate(
        document_id=document_id,
        snippet=snippet,
        title=title,
        created=created,
        correspondent=correspondent,
        document_type=document_type,
    )


def make_judge_verdict(
    *,
    relevant_document_ids: set[int] | None = None,
    degraded: bool = False,
    score: float = 1.0,
) -> JudgeVerdict:
    """Build a JudgeVerdict from a set of kept ids; defaults to keeping document 1.

    Constructs one :class:`~search.models.DocVerdict` per kept id (keep=True,
    full-confidence *score*, empty reason). Tests that care about per-document
    verdict details should build :class:`~search.models.JudgeVerdict` directly.
    """
    ids = frozenset(relevant_document_ids if relevant_document_ids is not None else {1})
    return JudgeVerdict(
        verdicts=tuple(
            DocVerdict(document_id=i, keep=True, reason="", score=score)
            for i in sorted(ids)
        ),
        degraded=degraded,
    )


def make_search_settings(**overrides: Any) -> Any:
    """Create a Settings-like MagicMock with every search-pipeline field set.

    The defaults span the planner, retriever, synthesiser, core, and the
    search/MCP servers, so this single factory replaces the per-file
    ``_make_settings`` mocks the search test files used to hand-roll.  The
    ``MAX_RETRIES`` / ``MAX_RETRY_BACKOFF_SECONDS`` ints keep the inherited
    ``@retry`` decorator on the planner and synthesiser well-formed even though
    tests patch ``_create_completion`` and never enter the retry loop.

    ``APP_DB_PATH`` defaults to a *unique* path per call (see
    :func:`_unique_app_db_path`) so a test building the search app over these
    defaults gets an isolated ``app.db``; pass an explicit ``APP_DB_PATH``
    override to point at a known file.

    Args:
        **overrides: Any field override — e.g. ``SEARCH_MAX_REFINEMENTS=0``.
    """
    from unittest.mock import MagicMock

    defaults: dict[str, Any] = {
        "PAPERLESS_URL": "http://paperless.example:8000",
        "PAPERLESS_PUBLIC_URL": "http://paperless.example:8000",
        "INDEX_DB_PATH": "/tmp/test-index.db",
        "APP_DB_PATH": _unique_app_db_path(),
        "EMBEDDING_MODEL": "text-embedding-3-small",
        "EMBEDDING_DIMENSIONS": 4,
        "SEARCH_TOP_K": 10,
        "SEARCH_MAX_REFINEMENTS": 1,
        "SEARCH_MAX_CONCURRENT": 4,
        "SEARCH_PLANNER_MODEL": "gpt-5.4-mini",
        "SEARCH_ANSWER_MODEL": "gpt-5.4",
        "CLASSIFY_MODELS": ["gpt-5.4-mini", "gpt-5.4"],
        "SEARCH_SESSION_TTL": 3600,
        "MAX_RETRIES": 3,
        "MAX_RETRY_BACKOFF_SECONDS": 30,
        # Area-3 SEARCH_* settings. A MagicMock auto-creates any unset attribute
        # as a truthy mock, so these must be pinned or downstream search tests
        # silently misbehave (CODE_GUIDELINES §11.5). The cache is OFF (TTL 0)
        # so existing two-call assertions keep making real (mocked) LLM calls;
        # LLM_PROVIDER="openai" so the structured-output helpers build a schema.
        "LLM_PROVIDER": "openai",
        "SEARCH_PLANNER_REASONING_EFFORT": "medium",
        "SEARCH_ANSWER_REASONING_EFFORT": "medium",
        "SEARCH_CACHE_TTL_SECONDS": 0,
        "SEARCH_SKIP_PLANNER_FOR_TRIVIAL": False,
        # Fail-fast gate knobs (Task 1). Mirror the production defaults so tests
        # are explicit about what they get rather than relying on MagicMock's
        # auto-truthy behaviour (CODE_GUIDELINES §11.5).
        "SEARCH_GATE_ADEQUACY": True,
        "SEARCH_GATE_RELEVANCE": True,
        # 0.0 keeps Layer 2 inert by default (the production default is 0.60, but
        # a real floor against a synthetic test index is brittle).  Tests that
        # exercise Layer 2 override with an explicit non-zero value.
        "SEARCH_RELEVANCE_MIN_SIMILARITY": 0.0,
        # Relevance-badge cut-points — mirror the production defaults so the core
        # builds a well-formed RelevanceThresholds (a bare MagicMock attribute
        # would be a truthy mock, not a float, and break the comparison).
        "SEARCH_RELEVANCE_TIER_STRONG": 0.70,
        "SEARCH_RELEVANCE_TIER_GOOD": 0.66,
        "SEARCH_RELEVANCE_TIER_PARTIAL": 0.60,
        "SEARCH_MIN_QUERY_CHARS": 2,
        # The judge defaults ON in production, but OFF here so existing core
        # tests keep their exact LLM-call-count assertions (it is a real extra
        # LLM call). Judge tests opt in with SEARCH_GATE_JUDGE=True and a scripted
        # judge_response, mirroring SEARCH_RELEVANCE_MIN_SIMILARITY=0.0.
        "SEARCH_GATE_JUDGE": False,
        "SEARCH_JUDGE_MODEL": "gpt-5.4-mini",
        "SEARCH_JUDGE_REASONING_EFFORT": "low",
        # Rationales ON mirrors the production default; tests that want lean
        # output (no reason strings) can override with SEARCH_JUDGE_RATIONALES=False.
        "SEARCH_JUDGE_RATIONALES": True,
        # Identity-awareness (Task 10). Defaults ON in production; pinned here
        # so make_search_settings always returns a real bool, not a truthy mock,
        # and tests that need it off can override with SEARCH_IDENTITY_AWARE=False.
        "SEARCH_IDENTITY_AWARE": True,
        # Cap on the number of planner specs (SEARCH_PLANNER_MAX_SPECS). A
        # MagicMock auto-attribute used as a slice index silently returns only
        # the first element; pin to 8 (the production default) so multi-spec
        # tests get the full list without needing to override.
        "SEARCH_PLANNER_MAX_SPECS": 8,
        # Multi-spec retriever knobs. A MagicMock auto-attribute used as an
        # int comparison or slice index misbehaves, so pin both to their
        # production defaults (SEARCH_PER_SPEC_K defaults to SEARCH_TOP_K=10).
        "SEARCH_PER_SPEC_K": 10,
        "SEARCH_MAX_CHUNKS_PER_DOC": 3,
    }
    defaults.update(overrides)
    settings = MagicMock()
    for key, value in defaults.items():
        setattr(settings, key, value)
    return settings
