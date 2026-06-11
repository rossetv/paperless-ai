"""Hybrid retriever with Reciprocal Rank Fusion for the search pipeline.

Searches each :class:`~search.models.RetrievalSpec` independently — vector
search for a semantic spec, keyword search for a keyword spec, each with the
spec's own resolved ``SearchFilters`` — then fuses every ranked list across all
specs with Reciprocal Rank Fusion (RRF).  Returns the top-K documents' chunks,
capped per document and ordered by fused score.

Also exposes ``resolve_specs``, which turns a :class:`~search.models.RetrievalPlan`
of free-text guesses into resolved ``RetrievalSpec``s (taxonomy ids + validated
ISO dates), intersecting each with the user's global UI filters.

Allowed deps: store.reader (SearchFilters, StoreReader), store.models (ChunkHit,
    FacetSet, TaxonomyEntry), search.dates (extract_date_range,
    normalise_iso_date), search.models (FilterCandidates, PlannedSpec,
    RetrievalPlan, RetrievalSpec, RetrievedChunk, RetrievalSignal),
    common.config (Settings), common.embeddings (EmbeddingClient,
    EMBEDDING_FAILURE_EXCEPTIONS).
Forbidden: no sqlite3, no FastAPI, no direct openai calls or imports — the
    OpenAI SDK is an implementation detail of common.embeddings.

# rationale: this file exceeds the §3.1 500-line guideline. It hosts two
# closely-related concerns — turning the planner's free-text guesses into
# resolved ``RetrievalSpec``s (``resolve_specs``) and then executing those specs
# (``Retriever``) — that share the taxonomy-matching helpers (``_match_name`` /
# ``_normalise``) and the ``SearchFilters`` shape. Both halves are the read
# side's "turn intent into ranked chunks" step and are imported as one module by
# ``search.core``; splitting now would add a re-export edge (forbidden by the
# project's no-barrel rule) for no reader benefit. The length is docstring-heavy
# (spec cross-references) rather than logic-heavy.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
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

# Reciprocal Rank Fusion smoothing constant (spec §6.2, CODE_GUIDELINES §3.5).
# The canonical value of 60 was established empirically in the original RRF paper
# (Cormack, Clarke, Buettcher 2009) and is the standard default for hybrid search.
_RRF_K = 60


# ---------------------------------------------------------------------------
# Filter resolution
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    """Normalise a string for fuzzy taxonomy matching.

    Applies:
    1. Unicode NFKC normalisation (collapses ligatures, compatibility chars).
    2. Lower-case folding.
    3. Removal of all non-alphanumeric characters (strips punctuation,
       hyphens, spaces, trailing dots, etc.).

    This makes "npower." == "npower" and "Gas-Bill" == "gas bill" == "gasbill".
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


@dataclass(frozen=True, slots=True)
class NameMatch:
    """Outcome of resolving one planner name guess against a taxonomy.

    ``id`` is the resolved taxonomy id, or None when nothing was applied.
    ``method`` records HOW it resolved so the trace can explain it: ``"exact"``,
    ``"normalised"``, ``"loose"`` (whole-word containment), ``"none"`` (no match),
    or ``"ambiguous"`` (more than one loose candidate — dropped, never guessed).
    ``candidates`` carries the competing names only when ``method == "ambiguous"``.
    """

    id: int | None
    method: str
    candidates: tuple[str, ...] = ()


def _tokenise(text: str) -> frozenset[str]:
    """Split *text* into a set of normalised whole-word tokens.

    NFKC + lower-case, then split on any run of non-alphanumerics; empty tokens
    are dropped. ``"Property Deed"`` -> ``{"property", "deed"}``. Used by the
    loose-matching pass so "Deed" matches "Property Deed" but "ID" does not match
    "Video" (no whole token "id").
    """
    folded = unicodedata.normalize("NFKC", text).lower()
    return frozenset(tok for tok in re.split(r"[^a-z0-9]+", folded) if tok)


def _match_name(
    candidate: str,
    entries: Sequence[TaxonomyEntry],
) -> NameMatch:
    """Resolve *candidate* against *entries* (spec §B1).

    Resolution order:
    1. Exact string match on ``entry.name``.
    2. Case- and punctuation-normalised match via ``_normalise``.
    3. Whole-word containment: one token set a (non-empty) subset of the other,
       in either direction. A unique loose hit resolves; multiple loose hits are
       ambiguous and dropped (the candidates are reported); none is a plain
       no-match.

    The resolved id is never a guess — an ambiguous or unmatched candidate yields
    ``id=None`` (spec §6.1).
    """
    # Pass 1: exact match.
    for entry in entries:
        if entry.name == candidate:
            return NameMatch(id=entry.id, method="exact")

    # Pass 2: case- and punctuation-normalised match.
    normalised_candidate = _normalise(candidate)
    for entry in entries:
        if _normalise(entry.name) == normalised_candidate:
            return NameMatch(id=entry.id, method="normalised")

    # Pass 3: whole-word containment (bidirectional token subset).
    candidate_tokens = _tokenise(candidate)
    if candidate_tokens:
        loose = [
            entry
            for entry in entries
            if (entry_tokens := _tokenise(entry.name))
            and (candidate_tokens <= entry_tokens or entry_tokens <= candidate_tokens)
        ]
        if len(loose) == 1:
            return NameMatch(id=loose[0].id, method="loose")
        if len(loose) > 1:
            return NameMatch(
                id=None,
                method="ambiguous",
                candidates=tuple(entry.name for entry in loose),
            )

    return NameMatch(id=None, method="none")


# ---------------------------------------------------------------------------
# Per-spec filter resolution (multi-spec retrieval)
# ---------------------------------------------------------------------------


def _resolve_dates(
    filter_guess: FilterCandidates,
    today: date,
) -> tuple[str | None, str | None]:
    """Resolve a spec's date guesses into a validated ``(date_from, date_to)`` pair.

    Two date sources can appear in a planner guess, and the deterministic one
    is authoritative:

    1. **ISO bounds.**  When the planner supplies ``date_from`` / ``date_to`` as
       ISO strings, each is validated with :func:`normalise_iso_date`.  A valid
       bound is kept; a *malformed* one is dropped to ``None`` — a hallucinated
       date never narrows the search.  If at least one ISO bound validates, that
       pair is returned and no further parsing happens.
    2. **A non-ISO temporal expression.**  When neither field is an ISO date but
       one carries a free-text expression ("April 2025", "last month"), the
       *first non-empty* raw guess is run through the deterministic
       :func:`extract_date_range`, whose ``(from, to)`` is returned.

    When neither path yields anything, ``(None, None)`` means "no date filter",
    which is the correct, widest result.
    """
    iso_from = (
        normalise_iso_date(filter_guess.date_from) if filter_guess.date_from else None
    )
    iso_to = normalise_iso_date(filter_guess.date_to) if filter_guess.date_to else None

    # The planner gave ISO bounds; the malformed ones have already dropped to
    # None above.  These are authoritative — do not re-parse.
    if iso_from or iso_to:
        return iso_from, iso_to

    # No ISO bound validated.  If either raw guess carries a non-ISO temporal
    # expression, the deterministic extractor turns it into a range.
    raw_guess = filter_guess.date_from or filter_guess.date_to
    if raw_guess:
        return extract_date_range(raw_guess, today)

    return None, None


def _intersect(
    spec_filters: SearchFilters,
    ui_filters: SearchFilters | None,
) -> SearchFilters:
    """Intersect a spec's resolved filters with the user's global UI filters.

    The UI filters are a constraint the user explicitly set, so they may only
    *narrow* the search — never widen it.  The intersection rules:

    - **Dates.** ``date_from`` becomes the *later* (lexical max) of the two ISO
      strings, ``date_to`` the *earlier* (lexical min); a ``None`` bound is
      unbounded, so the other side wins.  Both moves shrink the window.
    - **Correspondent / document type.** A UI value AND-narrows and therefore
      overrides the spec's; absent, the spec's resolved value is kept.
    - **Tags.** The order-stable, de-duplicated union of both — a spec tag and a
      UI tag are both required, so both ids are carried.

    When ``ui_filters`` is ``None`` the spec's filters pass through unchanged.
    """
    if ui_filters is None:
        return spec_filters

    date_from = _later_iso(spec_filters.date_from, ui_filters.date_from)
    date_to = _earlier_iso(spec_filters.date_to, ui_filters.date_to)

    # A set UI value wins; otherwise keep the spec's resolved value.
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
) -> tuple[RetrievalSpec, ...]:
    """Resolve every planned spec's free-text guesses into ready-for-store specs.

    For each :class:`~search.models.PlannedSpec` the mode, semantic text,
    keywords, and rationale are carried through verbatim; only the filter guess
    is resolved into a real :class:`~store.models.SearchFilters`:

    - Correspondent, document type, and tag *names* are matched against the live
      taxonomy via :func:`_match_name` (exact, then case/punctuation-normalised);
      a name with no match is dropped, never guessed at an id.
    - Dates are resolved by :func:`_resolve_dates`: validated ISO bounds are
      authoritative, a non-ISO expression is run through the deterministic
      extractor, and a malformed planner date is dropped.
    - The result is then intersected with ``ui_filters`` via :func:`_intersect`:
      the UI is a global constraint the user set, so it narrows the spec and
      never widens it.

    A spec whose guesses resolve to nothing simply yields a ``SearchFilters``
    with those fields ``None`` — that is the correct "no filter" outcome.

    **Deterministic date safety net** (design §5.2): after all specs are
    resolved, if *none* of them carries a date filter AND *query* names an
    explicit time period (as detected by :func:`~search.dates.extract_date_range`),
    one extra ``RetrievalSpec`` is appended.  The extra spec is a copy of the
    first semantic spec (or the first spec when there is no semantic one) with its
    filters augmented by the extracted date range and intersected with
    *ui_filters*.  This preserves the recall floor — the original, date-unbound
    spec remains in the tuple — while guaranteeing that a dated query reaches
    at least one date-scoped search even when the planner is degraded or produced
    a broad fallback plan with no date hints.

    The safety net fires only on the degraded / fallback path; in the normal case
    the planner or the deterministic filter resolution already binds at least one
    spec to a date, so the guard does not trigger and the intentionally-unbound
    recall spec is left untouched.

    Args:
        plan: The planner's structured multi-spec output.
        facets: The live taxonomy from ``StoreReader.list_facets()``.
        ui_filters: The user's explicit global filters, or ``None``.
        today: Reference date for relative temporal expressions (injected for
            deterministic tests).
        query: The raw user query string.  When non-empty it is run through the
            deterministic date extractor after resolution to power the safety
            net.  Defaults to ``""`` (safety net disabled) so callers that do
            not need the safety net — such as the broadened retrieval pass,
            which deliberately drops all date filters — can omit it.

    Returns:
        One :class:`~search.models.RetrievalSpec` per planned spec, in order,
        plus an optional extra safety-net spec when the conditions above hold.
    """
    resolved: list[RetrievalSpec] = []
    for spec in plan.specs:
        resolved.append(_resolve_one_spec(spec, facets, ui_filters, today))

    # Deterministic date safety net: only fires when the query names a period
    # but no resolved spec has a date filter.
    if query and not _any_has_date(resolved):
        date_from, date_to = extract_date_range(query, today)
        if date_from is not None or date_to is not None:
            resolved.append(
                _make_safety_net_spec(resolved, date_from, date_to, ui_filters)
            )

    return tuple(resolved)


def _any_has_date(specs: list[RetrievalSpec]) -> bool:
    """Return True when at least one spec already carries a date filter."""
    return any(
        spec.filters.date_from is not None or spec.filters.date_to is not None
        for spec in specs
    )


def _make_safety_net_spec(
    resolved: list[RetrievalSpec],
    date_from: str | None,
    date_to: str | None,
    ui_filters: SearchFilters | None,
) -> RetrievalSpec:
    """Build the safety-net spec: a date-scoped copy of the most relevant spec.

    Prefers the first ``mode=="semantic"`` spec; falls back to the very first
    spec.  The date range is grafted onto the base spec's already-intersected
    filters (so correspondent/type/tag constraints from the planner are kept),
    then the combined filters are intersected with *ui_filters* once more so the
    UI constraint still wins.

    The ``rationale`` describes the safety net so the trace is honest about why
    the extra spec exists.
    """
    # Prefer the first semantic spec; fall back to the first spec.
    base = next((s for s in resolved if s.mode == "semantic"), resolved[0])

    # Graft the query date range onto the base spec's filters.
    date_scoped_filters = SearchFilters(
        date_from=_later_iso(base.filters.date_from, date_from),
        date_to=_earlier_iso(base.filters.date_to, date_to),
        correspondent_id=base.filters.correspondent_id,
        document_type_id=base.filters.document_type_id,
        tag_ids=base.filters.tag_ids,
    )
    # Apply the UI constraint on top (the UI is authoritative).
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


# ---------------------------------------------------------------------------
# RRF fusion
# ---------------------------------------------------------------------------


def _fuse_with_rrf(
    ranked_lists: list[list[ChunkHit]],
) -> tuple[dict[int, float], dict[int, ChunkHit]]:
    """Apply Reciprocal Rank Fusion across all ranked lists.

    Each chunk's fused score is the sum of ``1 / (_RRF_K + rank)`` over every
    ranked list it appears in, where ``rank`` is 1-based (position 0 in the
    list → rank 1, position 1 → rank 2, …).

    Using 1-based ranks is the standard RRF convention from the original paper
    (Cormack et al., 2009): ``score = Σ 1 / (k + r)``, where r ∈ {1, 2, …}.
    Position 0 therefore contributes ``1 / (60 + 1) = 1/61``.

    Args:
        ranked_lists: Any number of ranked lists; each is ordered best-first.

    Returns:
        A pair of ``{chunk_id: fused_score}`` and ``{chunk_id: ChunkHit}``,
        where the ChunkHit is the one from the first list the chunk appeared
        in.  Two plain dicts replace a mutable accumulator dataclass
        (CODE_GUIDELINES §1.3).
    """
    fused_score: dict[int, float] = {}
    first_hit: dict[int, ChunkHit] = {}

    for ranked_list in ranked_lists:
        for position, hit in enumerate(ranked_list):
            # 1-based rank: position 0 → rank 1.
            rank = position + 1
            contribution = 1.0 / (_RRF_K + rank)
            if hit.chunk_id in fused_score:
                # Accumulate the score; keep the first-seen ChunkHit.
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
    """Return the ids of the *top_k* documents by their best chunk's score.

    A document may contribute several fused chunks; its rank is decided by the
    single highest fused score among them.  The ``top_k`` documents by that
    best score are returned as an id set.

    Args:
        fused_score: ``{chunk_id: fused_score}`` from :func:`_fuse_with_rrf`.
        first_hit: ``{chunk_id: ChunkHit}`` from :func:`_fuse_with_rrf`, used
            to resolve each chunk to its parent document.
        top_k: How many documents to keep.

    Returns:
        The set of the ``top_k`` highest-scoring documents' ids.
    """
    doc_best_score: dict[int, float] = {}
    for chunk_id, score in fused_score.items():
        document_id = first_hit[chunk_id].document_id
        if score > doc_best_score.get(document_id, -1.0):
            doc_best_score[document_id] = score

    ranked_doc_ids = sorted(doc_best_score.items(), key=lambda kv: kv[1], reverse=True)
    return {document_id for document_id, _ in ranked_doc_ids[:top_k]}


def _distance_to_similarity(distance: float | None) -> float | None:
    """Map a cosine distance to a similarity in (0, 1], passing None through.

    ``similarity = 1 / (1 + distance)`` maps [0, ∞) → (0, 1], is monotonically
    decreasing in distance (the closest possible hit, distance 0, gives 1.0),
    and is numerically stable at any finite distance — a consistent scale that
    later calibration can interpret without knowing the absolute distance range.
    """
    if distance is None:
        return None
    return 1.0 / (1.0 + distance)


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _RetrievalPasses:
    """The accumulated results of running every spec's store search.

    An internal carrier between :meth:`Retriever._run_passes` and
    :meth:`Retriever.retrieve` — four related values that would otherwise be a
    positional puzzle as a tuple (CODE_GUIDELINES §5.8).

    Attributes:
        ranked_lists: Every ranked ChunkHit list (vector and keyword) to fuse.
        best_vector_distance: Smallest cosine distance across all vector passes
            (lower = closer), or None when no vector pass returned a hit.
        vector_distance_by_chunk: Per-chunk best (smallest) cosine distance; a
            chunk absent from the map was found by keyword search alone.
        has_keyword_hit: True when any keyword pass returned rows.
    """

    ranked_lists: list[list[ChunkHit]]
    best_vector_distance: float | None
    vector_distance_by_chunk: dict[int, float]
    has_keyword_hit: bool


class Retriever:
    """Hybrid retriever: searches each spec independently, then fuses with RRF.

    Each :class:`~search.models.RetrievalSpec` is searched on its own terms and
    with its own resolved :class:`~store.models.SearchFilters`: a ``semantic``
    spec is embedded and run through ``StoreReader.vector_search``; a ``keyword``
    spec is run through ``StoreReader.keyword_search``.  Every semantic spec's
    text is embedded in a single batch call, so multiple specs cost one
    embedding round-trip.  All resulting ranked lists — across every spec — are
    fused with Reciprocal Rank Fusion, so a document a spec found independently
    and a document several specs agree on are ranked on the same scale.

    Chunks are grouped by document; each document's rank is its best chunk's
    fused score.  The top ``settings.SEARCH_TOP_K`` documents are returned, with
    each document capped at ``settings.SEARCH_MAX_CHUNKS_PER_DOC`` of its
    highest-scoring chunks, and the whole list sorted by fused score (highest
    first).

    Args:
        settings: Application settings; ``SEARCH_TOP_K``, ``SEARCH_PER_SPEC_K``,
            and ``SEARCH_MAX_CHUNKS_PER_DOC`` are used.
        store_reader: The read-side store interface.
        embedding_client: The embedding client for query vectorisation.
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
        """Embed *texts*, degrading to an empty result on any embedding failure.

        ``EmbeddingClient.embed`` can fail two ways — a non-retryable error (a
        bad/expired key, a 400) or a retryable one (an embedding-endpoint
        outage, sustained rate limiting) that exhausted its own retries.  Both
        are named by ``EMBEDDING_FAILURE_EXCEPTIONS``.  A search must not 500
        because the embedding backend is down: this catches that tuple, logs a
        warning, and returns ``[]`` so the query simply contributes no
        vector-search results — retrieval then falls through to its existing
        empty path (finding C3).

        Args:
            texts: The semantic queries and sub-questions to embed.

        Returns:
            One vector per input, or ``[]`` when embedding failed entirely.
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
        """Search every spec independently, fuse across specs, return top-K chunks.

        Each semantic spec's text is collected and embedded in a single batch
        call (one round-trip), then each embedding is searched with *its own*
        spec's ``filters`` at ``SEARCH_PER_SPEC_K`` candidates.  Each keyword
        spec is searched likewise.  The fan-out is bounded upstream by
        ``SEARCH_PLANNER_MAX_SPECS``, so no extra cap is needed here.

        Every ranked list — vector and keyword, across all specs — is fused with
        RRF.  Fused chunks are grouped by document; each document ranks by its
        best chunk's fused score.  The top ``SEARCH_TOP_K`` documents are kept,
        each capped at ``SEARCH_MAX_CHUNKS_PER_DOC`` of its highest-scoring
        chunks, and the result is sorted by fused score descending.

        A :class:`~search.models.RetrievalSignal` is returned alongside the
        chunks: ``best_vector_similarity`` is the closest distance across all
        vector passes (None when no vector pass returned a hit) and
        ``has_keyword_hit`` is True when any keyword pass returned rows.

        Args:
            specs: The resolved retrieval specs (from ``resolve_specs``).

        Returns:
            A 2-tuple ``(chunks, signal)`` — *chunks* sorted by rrf_score
            descending (empty when nothing was found), *signal* capturing
            pre-fusion quality.
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
        """Run each spec's store search and collect the ranked lists and signals.

        Semantic specs are embedded together in one batch and each embedding is
        searched with its own spec's filters; keyword specs are searched
        directly.  Returns the accumulated ranked lists plus the absolute
        vector signals RRF discards.
        """
        per_spec_k = self._settings.SEARCH_PER_SPEC_K
        ranked_lists: list[list[ChunkHit]] = []
        best_vector_distance: float | None = None
        # Per-chunk best (smallest) cosine distance across all vector passes.  A
        # chunk absent from this map was found by keyword search alone, so its
        # vector_similarity is None.
        vector_distance_by_chunk: dict[int, float] = {}

        semantic_specs = [
            spec for spec in specs if spec.mode == "semantic" and spec.semantic
        ]
        embeddings = (
            self._embed_queries([spec.semantic for spec in semantic_specs])  # type: ignore[misc]
            if semantic_specs
            else []
        )
        # _embed_queries returns [] on failure; zip then yields nothing, so a
        # dead embedding backend simply contributes no vector passes.
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
        """Build the output chunks, capping each document at the per-doc ceiling.

        Keeps only chunks whose document is in *top_doc_ids*, retains each
        document's ``SEARCH_MAX_CHUNKS_PER_DOC`` highest-scoring chunks, and
        sorts the whole result by fused score descending.
        """
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

        # Cap per document, keeping the highest-scoring chunks (the list is
        # already sorted descending, so a running per-doc count suffices).
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
