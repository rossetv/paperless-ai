"""The Settings shape and the builder that validates a mapping into it.

:class:`Settings` is the single, immutable description of a process's
configuration (CODE_GUIDELINES §5.2): frozen, so no code path mutates it
mid-run. This module owns the :class:`Settings` dataclass, the
provider-dependent defaults, and :func:`_build_settings`, which composes the
pure parsers in :mod:`._parsers` into a validated, clamped :class:`Settings`.

The DB-backed production entry points (:func:`load_settings`,
:func:`current_settings`) live in :mod:`._loader`; they layer the ``app.db``
config table over the environment, then call :func:`_build_settings` here.
:meth:`Settings.from_environment` is the environment-only path, preserved for
tests and any caller with no ``app.db``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import structlog

from ..constants import REFUSAL_PHRASES
from ._catalogue import SECRET_KEYS
from ._parsers import (
    _DEFAULT_OLLAMA_BASE_URL,
    _get_bool_env,
    _get_csv_env,
    _get_float_env,
    _get_int_env,
    _get_optional_int_env,
    _get_optional_positive_int_env,
    _get_required_env,
    _require_at_least_one,
    _resolve_chunk_overlap,
    _resolve_classify_reasoning_effort,
    _resolve_embedding_provider,
    _resolve_llm_provider,
    _resolve_log_format,
    _resolve_ocr_image_detail,
    _resolve_ocr_reasoning_effort,
    _resolve_pricing_refresh_url,
    _resolve_relevance_tiers,
    _resolve_search_max_refinements,
    _resolve_search_reasoning_effort,
    _resolve_server_port,
    _resolve_step_provider,
)

log = structlog.get_logger(__name__)

# One-shot deprecation guard: emit the AI_MODELS warning at most once per
# process lifetime so the hot-load loop (which rebuilds Settings on every
# config_version bump) does not spam the log. Module-level state is reset
# between test runs because each test session re-imports the module, but that
# is the intended behaviour — the flag prevents spam within a single run, not
# across test isolation boundaries.
_ai_models_deprecation_warned: bool = False

# Default store path used by the indexer and search server.
_DEFAULT_INDEX_DB_PATH = "/data/index.db"
# Default application-database path. app.db holds accounts, sessions, and
# (from later waves) config; it is separate from index.db so rebuilding the
# search index never destroys accounts.
_DEFAULT_APP_DB_PATH = "/data/app.db"

# Default URLs used when environment variables are not set.
_DEFAULT_PAPERLESS_URL = "http://paperless:8000"

# The marker text written into a document's content when every vision model
# refuses to transcribe it. A fixed constant, not configurable.
_REFUSAL_MARK = "CHATGPT REFUSED TO TRANSCRIBE"


@dataclass(frozen=True, slots=True)
class _ProviderDefaults:
    """The per-step model defaults for one provider.

    Resolved per step in :func:`_default_models_for` so each step's model
    default follows *its own* provider (not one global provider) — the change
    that makes provider selection independent per step. The Ollama base URL is
    no longer carried here: it is a single shared connection resolved once in
    :func:`_build_settings` from the union of the step providers.
    """

    ocr_models: list[str]
    classify_models: list[str]
    planner_model: str
    answer_model: str
    judge_model: str


def _default_models_for(provider: Literal["openai", "ollama"]) -> _ProviderDefaults:
    """Return the model defaults for a step whose provider is *provider*.

    Under ``ollama`` the defaults are the local Gemma set; under ``openai`` the
    GPT set. These are only *defaults* — an explicit ``OCR_MODELS`` /
    ``CLASSIFY_MODELS`` / ``SEARCH_*_MODEL`` value in *source* still wins in
    :func:`_build_settings`. Fresh lists are built per call so no two
    ``Settings`` instances share a mutable default list.
    """
    if provider == "ollama":
        return _ProviderDefaults(
            ocr_models=["gemma3:27b", "gemma3:12b"],
            classify_models=["gemma3:27b", "gemma3:12b"],
            planner_model="gemma3:12b",
            answer_model="gemma3:27b",
            judge_model="gemma3:12b",
        )
    return _ProviderDefaults(
        ocr_models=["gpt-5.4-mini", "gpt-5.4", "gpt-5.5"],
        classify_models=["gpt-5.4-mini", "gpt-5.4", "gpt-5.5"],
        planner_model="gpt-5.4-mini",
        answer_model="gpt-5.5",
        judge_model="gpt-5.4-mini",
    )


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable, fully-validated configuration for one process.

    Built once via :meth:`from_environment` or :func:`load_settings`; never
    mutated thereafter. Every field is set in a single constructor call, so
    the type checker and the reader both see the complete shape in one place.
    """

    PAPERLESS_URL: str
    # Browser-facing base URL for Paperless-ngx document deep-links. Distinct
    # from PAPERLESS_URL: the API may be reached over an internal address
    # (e.g. http://paperless:8000) that the user's browser cannot resolve,
    # while links rendered in the search UI need a public hostname.
    PAPERLESS_PUBLIC_URL: str
    PAPERLESS_TOKEN: str

    LLM_PROVIDER: Literal["openai", "ollama"]
    OLLAMA_BASE_URL: str | None
    # OPENAI_API_KEY is required whenever OpenAI is used by EITHER the LLM
    # provider OR the embedding provider; it may be empty only on a fully-local
    # deployment where both are ollama (CODE_GUIDELINES §10.8, §15.4). Kept a
    # plain ``str`` (never optional) — an unused fully-local deployment carries
    # ``""`` rather than ``None``, so no call site grows a None-guard.
    OPENAI_API_KEY: str

    # Per-step chat/vision provider. Each defaults to LLM_PROVIDER (the judge to
    # the planner) so a deployment that set only LLM_PROVIDER is unchanged; set
    # one explicitly to run that step on a different provider. The shared chat
    # client registry (common.llm) routes each step to its provider's client.
    OCR_PROVIDER: Literal["openai", "ollama"]
    CLASSIFY_PROVIDER: Literal["openai", "ollama"]
    SEARCH_PLANNER_PROVIDER: Literal["openai", "ollama"]
    SEARCH_JUDGE_PROVIDER: Literal["openai", "ollama"]
    SEARCH_ANSWER_PROVIDER: Literal["openai", "ollama"]

    OCR_MODELS: list[str]
    CLASSIFY_MODELS: list[str]
    OCR_REFUSAL_MARKERS: list[str]
    OCR_INCLUDE_PAGE_MODELS: bool

    PRE_TAG_ID: int
    POST_TAG_ID: int
    OCR_PROCESSING_TAG_ID: int | None

    CLASSIFY_PRE_TAG_ID: int
    CLASSIFY_POST_TAG_ID: int | None
    CLASSIFY_PROCESSING_TAG_ID: int | None
    ERROR_TAG_ID: int | None

    POLL_INTERVAL: int
    MAX_RETRIES: int
    MAX_RETRY_BACKOFF_SECONDS: int
    REQUEST_TIMEOUT: int
    LLM_MAX_CONCURRENT: int

    STALE_LOCK_RECOVERY: bool
    """Run the startup stale-lock sweep that re-queues orphaned documents.

    When ``True`` (the default), each tag daemon sweeps documents still carrying
    its processing-lock tag on startup and re-queues them — the crash-recovery
    net for a daemon that died mid-document (CODE_GUIDELINES §1.12). The sweep is
    unconditional (no age or owner check), so it is **unsafe with multiple
    replicas sharing one processing tag**: a restarting replica would steal a
    peer's live lock and re-spend LLM tokens on every rolling restart. Set
    ``False`` on a multi-replica deployment to disable the sweep; single-instance
    deployments leave it on to keep crash recovery.
    """

    OCR_DPI: int
    OCR_MAX_SIDE: int
    OCR_IMAGE_DETAIL: Literal["low", "high", "auto"]
    OCR_REASONING_EFFORT: Literal["minimal", "low", "medium", "high"]
    PAGE_WORKERS: int
    DOCUMENT_WORKERS: int

    LOG_LEVEL: str
    LOG_FORMAT: Literal["json", "console"]

    REFUSAL_MARK: str

    CLASSIFY_PERSON_FIELD_ID: int | None
    CLASSIFY_DEFAULT_COUNTRY_TAG: str
    CLASSIFY_MAX_CHARS: int
    CLASSIFY_MAX_TOKENS: int
    CLASSIFY_TAG_LIMIT: int
    CLASSIFY_TAXONOMY_LIMIT: int
    CLASSIFY_MAX_PAGES: int
    CLASSIFY_TAIL_PAGES: int
    CLASSIFY_HEADERLESS_CHAR_LIMIT: int
    CLASSIFY_REASONING_EFFORT: str

    # Indexer / store settings (semantic-search spec §10)
    INDEX_DB_PATH: str
    # Application-database path (web-redesign spec §4.1) — accounts/sessions.
    APP_DB_PATH: str
    EMBEDDING_PROVIDER: Literal["openai", "ollama"]
    """Provider that vectorises document chunks: ``openai`` or ``ollama``.

    Defaults to the value of ``LLM_PROVIDER`` so a fully-local
    ``LLM_PROVIDER=ollama`` deployment also embeds locally (no chunk leaves the
    box), while the default ``LLM_PROVIDER=openai`` deployment keeps OpenAI
    embeddings byte-for-byte unchanged. Set it explicitly to split the two (e.g.
    local chat with OpenAI embeddings). Under ``ollama`` the embedding client
    talks to ``OLLAMA_BASE_URL`` with a placeholder key (Ollama ignores it) and
    ``EMBEDDING_MODEL`` must name a local embedding model with a matching
    ``EMBEDDING_DIMENSIONS``. Switching this value forces a full re-embed
    (it is in ``REINDEX_KEYS``), because the stored vectors are model- and
    provider-specific and cannot be compared across providers.
    """
    EMBEDDING_MODEL: str
    EMBEDDING_DIMENSIONS: int
    EMBEDDING_MAX_CONCURRENT: int
    RECONCILE_INTERVAL: int
    DELETION_SWEEP_INTERVAL: int
    CHUNK_SIZE: int
    CHUNK_OVERLAP: int

    # Search-server settings (semantic-search spec §10)
    SEARCH_TOP_K: int
    SEARCH_MAX_REFINEMENTS: int
    SEARCH_PLANNER_MODEL: str
    SEARCH_ANSWER_MODEL: str
    SEARCH_SERVER_HOST: str
    SEARCH_SERVER_PORT: int
    SEARCH_FORWARDED_ALLOW_IPS: str
    SEARCH_SESSION_TTL: int
    SEARCH_MAX_CONCURRENT: int

    SEARCH_KEY_DAILY_TOKEN_QUOTA: int
    """Per-API-key daily LLM token quota — a cumulative spend cap on search.

    The per-query LLM budget and :attr:`SEARCH_MAX_CONCURRENT` bound a single
    query and simultaneous queries; neither bounds *cumulative* spend, so a
    leaked low-privilege API key can run up arbitrary cost with unbounded
    sequential queries. This caps the total LLM tokens one API key may consume
    on the search endpoints (``/api/search``, ``/api/search/stream``, and the
    MCP ``ask_documents`` / ``search_documents`` tools) per UTC calendar day.

    ``0`` (the default) means **unlimited** — the quota is disabled and the
    search path performs zero quota-related database I/O, so a deployment that
    has not opted in is wholly unaffected. A positive value enables the cap:
    an API-key caller whose tokens-used-today has reached the quota is rejected
    (HTTP 429 on REST, an error on MCP) before the pipeline runs, and a
    completed query's total tokens are recorded against the key's daily bucket.

    Cookie/browser callers are never limited — the cap targets programmatic
    keys, the credentials a leak exposes. It is a **soft** cap: usage is
    recorded after each query, so concurrent queries can each pass the check
    and slightly overshoot before the bucket updates. Floored at ``≥ 0``;
    negative values clamp to ``0`` (disabled).
    """

    # Search/RAG token-cost settings (token-cost programme Area 3)
    SEARCH_PLANNER_REASONING_EFFORT: str
    SEARCH_ANSWER_REASONING_EFFORT: str
    SEARCH_CACHE_TTL_SECONDS: int
    SEARCH_SKIP_PLANNER_FOR_TRIVIAL: bool

    SEARCH_GATE_JUDGE: bool
    """Enable the document-relevance judge (Layer 3, a cheap pre-synthesis call).

    When ``True`` (the default), a cheap ``SEARCH_JUDGE_MODEL`` call screens the
    retrieved documents before the expensive answer model: it bails to
    ``no_match`` when nothing is relevant, otherwise filters the chunk set to the
    relevant documents. Recall-biased and fail-open — any judge failure proceeds
    to synthesis over all chunks. Set ``False`` to restore the pre-judge path.
    """
    SEARCH_JUDGE_RATIONALES: bool
    """Instruct the relevance judge to write a one-line reason per document.

    When ``True`` (the default), each document verdict carries a short
    justification (``≤ 200`` characters) from the judge — visible in the live
    trace UI. The rationale adds a few extra tokens per query but provides
    transparency about why a document was kept or dropped. Set ``False`` to
    suppress rationales (the ``reason`` field will be an empty string) and save
    those tokens.
    """
    SEARCH_JUDGE_MODEL: str
    """The model for the relevance judge. Defaults to the planner model for the
    provider (``gpt-5.4-mini`` / ``gemma3:12b``); set independently to run the
    judge on a cheaper or sharper model than the planner."""
    SEARCH_JUDGE_REASONING_EFFORT: str
    """Reasoning effort for the judge (``minimal``/``low``/``medium``/``high``).
    Defaults to ``low`` — a coarse on-topic classification that does not need
    deep reasoning; raise it if the judge bails or filters too aggressively."""
    # Fail-fast gate knobs (search fail-fast spec §3)
    SEARCH_GATE_ADEQUACY: bool
    """Enable the query-adequacy gate (Layer 1, folded into the planner call).

    When ``True`` (the default), a planner response signalling an inadequate
    query is returned as a clarify outcome before retrieval and synthesis.
    Set to ``False`` to restore today's unconditional-plan behaviour, e.g.
    during incident response when the adequacy prompt has regressed.
    """
    SEARCH_GATE_RELEVANCE: bool
    """Enable the post-retrieval relevance gate (Layer 2, absolute similarity).

    When ``True`` (the default), retrieval results whose best vector similarity
    falls below ``SEARCH_RELEVANCE_MIN_SIMILARITY`` *and* that have no keyword
    hit are returned as a no-match outcome, skipping synthesis. Set to ``False``
    to bypass the gate (fail-open) while the similarity floor is being tuned.
    """
    SEARCH_RELEVANCE_MIN_SIMILARITY: float
    """Minimum absolute vector similarity required to proceed to synthesis.

    similarity = ``1 / (1 + best_cosine_distance)`` — higher is closer. The
    default ``0.60`` sits between off-topic noise and real matches on the
    ``text-embedding-3-large`` index: off-topic / unanswerable queries score
    ~0.54–0.58 (e.g. "popcorn recipe" in a personal-document library), while
    genuine matches score ~0.65+. A 0.60 floor rejects the former (fail fast →
    "no matches") without touching the latter. Lower it toward recall-first if
    too much is being rejected; raise it to bite harder. This is the *gate*
    cut-off only — it is independent of the relevance-badge tier cut-points in
    :mod:`search.relevance`, which stay calibrated so a shown result still
    badges by its own similarity. Floored at ``≥ 0.0``; negative values are
    clamped to ``0.0``.
    """
    SEARCH_RELEVANCE_TIER_STRONG: float
    """Minimum absolute vector similarity for the "strong match" badge.

    The relevance badge buckets a shown result by its best vector similarity
    into one of four tiers: a similarity ``≥`` this value badges "strong",
    ``≥ SEARCH_RELEVANCE_TIER_GOOD`` badges "good", ``≥
    SEARCH_RELEVANCE_TIER_PARTIAL`` badges "partial", and anything lower badges
    "weak". The defaults (0.70 / 0.66 / 0.60) are calibrated against the
    ``text-embedding-3-large`` @ 3072-dim index. These cut-points are the
    *badge* thresholds — deliberately independent of
    ``SEARCH_RELEVANCE_MIN_SIMILARITY`` (the gate floor that decides what is
    *shown*): the badge describes how good a shown result is. Validated as
    ``0 ≤ partial ≤ good ≤ strong ≤ 1`` at config-build time; a violating value
    is rejected naming the offending key.
    """
    SEARCH_RELEVANCE_TIER_GOOD: float
    """Minimum absolute vector similarity for the "good match" badge.

    See :attr:`SEARCH_RELEVANCE_TIER_STRONG`. Default ``0.66``. Must satisfy
    ``SEARCH_RELEVANCE_TIER_PARTIAL ≤ this ≤ SEARCH_RELEVANCE_TIER_STRONG``.
    """
    SEARCH_RELEVANCE_TIER_PARTIAL: float
    """Minimum absolute vector similarity for the "partial match" badge.

    See :attr:`SEARCH_RELEVANCE_TIER_STRONG`. Default ``0.60``. A shown result
    below this similarity badges "weak". Must satisfy ``0 ≤ this ≤
    SEARCH_RELEVANCE_TIER_GOOD``.
    """
    SEARCH_MIN_QUERY_CHARS: int
    """Minimum number of non-whitespace characters for a search query (Layer 0).

    Queries shorter than this floor are rejected before any LLM call. The
    default of ``2`` catches blank, single-character, and whitespace-only
    inputs without being so strict that it blocks legitimate short queries.
    Floored at ``≥ 0``; negative values are clamped to ``0``.
    """

    SEARCH_IDENTITY_AWARE: bool
    """Resolve the asker's account display name into the planner + answer prompts.

    When ``True`` (the default), a logged-in user's ``display_name`` is sanitised
    and passed as an ``asker`` so the planner resolves first-person queries
    ("my passport" -> the asker) and the answer model addresses them as "you".
    The cache key includes the asker, so personalised answers never leak across
    users. Set ``False`` to disable — prompts and cache key become identical to
    the pre-identity behaviour. Inert until an account has a display name.
    """

    # Multi-spec retrieval settings (multi-spec retrieval overhaul Phase 1)
    SEARCH_PLANNER_MAX_SPECS: int
    """Cap on the number of :class:`~search.models.PlannedSpec`\\s per plan.

    The planner is instructed to emit at most this many specs. A value of 1
    degrades to the legacy single-spec path. Clamped to >= 1.
    Default ``8``.
    """
    SEARCH_PLANNER_TAXONOMY_LIMIT: int
    """Max names per taxonomy list fed to the planner prompt.

    Correspondents, document types, and tags are listed (alphabetically) in the
    planner's cacheable prefix so it picks real names instead of guessing. A
    value of ``<= 0`` means no cap. Default ``100``.
    """
    SEARCH_PER_SPEC_K: int
    """Candidate chunks pulled from the store per :class:`~search.models.RetrievalSpec`.

    When unset, defaults to the resolved :attr:`SEARCH_TOP_K` value so the
    total candidate budget per query is unchanged in the single-spec case.
    Clamped to >= 1.
    """
    SEARCH_MAX_CHUNKS_PER_DOC: int
    """Maximum chunks per document admitted to the synthesiser after the chunk-union step.

    After merging chunks from all specs, each document is capped at this many
    chunks before synthesis. Prevents a single large document from dominating
    the context window. Clamped to >= 1. Default ``3``.
    """

    # Model-price book settings (refreshable, locally-cached pricing)
    PRICING_REFRESH_URL: str
    """Operator-provided URL serving the model-price refresh JSON, or ``""`` to disable.

    There is **no official OpenAI pricing API** (``/v1/models`` returns models,
    not prices), so live prices cannot be fetched from OpenAI. When this is set
    to an absolute ``http``/``https`` URL, the price book periodically fetches it
    — a self-hosted or community-maintained price list the operator trusts — and
    caches the result in ``app.db`` (surviving restarts), falling back to the
    bundled seed on any fetch/validation failure. The expected JSON schema is
    ``{"as_of": "YYYY-MM-DD", "currency": "USD", "models": {"<model>":
    {"input_per_mtok": <num>, "output_per_mtok": <num>}}}``.

    Empty (the default, and prod's config) **disables refresh entirely**: the
    price book equals the bundled seed exactly, produces identical dollar
    figures, and makes zero network calls. Validated as empty-or-absolute-URL at
    config-build time; a bare path or bad scheme is rejected naming the key.
    """
    PRICING_REFRESH_INTERVAL_HOURS: int
    """How often to refresh the price book from ``PRICING_REFRESH_URL``, in hours.

    Inert when ``PRICING_REFRESH_URL`` is empty (no refresh runs at all). When a
    URL is set, the background refresh task re-fetches at most this often.
    Clamped to ``>= 1`` so a typo (``0`` or negative) cannot turn the refresh
    into a hot loop hammering the price-list host. Default ``24``.
    """

    @classmethod
    def from_environment(cls) -> Settings:
        """Build a :class:`Settings` from the process environment alone.

        The environment-only path, preserved for tests and for any caller
        that has no ``app.db``. Production processes use :func:`load_settings`
        instead, which layers the ``config`` table over the environment.

        Raises:
            ValueError: A required variable is unset, or a value fails
                validation. The message names the offending variable.
        """
        return _build_settings(os.environ)

    def __repr__(self) -> str:
        """Return a repr with every secret value masked.

        The default dataclass repr serialises every field, so dropping a
        Settings into a log line (``log.info("startup", settings=settings)``)
        would leak ``OPENAI_API_KEY`` and ``PAPERLESS_TOKEN`` — never log a
        secret (CODE_GUIDELINES §7.4, §10). The mask is the same sentinel the
        Settings API uses, so the two surfaces present the same redaction.
        """
        parts = []
        for field_name in self.__dataclass_fields__:  # type: ignore[attr-defined]
            value = getattr(self, field_name)
            if field_name in SECRET_KEYS and value:
                value_repr = "'********'"
            else:
                value_repr = repr(value)
            parts.append(f"{field_name}={value_repr}")
        return f"Settings({', '.join(parts)})"

    __str__ = __repr__


def build_settings(source: Mapping[str, str]) -> Settings:
    """Build a validated :class:`Settings` from a string mapping.

    The public validation entry point: callers outside :mod:`common.config`
    (the Settings route layer, the test-connection probe) use this to run the
    same parsing/validation the daemon startup path uses on a candidate
    configuration mapping. The underscore-prefixed :func:`_build_settings` is
    preserved as a thin private alias for in-module call sites.
    """
    return _build_settings(source)


def _build_settings(source: Mapping[str, str]) -> Settings:
    """Build a validated :class:`Settings` from a string mapping.

    *source* is the merged configuration: for :func:`load_settings` it is the
    ``config`` table layered over the process environment; for
    :meth:`Settings.from_environment` it is ``os.environ`` alone. Parsing,
    validation and clamping are identical either way — only the source of the
    raw strings differs.

    Raises:
        ValueError: A required key is missing, or a value fails validation.
            The message names the offending key.

    rationale: this function exceeds the 60-line body ceiling because it is an
    irreducibly flat enumeration of every configuration key — one keyword per
    setting. Splitting it would only scatter that single list across helpers
    without lowering the real complexity (CODE_GUIDELINES §3.1).
    """
    # Resolved first: these drive the provider-dependent defaults below.
    llm_provider = _resolve_llm_provider(source)
    # EMBEDDING_PROVIDER defaults to LLM_PROVIDER (privacy fix: ollama chat ⇒
    # ollama embeddings), overridable explicitly. Resolved here because it
    # drives the OPENAI_API_KEY requirement below.
    embedding_provider = _resolve_embedding_provider(source)
    post_tag_id = _get_int_env(source, "POST_TAG_ID", 444)
    chunk_size = _require_at_least_one(
        "CHUNK_SIZE", _get_int_env(source, "CHUNK_SIZE", 2000)
    )
    # Resolved early so SEARCH_PER_SPEC_K can default to it when unset.
    search_top_k = _require_at_least_one(
        "SEARCH_TOP_K", _get_int_env(source, "SEARCH_TOP_K", 10)
    )

    # Per-step chat/vision providers. Each seeds from LLM_PROVIDER (the judge
    # from the planner) so a deployment that set only LLM_PROVIDER is unchanged;
    # each step's model default then follows its own provider.
    ocr_provider = _resolve_step_provider(source, "OCR_PROVIDER", llm_provider)
    classify_provider = _resolve_step_provider(
        source, "CLASSIFY_PROVIDER", llm_provider
    )
    planner_provider = _resolve_step_provider(
        source, "SEARCH_PLANNER_PROVIDER", llm_provider
    )
    judge_provider = _resolve_step_provider(
        source, "SEARCH_JUDGE_PROVIDER", planner_provider
    )
    answer_provider = _resolve_step_provider(
        source, "SEARCH_ANSWER_PROVIDER", llm_provider
    )

    # OLLAMA_BASE_URL is one shared connection. Resolve it whenever ANY step
    # (chat or embedding) uses Ollama: the configured value, else the local
    # default. An all-OpenAI deployment keeps it None (unchanged behaviour).
    any_ollama = "ollama" in (
        ocr_provider,
        classify_provider,
        planner_provider,
        judge_provider,
        answer_provider,
        embedding_provider,
    )
    ollama_base_url = (
        (source.get("OLLAMA_BASE_URL") or _DEFAULT_OLLAMA_BASE_URL)
        if any_ollama
        else None
    )

    default_ocr_models = _default_models_for(ocr_provider).ocr_models
    default_classify_models = _default_models_for(classify_provider).classify_models
    default_planner_model = _default_models_for(planner_provider).planner_model
    default_answer_model = _default_models_for(answer_provider).answer_model
    default_judge_model = _default_models_for(judge_provider).judge_model

    # Back-compat shim: AI_MODELS is the legacy key. If neither OCR_MODELS nor
    # CLASSIFY_MODELS is set but AI_MODELS is, use its value as the default for
    # both. Precedence: explicit new key > AI_MODELS legacy > provider default.
    legacy_models = _get_csv_env(source, "AI_MODELS", [], require_non_empty=False)

    # One-shot deprecation warning: fire at most once per process lifetime when
    # AI_MODELS is actually being used as a fallback for at least one of the new
    # keys.  The flag prevents the hot-load loop from spamming the log on every
    # config_version bump.
    global _ai_models_deprecation_warned
    if legacy_models and not _ai_models_deprecation_warned:
        _missing_new_keys = [
            k
            for k in ("OCR_MODELS", "CLASSIFY_MODELS")
            if not source.get(k, "").strip()
        ]
        if _missing_new_keys:
            _ai_models_deprecation_warned = True
            log.warning(
                "common.config.ai_models_deprecated",
                message=(
                    "AI_MODELS is deprecated; migrate to OCR_MODELS / CLASSIFY_MODELS. "
                    "AI_MODELS is still honoured as a fallback but will be removed in a "
                    "future release."
                ),
                missing_keys=_missing_new_keys,
            )

    # CLASSIFY_PRE_TAG_ID defaults to POST_TAG_ID (an int). _get_int_env has an
    # int default and treats blank as unset, so it returns a plain int — no
    # int | None union to narrow away with an assert (COMMON-16, §17.2).
    classify_pre_tag_id = _get_int_env(source, "CLASSIFY_PRE_TAG_ID", post_tag_id)

    # PAPERLESS_URL is the API base (often an internal address);
    # PAPERLESS_PUBLIC_URL is the browser-facing base for document
    # deep-links and falls back to PAPERLESS_URL when unset, so existing
    # single-URL deployments are unaffected. Both are stored stripped of
    # any trailing slash so callers can append paths cleanly.
    paperless_url = source.get("PAPERLESS_URL", _DEFAULT_PAPERLESS_URL).rstrip("/")
    paperless_public_url = source.get("PAPERLESS_PUBLIC_URL", paperless_url).rstrip("/")

    # The three relevance-badge cut-points are validated together (range and
    # ordering) so a misconfigured tier fails closed at config-build time.
    tier_strong, tier_good, tier_partial = _resolve_relevance_tiers(source)

    return Settings(
        PAPERLESS_URL=paperless_url,
        PAPERLESS_PUBLIC_URL=paperless_public_url,
        PAPERLESS_TOKEN=_get_required_env(source, "PAPERLESS_TOKEN"),
        LLM_PROVIDER=llm_provider,
        OLLAMA_BASE_URL=ollama_base_url,
        # Required whenever OpenAI is actually used by ANY step — the five
        # chat/vision steps OR the embedding provider. A fully-local deployment
        # (every step ollama) may omit it, so it defaults to "" there; every
        # other config (any step on openai) keeps the required behaviour and
        # fails closed at config-build time if the key is absent (§10.8, §1.11).
        OPENAI_API_KEY=(
            _get_required_env(source, "OPENAI_API_KEY")
            if "openai"
            in (
                ocr_provider,
                classify_provider,
                planner_provider,
                judge_provider,
                answer_provider,
                embedding_provider,
            )
            else source.get("OPENAI_API_KEY", "").strip()
        ),
        OCR_PROVIDER=ocr_provider,
        CLASSIFY_PROVIDER=classify_provider,
        SEARCH_PLANNER_PROVIDER=planner_provider,
        SEARCH_JUDGE_PROVIDER=judge_provider,
        SEARCH_ANSWER_PROVIDER=answer_provider,
        OCR_MODELS=_get_csv_env(
            source,
            "OCR_MODELS",
            legacy_models or default_ocr_models,
            require_non_empty=True,
        ),
        CLASSIFY_MODELS=_get_csv_env(
            source,
            "CLASSIFY_MODELS",
            legacy_models or default_classify_models,
            require_non_empty=True,
        ),
        OCR_REFUSAL_MARKERS=[
            marker.lower()
            for marker in _get_csv_env(
                source,
                "OCR_REFUSAL_MARKERS",
                [*REFUSAL_PHRASES, _REFUSAL_MARK],
            )
        ],
        OCR_INCLUDE_PAGE_MODELS=_get_bool_env(source, "OCR_INCLUDE_PAGE_MODELS", False),
        PRE_TAG_ID=_get_int_env(source, "PRE_TAG_ID", 443),
        POST_TAG_ID=post_tag_id,
        OCR_PROCESSING_TAG_ID=_get_optional_positive_int_env(
            source, "OCR_PROCESSING_TAG_ID"
        ),
        CLASSIFY_PRE_TAG_ID=classify_pre_tag_id,
        CLASSIFY_POST_TAG_ID=_get_optional_positive_int_env(
            source, "CLASSIFY_POST_TAG_ID"
        ),
        CLASSIFY_PROCESSING_TAG_ID=_get_optional_positive_int_env(
            source, "CLASSIFY_PROCESSING_TAG_ID"
        ),
        ERROR_TAG_ID=_get_optional_positive_int_env(source, "ERROR_TAG_ID", 552),
        POLL_INTERVAL=_require_at_least_one(
            "POLL_INTERVAL", _get_int_env(source, "POLL_INTERVAL", 15)
        ),
        MAX_RETRIES=_require_at_least_one(
            "MAX_RETRIES", _get_int_env(source, "MAX_RETRIES", 3)
        ),
        MAX_RETRY_BACKOFF_SECONDS=_require_at_least_one(
            "MAX_RETRY_BACKOFF_SECONDS",
            _get_int_env(source, "MAX_RETRY_BACKOFF_SECONDS", 30),
        ),
        REQUEST_TIMEOUT=_require_at_least_one(
            "REQUEST_TIMEOUT", _get_int_env(source, "REQUEST_TIMEOUT", 180)
        ),
        LLM_MAX_CONCURRENT=max(0, _get_int_env(source, "LLM_MAX_CONCURRENT", 4)),
        # Default True: a single-instance deployment keeps its crash-recovery
        # sweep. A multi-replica deployment sets this False so a restarting
        # replica does not steal a peer's live processing lock (see the field
        # docstring and common.stale_lock).
        STALE_LOCK_RECOVERY=_get_bool_env(source, "STALE_LOCK_RECOVERY", True),
        OCR_DPI=_require_at_least_one("OCR_DPI", _get_int_env(source, "OCR_DPI", 300)),
        OCR_MAX_SIDE=_require_at_least_one(
            "OCR_MAX_SIDE", _get_int_env(source, "OCR_MAX_SIDE", 1600)
        ),
        OCR_IMAGE_DETAIL=_resolve_ocr_image_detail(source),
        OCR_REASONING_EFFORT=_resolve_ocr_reasoning_effort(source),
        PAGE_WORKERS=max(1, _get_int_env(source, "PAGE_WORKERS", 8)),
        DOCUMENT_WORKERS=max(1, _get_int_env(source, "DOCUMENT_WORKERS", 4)),
        LOG_LEVEL=source.get("LOG_LEVEL", "INFO").upper(),
        LOG_FORMAT=_resolve_log_format(source),
        REFUSAL_MARK=_REFUSAL_MARK,
        CLASSIFY_PERSON_FIELD_ID=_get_optional_int_env(
            source, "CLASSIFY_PERSON_FIELD_ID"
        ),
        CLASSIFY_DEFAULT_COUNTRY_TAG=source.get(
            "CLASSIFY_DEFAULT_COUNTRY_TAG", ""
        ).strip(),
        # Clamped >= 0 like its CLASSIFY_* siblings: a negative operator typo
        # must not flow into the truncation logic (0 means "no char cap").
        CLASSIFY_MAX_CHARS=max(0, _get_int_env(source, "CLASSIFY_MAX_CHARS", 0)),
        CLASSIFY_MAX_TOKENS=max(0, _get_int_env(source, "CLASSIFY_MAX_TOKENS", 0)),
        CLASSIFY_TAG_LIMIT=max(0, _get_int_env(source, "CLASSIFY_TAG_LIMIT", 5)),
        CLASSIFY_TAXONOMY_LIMIT=max(
            0, _get_int_env(source, "CLASSIFY_TAXONOMY_LIMIT", 40)
        ),
        CLASSIFY_MAX_PAGES=max(0, _get_int_env(source, "CLASSIFY_MAX_PAGES", 3)),
        CLASSIFY_TAIL_PAGES=max(0, _get_int_env(source, "CLASSIFY_TAIL_PAGES", 2)),
        CLASSIFY_HEADERLESS_CHAR_LIMIT=max(
            0, _get_int_env(source, "CLASSIFY_HEADERLESS_CHAR_LIMIT", 15000)
        ),
        CLASSIFY_REASONING_EFFORT=_resolve_classify_reasoning_effort(source),
        INDEX_DB_PATH=source.get("INDEX_DB_PATH", _DEFAULT_INDEX_DB_PATH),
        APP_DB_PATH=source.get("APP_DB_PATH", _DEFAULT_APP_DB_PATH),
        EMBEDDING_PROVIDER=embedding_provider,
        EMBEDDING_MODEL=source.get("EMBEDDING_MODEL", "text-embedding-3-small"),
        EMBEDDING_DIMENSIONS=_require_at_least_one(
            "EMBEDDING_DIMENSIONS",
            _get_int_env(source, "EMBEDDING_DIMENSIONS", 1536),
        ),
        # 0 means unbounded, mirroring LLM_MAX_CONCURRENT.
        EMBEDDING_MAX_CONCURRENT=max(
            0, _get_int_env(source, "EMBEDDING_MAX_CONCURRENT", 4)
        ),
        RECONCILE_INTERVAL=_require_at_least_one(
            "RECONCILE_INTERVAL", _get_int_env(source, "RECONCILE_INTERVAL", 300)
        ),
        DELETION_SWEEP_INTERVAL=_require_at_least_one(
            "DELETION_SWEEP_INTERVAL",
            _get_int_env(source, "DELETION_SWEEP_INTERVAL", 3600),
        ),
        CHUNK_SIZE=chunk_size,
        CHUNK_OVERLAP=_resolve_chunk_overlap(source, chunk_size),
        SEARCH_TOP_K=search_top_k,
        SEARCH_MAX_REFINEMENTS=_resolve_search_max_refinements(source),
        SEARCH_PLANNER_MODEL=source.get("SEARCH_PLANNER_MODEL", default_planner_model),
        SEARCH_ANSWER_MODEL=source.get("SEARCH_ANSWER_MODEL", default_answer_model),
        # 0.0.0.0 is deliberate: the server is auth-gated by sessions and
        # API keys (CODE_GUIDELINES §10.1); binding all interfaces lets the
        # operator restrict exposure at the reverse proxy / port map.
        SEARCH_SERVER_HOST=source.get("SEARCH_SERVER_HOST", "0.0.0.0"),  # nosec B104 - intentional default, auth-gated, exposure restricted by reverse proxy
        SEARCH_SERVER_PORT=_resolve_server_port(source),
        # Which peers uvicorn trusts the X-Forwarded-For/-Proto headers from.
        # Defaults to "*" — unchanged behaviour, correct behind a reverse
        # proxy whose port is the only reachable one. Pin it to the proxy CIDR
        # in production if the uvicorn port can be reached directly, so an
        # attacker cannot spoof the client IP or the cookie Secure flag (§10.1).
        SEARCH_FORWARDED_ALLOW_IPS=source.get("SEARCH_FORWARDED_ALLOW_IPS", "*"),
        SEARCH_SESSION_TTL=_require_at_least_one(
            "SEARCH_SESSION_TTL", _get_int_env(source, "SEARCH_SESSION_TTL", 604800)
        ),
        # 0 means unbounded, mirroring LLM_MAX_CONCURRENT.
        SEARCH_MAX_CONCURRENT=max(0, _get_int_env(source, "SEARCH_MAX_CONCURRENT", 4)),
        # 0 (the default) disables the per-key daily token quota entirely — the
        # search path then does zero quota-related DB I/O. A negative value
        # clamps to 0 (disabled), so a typo never enables a surprise cap.
        SEARCH_KEY_DAILY_TOKEN_QUOTA=max(
            0, _get_int_env(source, "SEARCH_KEY_DAILY_TOKEN_QUOTA", 0)
        ),
        SEARCH_PLANNER_REASONING_EFFORT=_resolve_search_reasoning_effort(
            source, "SEARCH_PLANNER_REASONING_EFFORT"
        ),
        SEARCH_ANSWER_REASONING_EFFORT=_resolve_search_reasoning_effort(
            source, "SEARCH_ANSWER_REASONING_EFFORT"
        ),
        # 0 disables the result cache entirely (the kill-switch); negative clamps.
        SEARCH_CACHE_TTL_SECONDS=max(
            0, _get_int_env(source, "SEARCH_CACHE_TTL_SECONDS", 14400)
        ),
        SEARCH_SKIP_PLANNER_FOR_TRIVIAL=_get_bool_env(
            source, "SEARCH_SKIP_PLANNER_FOR_TRIVIAL", False
        ),
        SEARCH_GATE_JUDGE=_get_bool_env(source, "SEARCH_GATE_JUDGE", True),
        SEARCH_JUDGE_RATIONALES=_get_bool_env(source, "SEARCH_JUDGE_RATIONALES", True),
        SEARCH_JUDGE_MODEL=source.get("SEARCH_JUDGE_MODEL", default_judge_model),
        SEARCH_JUDGE_REASONING_EFFORT=_resolve_search_reasoning_effort(
            source, "SEARCH_JUDGE_REASONING_EFFORT", default="low"
        ),
        SEARCH_GATE_ADEQUACY=_get_bool_env(source, "SEARCH_GATE_ADEQUACY", True),
        SEARCH_GATE_RELEVANCE=_get_bool_env(source, "SEARCH_GATE_RELEVANCE", True),
        # Default 0.60 — sits between off-topic noise (~0.54-0.58 on the large
        # index, e.g. "popcorn recipe") and real matches (~0.65+), so blatantly
        # off-topic queries fail fast instead of synthesising over junk. Floored
        # at 0.0: a negative floor would never reject anything, same as 0.0, so
        # clamping is more forgiving than raising.
        SEARCH_RELEVANCE_MIN_SIMILARITY=max(
            0.0, _get_float_env(source, "SEARCH_RELEVANCE_MIN_SIMILARITY", 0.60)
        ),
        # Badge cut-points (calibrated, validated together above). Independent of
        # the gate floor: they describe how good a *shown* result is.
        SEARCH_RELEVANCE_TIER_STRONG=tier_strong,
        SEARCH_RELEVANCE_TIER_GOOD=tier_good,
        SEARCH_RELEVANCE_TIER_PARTIAL=tier_partial,
        # Floored at 0 — a negative char floor disables the Layer-0 guard, same
        # as 0, so clamping matches the intent without refusing the daemon start.
        SEARCH_MIN_QUERY_CHARS=max(
            0, _get_int_env(source, "SEARCH_MIN_QUERY_CHARS", 2)
        ),
        SEARCH_IDENTITY_AWARE=_get_bool_env(source, "SEARCH_IDENTITY_AWARE", True),
        # Multi-spec retrieval settings — clamped >= 1 (Phase 1 overhaul).
        SEARCH_PLANNER_MAX_SPECS=max(
            1, _get_int_env(source, "SEARCH_PLANNER_MAX_SPECS", 8)
        ),
        SEARCH_PLANNER_TAXONOMY_LIMIT=max(
            0, _get_int_env(source, "SEARCH_PLANNER_TAXONOMY_LIMIT", 100)
        ),
        # SEARCH_PER_SPEC_K defaults to the already-resolved SEARCH_TOP_K so the
        # per-query candidate budget is unchanged in the single-spec case.
        SEARCH_PER_SPEC_K=max(
            1, _get_int_env(source, "SEARCH_PER_SPEC_K", search_top_k)
        ),
        SEARCH_MAX_CHUNKS_PER_DOC=max(
            1, _get_int_env(source, "SEARCH_MAX_CHUNKS_PER_DOC", 3)
        ),
        # Empty (the default) disables price refresh: the book uses the bundled
        # seed only and makes no network call. A non-empty value is validated as
        # an absolute http/https URL at config-build time.
        PRICING_REFRESH_URL=_resolve_pricing_refresh_url(source),
        # Clamped >= 1 so a 0/negative typo cannot turn the background refresh
        # into a hot loop against the price-list host.
        PRICING_REFRESH_INTERVAL_HOURS=max(
            1, _get_int_env(source, "PRICING_REFRESH_INTERVAL_HOURS", 24)
        ),
    )
