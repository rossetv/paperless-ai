"""Search-pipeline test factories, plus the store read-shapes the search tests use."""

from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path
from typing import Any

from search.models import (
    Answered,
    CostSummary,
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
    TokenUsage,
)
from search.relevance import RelevanceThresholds, RelevanceTier
from store.models import (
    ChunkHit,
    FacetSet,
    IndexedDocument,
    IndexStats,
    TaxonomyEntry,
)


# Planner / retriever shapes


def make_filter_candidates(
    *,
    correspondent: str | None = None,
    document_type: str | None = None,
    tags: tuple[str, ...] = (),
    date_from: str | None = None,
    date_to: str | None = None,
) -> FilterCandidates:
    """Create a FilterCandidates; every field defaults to "no candidate"."""
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
    """Create a PlannedSpec with a single semantic query and no filter guesses."""
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
    """Create a RetrievalPlan with one broad semantic spec and no clarify."""
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


# Synthesiser outcome shapes


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


# Result shapes


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
    """Create a SourceDocument; *paperless_url* defaults to a link for *document_id*."""
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
    total_tokens: int | None = None,
) -> SearchStats:
    """Create a SearchStats; the default models a normal two-call query.

    *total_tokens* sets ``cost.tokens.total``, the value the spend quota reads.
    """
    if total_tokens is None:
        return SearchStats(llm_calls=llm_calls, latency_ms=latency_ms, refined=refined)
    cost = CostSummary(
        tokens=TokenUsage(
            prompt=total_tokens, completion=0, reasoning=0, total=total_tokens
        ),
        usd=None,
        local=False,
        llm_calls=llm_calls,
    )
    return SearchStats(
        llm_calls=llm_calls, latency_ms=latency_ms, refined=refined, cost=cost
    )


def make_search_result(
    *,
    answer: str = "The synthesised answer.",
    sources: tuple[SourceDocument, ...] | None = None,
    plan: RetrievalPlan | None = None,
    stats: SearchStats | None = None,
    outcome_kind: str = "answered",
) -> SearchResult:
    """Create a SearchResult with one source, a default plan, and default stats.

    Pass ``outcome_kind="no_match"`` or ``"clarify"`` (with ``sources=()``) to
    build the short-circuit shapes.
    """
    return SearchResult(
        answer=answer,
        sources=(sources if sources is not None else (make_source_document(),)),
        plan=plan if plan is not None else make_retrieval_plan(),
        stats=stats if stats is not None else make_search_stats(),
        outcome_kind=outcome_kind,
    )


# Store read-shapes


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
    latest_indexed_at: str | None = None,
) -> IndexStats:
    """Create an IndexStats; defaults model a reconciled, empty index.

    Pass ``last_reconcile_at=None`` for the never-reconciled case.
    ``latest_indexed_at`` is the result cache's content signal.
    """
    return IndexStats(
        document_count=document_count,
        chunk_count=chunk_count,
        last_reconcile_at=last_reconcile_at,
        embedding_model=embedding_model,
        latest_indexed_at=latest_indexed_at,
    )


# Settings-like mock for the search pipeline


# A per-process temp directory for the unique ``APP_DB_PATH`` default below,
# removed when the test process exits.
_APP_DB_TMP_DIR = Path(tempfile.mkdtemp(prefix="paperless-ai-test-appdb-"))
atexit.register(shutil.rmtree, _APP_DB_TMP_DIR, ignore_errors=True)

# Counter giving every make_search_settings() call a distinct app.db path.
_app_db_counter = 0


def _unique_app_db_path() -> str:
    """Return a fresh ``app.db`` path for a settings mock.

    ``create_app`` migrates and persists users into ``APP_DB_PATH``; a shared
    path would leak one test's users into another's first-run-setup state.
    """
    global _app_db_counter
    _app_db_counter += 1
    return str(_APP_DB_TMP_DIR / f"app-{_app_db_counter}.db")


def make_relevance_thresholds(
    *, strong: float = 0.70, good: float = 0.66, partial: float = 0.60
) -> RelevanceThresholds:
    """Build a :class:`RelevanceThresholds` with the calibrated defaults."""
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
    """Build a JudgeCandidate; metadata fields default to ``None`` (snippet only)."""
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
    """Build a JudgeVerdict keeping each id in *relevant_document_ids* (default: 1).

    Tests that care about per-document verdict details should build a
    :class:`~search.models.JudgeVerdict` directly.
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

    A MagicMock turns any unset attribute into a truthy mock, which silently
    breaks comparisons, slices and flags downstream, so every field the pipeline
    reads is pinned to a real value. ``APP_DB_PATH`` is unique per call.
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
        # 0 = unlimited, so non-quota tests do no quota I/O.
        "SEARCH_KEY_DAILY_TOKEN_QUOTA": 0,
        # Keep the planner and synthesiser ``@retry`` decorators well-formed.
        "MAX_RETRIES": 3,
        "MAX_RETRY_BACKOFF_SECONDS": 30,
        # "openai" so the structured-output helpers build a schema.
        "LLM_PROVIDER": "openai",
        # All openai so the structured-output / reasoning gates fire and the
        # fallback to CLASSIFY_MODELS stays provider-coherent; Ollama tests pin
        # the specific step provider instead.
        "OCR_PROVIDER": "openai",
        "CLASSIFY_PROVIDER": "openai",
        "SEARCH_PLANNER_PROVIDER": "openai",
        "SEARCH_JUDGE_PROVIDER": "openai",
        "SEARCH_ANSWER_PROVIDER": "openai",
        "SEARCH_PLANNER_REASONING_EFFORT": "medium",
        "SEARCH_ANSWER_REASONING_EFFORT": "medium",
        # Cache off so LLM-call-count assertions see real (mocked) calls.
        "SEARCH_CACHE_TTL_SECONDS": 0,
        "SEARCH_SKIP_PLANNER_FOR_TRIVIAL": False,
        "SEARCH_GATE_ADEQUACY": True,
        "SEARCH_GATE_RELEVANCE": True,
        # Production uses 0.60, but a real floor against a synthetic test index
        # is brittle; Layer 2 tests override it.
        "SEARCH_RELEVANCE_MIN_SIMILARITY": 0.0,
        "SEARCH_RELEVANCE_TIER_STRONG": 0.70,
        "SEARCH_RELEVANCE_TIER_GOOD": 0.66,
        "SEARCH_RELEVANCE_TIER_PARTIAL": 0.60,
        "SEARCH_MIN_QUERY_CHARS": 2,
        # On in production, off here: the judge is an extra LLM call that would
        # change call-count assertions. Judge tests opt in.
        "SEARCH_GATE_JUDGE": False,
        "SEARCH_JUDGE_MODEL": "gpt-5.4-mini",
        "SEARCH_JUDGE_REASONING_EFFORT": "low",
        "SEARCH_JUDGE_RATIONALES": True,
        "SEARCH_IDENTITY_AWARE": True,
        "SEARCH_PLANNER_MAX_SPECS": 8,
        "SEARCH_PLANNER_TAXONOMY_LIMIT": 100,
        "SEARCH_PER_SPEC_K": 10,
        "SEARCH_MAX_CHUNKS_PER_DOC": 3,
        # Empty URL disables the refresh thread, keeping create_app network-free.
        "PRICING_REFRESH_URL": "",
        "PRICING_REFRESH_INTERVAL_HOURS": 24,
    }
    defaults.update(overrides)
    settings = MagicMock()
    for key, value in defaults.items():
        setattr(settings, key, value)
    return settings
