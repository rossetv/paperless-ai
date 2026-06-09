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
    _resolve_llm_provider,
    _resolve_log_format,
    _resolve_ocr_image_detail,
    _resolve_ocr_reasoning_effort,
    _resolve_search_max_refinements,
    _resolve_search_reasoning_effort,
    _resolve_server_port,
)

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
    """The model and base-URL defaults that depend on ``LLM_PROVIDER``.

    Resolved once in :func:`_resolve_provider_defaults` so the provider branch
    lives in one place rather than inline in :func:`_build_settings` (COMMON-15).
    """

    ollama_base_url: str | None
    ai_models: list[str]
    planner_model: str
    answer_model: str


def _resolve_provider_defaults(
    llm_provider: Literal["openai", "ollama"], source: Mapping[str, str]
) -> _ProviderDefaults:
    """Resolve the provider-dependent model and base-URL defaults.

    Under ``ollama`` the Ollama base URL is read (defaulting to the local
    daemon) and the model defaults are the local Gemma set; under ``openai`` the
    base URL is ``None`` and the defaults are the GPT set. These are only
    *defaults* — an explicit ``AI_MODELS`` / ``SEARCH_*_MODEL`` value in *source*
    still wins in :func:`_build_settings`.
    """
    if llm_provider == "ollama":
        return _ProviderDefaults(
            ollama_base_url=source.get("OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE_URL),
            ai_models=["gemma3:27b", "gemma3:12b"],
            planner_model="gemma3:12b",
            answer_model="gemma3:27b",
        )
    return _ProviderDefaults(
        ollama_base_url=None,
        ai_models=["gpt-5.4-mini", "gpt-5.4", "gpt-5.5"],
        planner_model="gpt-5.4-mini",
        answer_model="gpt-5.5",
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
    # OPENAI_API_KEY is required regardless of LLM_PROVIDER: the embedding
    # client always uses OpenAI (CODE_GUIDELINES §10.8, §15.4).
    OPENAI_API_KEY: str

    AI_MODELS: list[str]
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

    # Search/RAG token-cost settings (token-cost programme Area 3)
    SEARCH_PLANNER_REASONING_EFFORT: str
    SEARCH_ANSWER_REASONING_EFFORT: str
    SEARCH_CACHE_TTL_SECONDS: int
    SEARCH_SKIP_PLANNER_FOR_TRIVIAL: bool

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
    default ``0.60`` was calibrated against the live index: known-good queries
    scored 0.666–0.713, blatantly off-topic queries as low as 0.567 (e.g.
    ``Popcorn``). 0.60 sits below the worst good score, so a real query is never
    rejected, while still catching off-topic noise. It deliberately does *not*
    catch near-miss queries (a document the library genuinely lacks scores like
    a good one, because it shares tokens with real documents) — those are the
    synthesiser's job, not this gate's. Floored at ``≥ 0.0``; negative values
    are clamped to ``0.0``.
    """
    SEARCH_MIN_QUERY_CHARS: int
    """Minimum number of non-whitespace characters for a search query (Layer 0).

    Queries shorter than this floor are rejected before any LLM call. The
    default of ``2`` catches blank, single-character, and whitespace-only
    inputs without being so strict that it blocks legitimate short queries.
    Floored at ``≥ 0``; negative values are clamped to ``0``.
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
    post_tag_id = _get_int_env(source, "POST_TAG_ID", 444)
    chunk_size = _require_at_least_one(
        "CHUNK_SIZE", _get_int_env(source, "CHUNK_SIZE", 2000)
    )

    provider_defaults = _resolve_provider_defaults(llm_provider, source)
    ollama_base_url = provider_defaults.ollama_base_url
    default_ai_models = provider_defaults.ai_models
    default_planner_model = provider_defaults.planner_model
    default_answer_model = provider_defaults.answer_model

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

    return Settings(
        PAPERLESS_URL=paperless_url,
        PAPERLESS_PUBLIC_URL=paperless_public_url,
        PAPERLESS_TOKEN=_get_required_env(source, "PAPERLESS_TOKEN"),
        LLM_PROVIDER=llm_provider,
        OLLAMA_BASE_URL=ollama_base_url,
        # Required unconditionally — embeddings always use OpenAI.
        OPENAI_API_KEY=_get_required_env(source, "OPENAI_API_KEY"),
        AI_MODELS=_get_csv_env(
            source, "AI_MODELS", default_ai_models, require_non_empty=True
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
        CLASSIFY_MAX_CHARS=_get_int_env(source, "CLASSIFY_MAX_CHARS", 0),
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
        SEARCH_TOP_K=_require_at_least_one(
            "SEARCH_TOP_K", _get_int_env(source, "SEARCH_TOP_K", 10)
        ),
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
        SEARCH_GATE_ADEQUACY=_get_bool_env(source, "SEARCH_GATE_ADEQUACY", True),
        SEARCH_GATE_RELEVANCE=_get_bool_env(source, "SEARCH_GATE_RELEVANCE", True),
        # Default 0.60 — calibrated below the worst known-good similarity
        # (0.666) and above off-topic noise (Popcorn ≈ 0.567). Floored at 0.0:
        # a negative floor would never reject anything, same as 0.0, so clamping
        # is more forgiving than raising.
        SEARCH_RELEVANCE_MIN_SIMILARITY=max(
            0.0, _get_float_env(source, "SEARCH_RELEVANCE_MIN_SIMILARITY", 0.60)
        ),
        # Floored at 0 — a negative char floor disables the Layer-0 guard, same
        # as 0, so clamping matches the intent without refusing the daemon start.
        SEARCH_MIN_QUERY_CHARS=max(
            0, _get_int_env(source, "SEARCH_MIN_QUERY_CHARS", 2)
        ),
    )
