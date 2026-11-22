"""Hybrid retrieval with Reciprocal Rank Fusion.

:func:`resolve_specs` turns the planner's free-text filter guesses into
taxonomy ids and ISO dates; :class:`Retriever` searches each spec and fuses the
ranked lists.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import structlog

from common.embeddings import EMBEDDING_FAILURE_EXCEPTIONS
from search.dates import extract_date_range, normalise_iso_date
from search.models import (
    FilterCandidates,
    PlannedSpec,
    RetrievalPlan,
    RetrievalSignal,
    RetrievalSpec,
    RetrievedChunk,
)
from store.models import ChunkHit, FacetSet, TaxonomyEntry
from store.reader import SearchFilters, StoreReader

if TYPE_CHECKING:
    from datetime import date

    from common.config import Settings
    from common.embeddings import EmbeddingClient

log = structlog.get_logger(__name__)

# The standard RRF smoothing constant (Cormack, Clarke, Buettcher 2009).
_RRF_K = 60


# Accent marks are dropped only on these scripts. In others (Indic, Thai,
# Arabic, ...) the marks carry vowels, so dropping them splits or merges words.
_ACCENT_SCRIPTS = ("LATIN", "GREEK", "CYRILLIC")


def _fold(text: str) -> str:
    """Lower-case, strip Latin/Greek/Cyrillic accents, map non-word chars to space.

    Combining marks on other scripts stay as part of their word.
    """
    out: list[str] = []
    base_is_accentable = False
    for ch in unicodedata.normalize("NFKD", text).casefold():
        if unicodedata.category(ch).startswith("M"):
            if not base_is_accentable:
                out.append(ch)
            continue
        base_is_accentable = unicodedata.name(ch, "").startswith(_ACCENT_SCRIPTS)
        out.append(ch if ch.isalnum() else " ")
    return "".join(out)


def _normalise(text: str) -> str:
    """Normalise for fuzzy taxonomy matching: "Gas-Bill." == "gas bill" == "gasbill"."""
    return "".join(_fold(text).split())


# Connectives ignored when comparing word sets. "a"/"an" are left out on purpose:
# stripping them would make "Schedule A" equal "Schedule B".
_STOPWORDS = frozenset({"of", "the", "and", "for", "to"})


@dataclass(frozen=True, slots=True)
class NameMatch:
    """Outcome of resolving one planner name guess against a taxonomy.

    ``method`` is one of ``exact``, ``normalised``, ``loose`` (unique equal word
    set), ``ambiguous``, ``near_miss`` or ``none``; only the first three set
    ``id``. ``candidates`` lists the competing names for ``ambiguous`` and the
    overlapping names for ``near_miss``, for the trace.
    """

    id: int | None
    method: str
    candidates: tuple[str, ...] = ()


def _tokenise(text: str) -> frozenset[str]:
    """Split *text* into normalised whole-word tokens, so "ID" never matches "Video"."""
    return frozenset(_fold(text).split())


def _content_tokens(text: str) -> frozenset[str]:
    """Whole-word tokens of *text* without connectives.

    "Employment Contract" then matches "Contract of Employment" but not
    "Contract".
    """
    return _tokenise(text) - _STOPWORDS


def _match_name(
    candidate: str,
    entries: Sequence[TaxonomyEntry],
) -> NameMatch:
    """Resolve *candidate* against *entries*: exact, normalised, then word set.

    The word-set pass needs exactly the candidate's content words. A broader or
    narrower name does not resolve: a wrong filter is worse than none, since
    text retrieval still runs.
    """
    for entry in entries:
        if entry.name == candidate:
            return NameMatch(id=entry.id, method="exact")

    normalised_candidate = _normalise(candidate)
    if normalised_candidate:
        for entry in entries:
            if _normalise(entry.name) == normalised_candidate:
                return NameMatch(id=entry.id, method="normalised")

    candidate_tokens = _content_tokens(candidate)
    if candidate_tokens:
        equal = [
            entry
            for entry in entries
            if _content_tokens(entry.name) == candidate_tokens
        ]
        if len(equal) == 1:
            return NameMatch(id=equal[0].id, method="loose")
        if len(equal) > 1:
            return NameMatch(
                id=None,
                method="ambiguous",
                candidates=tuple(entry.name for entry in equal),
            )
        # Near-misses are reported for the trace, never applied.
        near = sorted(
            (e for e in entries if _content_tokens(e.name) & candidate_tokens),
            key=lambda e: len(_content_tokens(e.name) & candidate_tokens),
            reverse=True,
        )
        if near:
            return NameMatch(
                id=None,
                method="near_miss",
                candidates=tuple(entry.name for entry in near[:5]),
            )

    return NameMatch(id=None, method="none")


def _resolve_dates(
    filter_guess: FilterCandidates,
    today: date,
) -> tuple[str | None, str | None]:
    """Resolve a spec's date guesses into a validated ``(date_from, date_to)`` pair.

    Valid ISO bounds win and a malformed one is dropped, so a hallucinated date
    never narrows the search. With no valid ISO bound, a free-text expression
    ("last month") goes through :func:`extract_date_range`.
    """
    iso_from = (
        normalise_iso_date(filter_guess.date_from) if filter_guess.date_from else None
    )
    iso_to = normalise_iso_date(filter_guess.date_to) if filter_guess.date_to else None

    if iso_from or iso_to:
        return iso_from, iso_to

    raw_guess = filter_guess.date_from or filter_guess.date_to
    if raw_guess:
        return extract_date_range(raw_guess, today)

    return None, None


def _intersect(
    spec_filters: SearchFilters,
    ui_filters: SearchFilters | None,
) -> SearchFilters:
    """Intersect a spec's filters with the user's UI filters, which only narrow.

    The date window shrinks to the overlap, a UI correspondent or document type
    overrides the spec's, and tags are the union since all are required.
    """
    if ui_filters is None:
        return spec_filters

    date_from = _later_iso(spec_filters.date_from, ui_filters.date_from)
    date_to = _earlier_iso(spec_filters.date_to, ui_filters.date_to)

    correspondent_id = (
        ui_filters.correspondent_id
        if ui_filters.correspondent_id is not None
        else spec_filters.correspondent_id
    )
    document_type_id = (
        ui_filters.document_type_id
        if ui_filters.document_type_id is not None
        else spec_filters.document_type_id
    )

    return SearchFilters(
        date_from=date_from,
        date_to=date_to,
        correspondent_id=correspondent_id,
        document_type_id=document_type_id,
        tag_ids=_union_ids(spec_filters.tag_ids, ui_filters.tag_ids),
    )


def _later_iso(left: str | None, right: str | None) -> str | None:
    """Return the later of two ISO date bounds; ``None`` means unbounded."""
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _earlier_iso(left: str | None, right: str | None) -> str | None:
    """Return the earlier of two ISO date bounds; ``None`` means unbounded."""
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _union_ids(left: tuple[int, ...], right: tuple[int, ...]) -> tuple[int, ...]:
    """Return the order-stable, de-duplicated union of two id tuples."""
    seen: set[int] = set()
    union: list[int] = []
    for tag_id in (*left, *right):
        if tag_id not in seen:
            seen.add(tag_id)
            union.append(tag_id)
    return tuple(union)


def resolve_specs(
    plan: RetrievalPlan,
    facets: FacetSet,
    *,
    ui_filters: SearchFilters | None,
    today: date,
    query: str = "",
    max_specs: int | None = None,
) -> tuple[RetrievalSpec, ...]:
    """Resolve every planned spec's filter guesses into store filters.

    Names that do not match the taxonomy are dropped, never guessed at an id,
    and every spec is intersected with *ui_filters*.

    Date safety net: when *query* names a period but no spec got a date filter
    (a degraded or fallback plan), a date-scoped copy of the first semantic spec
    is appended; the unbound originals stay for recall. An empty *query*
    disables it.

    *max_specs* enables unfiltered twins of filtered specs. Only twins count
    against it, so the total can reach ``max_specs + 1`` with the safety net.
    """
    resolved: list[RetrievalSpec] = []
    for spec in plan.specs:
        resolved.append(_resolve_one_spec(spec, facets, ui_filters, today))

    if query and not _any_has_date(resolved):
        date_from, date_to = extract_date_range(query, today)
        if date_from is not None or date_to is not None:
            resolved.append(
                _make_safety_net_spec(resolved, query, date_from, date_to, ui_filters)
            )

    if max_specs is not None:
        resolved = _append_unfiltered_twins(resolved, max_specs)

    return tuple(resolved)


def _any_has_date(specs: list[RetrievalSpec]) -> bool:
    """Return True when at least one spec already carries a date filter."""
    return any(
        spec.filters.date_from is not None or spec.filters.date_to is not None
        for spec in specs
    )


_EMPTY_FILTERS = SearchFilters(
    date_from=None,
    date_to=None,
    correspondent_id=None,
    document_type_id=None,
    tag_ids=(),
)


def _has_filter(f: SearchFilters) -> bool:
    """True when the spec carries any resolved filter (so a twin would differ)."""
    return (
        f.correspondent_id is not None
        or f.document_type_id is not None
        or bool(f.tag_ids)
        or f.date_from is not None
        or f.date_to is not None
    )


def _retrieval_key(spec: RetrievalSpec) -> tuple[object, ...]:
    """Identity that affects retrieval — excludes rationale so twins dedup on it."""
    return (spec.mode, spec.semantic, spec.keywords, spec.filters)


def _append_unfiltered_twins(
    resolved: list[RetrievalSpec], max_specs: int
) -> list[RetrievalSpec]:
    """Append a filter-stripped twin of each filtered spec (deduped, capped).

    A wrong filter silently excludes the answer; the twin re-admits it, and if
    the filter was right RRF rewards the document both found. Originals always
    survive the cap.
    """
    out = list(resolved)
    seen = {_retrieval_key(spec) for spec in resolved}
    for spec in resolved:
        if len(out) >= max_specs:
            break
        if not _has_filter(spec.filters):
            continue
        twin = replace(spec, filters=_EMPTY_FILTERS)
        key = _retrieval_key(twin)
        if key in seen:
            continue
        seen.add(key)
        out.append(twin)
    return out


def _broad_semantic_base(query: str) -> RetrievalSpec:
    """Build a broad, unfiltered semantic spec on the raw *query*."""
    return RetrievalSpec(
        mode="semantic",
        semantic=query,
        keywords=(),
        filters=_EMPTY_FILTERS,
        rationale="fallback: broad semantic search",
    )


def _make_safety_net_spec(
    resolved: list[RetrievalSpec],
    query: str,
    date_from: str | None,
    date_to: str | None,
    ui_filters: SearchFilters | None,
) -> RetrievalSpec:
    """Build the safety-net spec: a date-scoped copy of the most relevant spec.

    The base is the first semantic spec, else the first spec, else (for an
    empty plan) a broad semantic spec on *query*. Its other filters are kept.
    """
    base = next(
        (s for s in resolved if s.mode == "semantic"),
        resolved[0] if resolved else _broad_semantic_base(query),
    )

    date_scoped_filters = SearchFilters(
        date_from=_later_iso(base.filters.date_from, date_from),
        date_to=_earlier_iso(base.filters.date_to, date_to),
        correspondent_id=base.filters.correspondent_id,
        document_type_id=base.filters.document_type_id,
        tag_ids=base.filters.tag_ids,
    )
    final_filters = _intersect(date_scoped_filters, ui_filters)

    return RetrievalSpec(
        mode=base.mode,
        semantic=base.semantic,
        keywords=base.keywords,
        filters=final_filters,
        rationale="deterministic date safety net: query names an explicit period",
    )


def _resolve_one_spec(
    spec: PlannedSpec,
    facets: FacetSet,
    ui_filters: SearchFilters | None,
    today: date,
) -> RetrievalSpec:
    """Resolve one planned spec into a ready-for-store RetrievalSpec."""
    guess = spec.filter_guess

    correspondent_id = (
        _match_name(guess.correspondent, facets.correspondents).id
        if guess.correspondent is not None
        else None
    )
    document_type_id = (
        _match_name(guess.document_type, facets.document_types).id
        if guess.document_type is not None
        else None
    )
    tag_ids = tuple(
        match.id
        for tag_candidate in guess.tags
        if (match := _match_name(tag_candidate, facets.tags)).id is not None
    )
    date_from, date_to = _resolve_dates(guess, today)

    spec_filters = SearchFilters(
        date_from=date_from,
        date_to=date_to,
        correspondent_id=correspondent_id,
        document_type_id=document_type_id,
        tag_ids=tag_ids,
    )

    return RetrievalSpec(
        mode=spec.mode,
        semantic=spec.semantic,
        keywords=spec.keywords,
        filters=_intersect(spec_filters, ui_filters),
        rationale=spec.rationale,
    )


def _fuse_with_rrf(
    ranked_lists: list[list[ChunkHit]],
) -> tuple[dict[int, float], dict[int, ChunkHit]]:
    """Fuse best-first ranked lists: each chunk scores ``Σ 1 / (_RRF_K + rank)``.

    Ranks are 1-based, as in the original paper. Returns the fused scores and
    each chunk's first-seen :class:`ChunkHit`.
    """
    fused_score: dict[int, float] = {}
    first_hit: dict[int, ChunkHit] = {}

    for ranked_list in ranked_lists:
        for position, hit in enumerate(ranked_list):
            rank = position + 1
            contribution = 1.0 / (_RRF_K + rank)
            if hit.chunk_id in fused_score:
                fused_score[hit.chunk_id] += contribution
            else:
                fused_score[hit.chunk_id] = contribution
                first_hit[hit.chunk_id] = hit

    return fused_score, first_hit


def _top_document_ids(
    fused_score: dict[int, float],
    first_hit: dict[int, ChunkHit],
    top_k: int,
) -> set[int]:
    """Return the ids of the *top_k* documents by their best chunk's score."""
    doc_best_score: dict[int, float] = {}
    for chunk_id, score in fused_score.items():
        document_id = first_hit[chunk_id].document_id
        if score > doc_best_score.get(document_id, -1.0):
            doc_best_score[document_id] = score

    ranked_doc_ids = sorted(doc_best_score.items(), key=lambda kv: kv[1], reverse=True)
    return {document_id for document_id, _ in ranked_doc_ids[:top_k]}


def _distance_to_similarity(distance: float | None) -> float | None:
    """Map a cosine distance to ``1 / (1 + distance)``, passing None through."""
    if distance is None:
        return None
    return 1.0 / (1.0 + distance)


@dataclass(frozen=True, slots=True)
class _RetrievalPasses:
    """The ranked lists and vector signals from running every spec's search.

    A chunk missing from ``vector_distance_by_chunk`` was found by keyword
    search alone.
    """

    ranked_lists: list[list[ChunkHit]]
    best_vector_distance: float | None
    vector_distance_by_chunk: dict[int, float]
    has_keyword_hit: bool


class Retriever:
    """Hybrid retriever: searches each spec with its own filters, fuses with RRF.

    Documents rank by their best chunk's fused score; the top
    ``SEARCH_TOP_K`` are kept, each capped at ``SEARCH_MAX_CHUNKS_PER_DOC``
    chunks.
    """

    def __init__(
        self,
        settings: Settings,
        store_reader: StoreReader,
        embedding_client: EmbeddingClient,
    ) -> None:
        self._settings = settings
        self._store_reader = store_reader
        self._embedding_client = embedding_client

    def _embed_queries(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts*, returning ``[]`` on any embedding failure.

        A search must not 500 because the embedding backend is down; it just
        gets no vector results.
        """
        try:
            return self._embedding_client.embed(texts)
        except EMBEDDING_FAILURE_EXCEPTIONS as exc:
            log.warning(
                "retriever.embedding_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                query_count=len(texts),
            )
            return []

    def retrieve(
        self,
        specs: tuple[RetrievalSpec, ...],
    ) -> tuple[list[RetrievedChunk], RetrievalSignal]:
        """Search every spec, fuse, and return the top chunks by fused score.

        The :class:`~search.models.RetrievalSignal` keeps the pre-fusion quality
        signals that RRF discards. The spec count is already bounded by
        ``SEARCH_PLANNER_MAX_SPECS``.
        """
        passes = self._run_passes(specs)

        best_vector_similarity = _distance_to_similarity(passes.best_vector_distance)
        signal = RetrievalSignal(
            best_vector_similarity=best_vector_similarity,
            has_keyword_hit=passes.has_keyword_hit,
        )

        if not passes.ranked_lists:
            return [], signal

        fused_score, first_hit = _fuse_with_rrf(passes.ranked_lists)
        if not fused_score:
            return [], signal

        top_doc_ids = _top_document_ids(
            fused_score, first_hit, self._settings.SEARCH_TOP_K
        )
        chunks = self._build_capped_chunks(
            fused_score, first_hit, top_doc_ids, passes.vector_distance_by_chunk
        )

        log.debug(
            "retriever.retrieve.complete",
            spec_count=len(specs),
            ranked_lists_count=len(passes.ranked_lists),
            fused_chunks=len(fused_score),
            returned_chunks=len(chunks),
        )
        return chunks, signal

    def _run_passes(self, specs: tuple[RetrievalSpec, ...]) -> _RetrievalPasses:
        """Run each spec's store search; semantic specs share one embedding call."""
        per_spec_k = self._settings.SEARCH_PER_SPEC_K
        ranked_lists: list[list[ChunkHit]] = []
        best_vector_distance: float | None = None
        vector_distance_by_chunk: dict[int, float] = {}

        semantic_specs = [
            spec for spec in specs if spec.mode == "semantic" and spec.semantic
        ]
        embeddings = (
            self._embed_queries([spec.semantic for spec in semantic_specs])  # type: ignore[misc]
            if semantic_specs
            else []
        )
        # On embedding failure embeddings is [], so no vector passes run.
        for spec, embedding in zip(semantic_specs, embeddings):
            hits = self._store_reader.vector_search(embedding, per_spec_k, spec.filters)
            if not hits:
                continue
            ranked_lists.append(hits)
            pass_min = min(hit.score for hit in hits)
            if best_vector_distance is None or pass_min < best_vector_distance:
                best_vector_distance = pass_min
            for hit in hits:
                prior = vector_distance_by_chunk.get(hit.chunk_id)
                if prior is None or hit.score < prior:
                    vector_distance_by_chunk[hit.chunk_id] = hit.score

        has_keyword_hit = False
        for spec in specs:
            if spec.mode != "keyword" or not spec.keywords:
                continue
            hits = self._store_reader.keyword_search(
                list(spec.keywords), per_spec_k, spec.filters
            )
            if hits:
                has_keyword_hit = True
                ranked_lists.append(hits)

        return _RetrievalPasses(
            ranked_lists=ranked_lists,
            best_vector_distance=best_vector_distance,
            vector_distance_by_chunk=vector_distance_by_chunk,
            has_keyword_hit=has_keyword_hit,
        )

    def _build_capped_chunks(
        self,
        fused_score: dict[int, float],
        first_hit: dict[int, ChunkHit],
        top_doc_ids: set[int],
        vector_distance_by_chunk: dict[int, float],
    ) -> list[RetrievedChunk]:
        """Build the chunks of *top_doc_ids*, best first, capped per document."""
        chunks = [
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id=first_hit[chunk_id].document_id,
                text=first_hit[chunk_id].text,
                page_hint=first_hit[chunk_id].page_hint,
                rrf_score=score,
                vector_similarity=_distance_to_similarity(
                    vector_distance_by_chunk.get(chunk_id)
                ),
            )
            for chunk_id, score in fused_score.items()
            if first_hit[chunk_id].document_id in top_doc_ids
        ]
        chunks.sort(key=lambda chunk: chunk.rrf_score, reverse=True)

        # Already sorted best-first, so a running per-doc count keeps the best.
        max_per_doc = self._settings.SEARCH_MAX_CHUNKS_PER_DOC
        kept_per_doc: dict[int, int] = {}
        capped: list[RetrievedChunk] = []
        for chunk in chunks:
            count = kept_per_doc.get(chunk.document_id, 0)
            if count >= max_per_doc:
                continue
            kept_per_doc[chunk.document_id] = count + 1
            capped.append(chunk)
        return capped
