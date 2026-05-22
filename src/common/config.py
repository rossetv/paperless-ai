"""Environment-variable configuration for every daemon and the search server.

The :class:`Settings` dataclass is the single, immutable description of a
process's configuration. It is **frozen** (CODE_GUIDELINES §5.2): once built it
cannot be mutated, so no code path can change configuration mid-run.

Construct it with :meth:`Settings.from_environment` — never ``Settings()``
directly. ``from_environment`` reads, parses, validates, and clamps every
environment variable, then builds the instance in a single ``cls(...)`` call.
A missing required variable or an invalid value raises ``ValueError`` with a
message naming the offending variable (CODE_GUIDELINES §1.11, §6.6).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from .constants import REFUSAL_PHRASES

# Default store path used by the indexer and search server.
_DEFAULT_INDEX_DB_PATH = "/data/index.db"

# Default URLs used when environment variables are not set.
_DEFAULT_PAPERLESS_URL = "http://paperless:8000"
_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1/"

# The marker text written into a document's content when every vision model
# refuses to transcribe it. A fixed constant, not configurable.
_REFUSAL_MARK = "CHATGPT REFUSED TO TRANSCRIBE"

# Hard ceiling on SEARCH_MAX_REFINEMENTS. The agentic pipeline's three-LLM-call
# budget (CODE_GUIDELINES §14.3) is a correctness and cost property, not a
# tuning knob: planner (1) + retrieve + refine. SEARCH_MAX_REFINEMENTS counts
# refinement steps, so it is capped here rather than left unbounded.
_SEARCH_MAX_REFINEMENTS_CEILING = 3


# ---------------------------------------------------------------------------
# Environment-variable parsing helpers (pure functions)
# ---------------------------------------------------------------------------


def _get_required_env(var_name: str) -> str:
    """Return the value of *var_name*, raising ``ValueError`` if it is unset."""
    value = os.getenv(var_name)
    if value is None:
        raise ValueError(f"Required environment variable '{var_name}' is not set.")
    return value


def _get_int_env(var_name: str, default: int) -> int:
    """Parse *var_name* as an integer, falling back to *default* when unset.

    Raises a ``ValueError`` naming *var_name* when the value is set but is not
    a valid integer — the opaque stdlib ``invalid literal for int()`` message
    does not say which variable was at fault (CODE_GUIDELINES §6.6).
    """
    raw = os.getenv(var_name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{var_name} must be an integer, got {raw!r}.") from exc


def _get_optional_int_env(var_name: str, default: int | None = None) -> int | None:
    """Parse *var_name* as an integer, returning *default* when unset or blank."""
    raw = os.getenv(var_name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{var_name} must be an integer, got {raw!r}.") from exc


def _get_optional_positive_int_env(
    var_name: str, default: int | None = None
) -> int | None:
    """Like :func:`_get_optional_int_env`, but maps a non-positive value to None."""
    value = _get_optional_int_env(var_name, default)
    if value is not None and value <= 0:
        return None
    return value


def _get_csv_env(
    var_name: str,
    default: list[str],
    *,
    require_non_empty: bool = False,
) -> list[str]:
    """Parse a comma-separated env var, falling back to *default*.

    When *require_non_empty* is ``True``, raises ``ValueError`` if the env
    var is set but yields no items (used for model lists).
    """
    value = os.getenv(var_name)
    if value is None:
        return [item for item in default if item]
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if require_non_empty and not parts:
        raise ValueError(f"{var_name} must contain at least one model name.")
    return parts


def _get_bool_env(var_name: str, default: bool) -> bool:
    """Parse *var_name* as a boolean, falling back to *default* when unset."""
    value = os.getenv(var_name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in ("1", "true", "yes", "y", "on"):
        return True
    if value in ("0", "false", "no", "n", "off"):
        return False
    raise ValueError(f"{var_name} must be a boolean value.")


def _require_at_least_one(var_name: str, value: int, minimum: int = 1) -> int:
    """Return *value*, raising a contextful ``ValueError`` if it is below *minimum*."""
    if value < minimum:
        raise ValueError(f"{var_name} must be >= {minimum}")
    return value


def _resolve_llm_provider() -> Literal["openai", "ollama"]:
    """Resolve and validate ``LLM_PROVIDER`` (defaults to ``openai``)."""
    provider = os.getenv("LLM_PROVIDER", "openai")
    if provider not in ("openai", "ollama"):
        raise ValueError("LLM_PROVIDER must be 'openai' or 'ollama'")
    # rationale: validated above; mypy cannot narrow `str` → `Literal["openai","ollama"]`.
    return provider  # type: ignore[return-value]


def _resolve_log_format() -> Literal["json", "console"]:
    """Resolve and validate ``LOG_FORMAT`` (defaults to ``console``)."""
    log_format = os.getenv("LOG_FORMAT", "console")
    if log_format not in ("json", "console"):
        raise ValueError("LOG_FORMAT must be 'json' or 'console'")
    # rationale: validated above; mypy cannot narrow `str` → `Literal["json","console"]`.
    return log_format  # type: ignore[return-value]


def _resolve_chunk_overlap(chunk_size: int) -> int:
    """Resolve and validate ``CHUNK_OVERLAP`` against *chunk_size*.

    The overlap must be non-negative and strictly less than the chunk size,
    otherwise a chunk could never advance past its own overlap.
    """
    chunk_overlap = _get_int_env("CHUNK_OVERLAP", 256)
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError(
            f"CHUNK_OVERLAP must be >= 0 and < CHUNK_SIZE ({chunk_size}), "
            f"got {chunk_overlap}."
        )
    return chunk_overlap


def _resolve_search_max_refinements() -> int:
    """Resolve and validate ``SEARCH_MAX_REFINEMENTS`` against the §14.3 ceiling."""
    value = _get_int_env("SEARCH_MAX_REFINEMENTS", 1)
    if not 0 <= value <= _SEARCH_MAX_REFINEMENTS_CEILING:
        # The three-LLM-call budget is a hard correctness property, not a knob.
        raise ValueError(
            f"SEARCH_MAX_REFINEMENTS must be between 0 and "
            f"{_SEARCH_MAX_REFINEMENTS_CEILING} (the §14.3 three-LLM-call "
            f"budget), got {value}."
        )
    return value


def _resolve_server_port() -> int:
    """Resolve and validate ``SEARCH_SERVER_PORT`` to the valid TCP port range."""
    port = _get_int_env("SEARCH_SERVER_PORT", 8080)
    if not 1 <= port <= 65535:
        raise ValueError(
            f"SEARCH_SERVER_PORT must be between 1 and 65535, got {port}."
        )
    return port


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable, fully-validated configuration for one process.

    Built once via :meth:`from_environment`; never mutated thereafter. Every
    field is set in a single constructor call, so the type checker and the
    reader both see the complete shape in one place.
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

    # Indexer / store settings (semantic-search spec §10)
    INDEX_DB_PATH: str
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
    # Default is empty string; emptiness validated at search-server preflight,
    # not here — the indexer daemon does not require this key.
    SEARCH_API_KEY: str
    SEARCH_SESSION_TTL: int
    SEARCH_MAX_CONCURRENT: int

    @classmethod
    def from_environment(cls) -> Settings:
        """Build a :class:`Settings` from the process environment.

        Reads, parses, validates, and clamps every environment variable, then
        constructs the frozen instance in one ``cls(...)`` call. Each value is
        produced by a typed parsing helper above, so the constructor arguments
        type-check field by field.

        Raises:
            ValueError: When a required variable is unset, or a value fails
                validation. The message names the offending variable.

        rationale: this function exceeds the 60-line body ceiling because it is
        an irreducibly flat enumeration of every environment variable — one
        keyword per setting. Splitting it would only scatter that single list
        across helpers without lowering the real complexity (CODE_GUIDELINES
        §3.1).
        """
        # Resolved first: these drive the provider-dependent defaults below.
        llm_provider = _resolve_llm_provider()
        post_tag_id = _get_int_env("POST_TAG_ID", 444)
        chunk_size = _require_at_least_one("CHUNK_SIZE", _get_int_env("CHUNK_SIZE", 2000))

        if llm_provider == "ollama":
            ollama_base_url: str | None = os.getenv(
                "OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE_URL
            )
            default_ai_models = ["gemma3:27b", "gemma3:12b"]
            default_planner_model = "gemma3:12b"
            default_answer_model = "gemma3:27b"
        else:
            ollama_base_url = None
            default_ai_models = ["gpt-5.4-mini", "gpt-5.4", "o4-mini"]
            default_planner_model = "gpt-5.4-mini"
            default_answer_model = "gpt-5.4"

        # CLASSIFY_PRE_TAG_ID defaults to POST_TAG_ID (an int), so it is never
        # None here; _get_optional_int_env returns int | None only because it
        # cannot express "None only when the default is None".
        classify_pre_tag_id = _get_optional_int_env("CLASSIFY_PRE_TAG_ID", post_tag_id)
        assert classify_pre_tag_id is not None  # default is an int → never None

        # PAPERLESS_URL is the API base (often an internal address);
        # PAPERLESS_PUBLIC_URL is the browser-facing base for document
        # deep-links and falls back to PAPERLESS_URL when unset, so existing
        # single-URL deployments are unaffected. Both are stored stripped of
        # any trailing slash so callers can append paths cleanly.
        paperless_url = os.getenv(
            "PAPERLESS_URL", _DEFAULT_PAPERLESS_URL
        ).rstrip("/")
        paperless_public_url = os.getenv(
            "PAPERLESS_PUBLIC_URL", paperless_url
        ).rstrip("/")

        return cls(
            PAPERLESS_URL=paperless_url,
            PAPERLESS_PUBLIC_URL=paperless_public_url,
            PAPERLESS_TOKEN=_get_required_env("PAPERLESS_TOKEN"),
            LLM_PROVIDER=llm_provider,
            OLLAMA_BASE_URL=ollama_base_url,
            # Required unconditionally — embeddings always use OpenAI.
            OPENAI_API_KEY=_get_required_env("OPENAI_API_KEY"),
            AI_MODELS=_get_csv_env(
                "AI_MODELS", default_ai_models, require_non_empty=True
            ),
            OCR_REFUSAL_MARKERS=[
                marker.lower()
                for marker in _get_csv_env(
                    "OCR_REFUSAL_MARKERS",
                    [*REFUSAL_PHRASES, _REFUSAL_MARK],
                )
            ],
            OCR_INCLUDE_PAGE_MODELS=_get_bool_env("OCR_INCLUDE_PAGE_MODELS", False),
            PRE_TAG_ID=_get_int_env("PRE_TAG_ID", 443),
            POST_TAG_ID=post_tag_id,
            OCR_PROCESSING_TAG_ID=_get_optional_positive_int_env(
                "OCR_PROCESSING_TAG_ID"
            ),
            CLASSIFY_PRE_TAG_ID=classify_pre_tag_id,
            CLASSIFY_POST_TAG_ID=_get_optional_positive_int_env(
                "CLASSIFY_POST_TAG_ID"
            ),
            CLASSIFY_PROCESSING_TAG_ID=_get_optional_positive_int_env(
                "CLASSIFY_PROCESSING_TAG_ID"
            ),
            ERROR_TAG_ID=_get_optional_positive_int_env("ERROR_TAG_ID", 552),
            POLL_INTERVAL=_get_int_env("POLL_INTERVAL", 15),
            MAX_RETRIES=_require_at_least_one(
                "MAX_RETRIES", _get_int_env("MAX_RETRIES", 20)
            ),
            MAX_RETRY_BACKOFF_SECONDS=_require_at_least_one(
                "MAX_RETRY_BACKOFF_SECONDS",
                _get_int_env("MAX_RETRY_BACKOFF_SECONDS", 30),
            ),
            REQUEST_TIMEOUT=_get_int_env("REQUEST_TIMEOUT", 180),
            LLM_MAX_CONCURRENT=max(0, _get_int_env("LLM_MAX_CONCURRENT", 0)),
            OCR_DPI=_get_int_env("OCR_DPI", 300),
            OCR_MAX_SIDE=_get_int_env("OCR_MAX_SIDE", 1600),
            PAGE_WORKERS=max(1, _get_int_env("PAGE_WORKERS", 8)),
            DOCUMENT_WORKERS=max(1, _get_int_env("DOCUMENT_WORKERS", 4)),
            LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO").upper(),
            LOG_FORMAT=_resolve_log_format(),
            REFUSAL_MARK=_REFUSAL_MARK,
            CLASSIFY_PERSON_FIELD_ID=_get_optional_int_env("CLASSIFY_PERSON_FIELD_ID"),
            CLASSIFY_DEFAULT_COUNTRY_TAG=os.getenv(
                "CLASSIFY_DEFAULT_COUNTRY_TAG", ""
            ).strip(),
            CLASSIFY_MAX_CHARS=_get_int_env("CLASSIFY_MAX_CHARS", 0),
            CLASSIFY_MAX_TOKENS=max(0, _get_int_env("CLASSIFY_MAX_TOKENS", 0)),
            CLASSIFY_TAG_LIMIT=max(0, _get_int_env("CLASSIFY_TAG_LIMIT", 5)),
            CLASSIFY_TAXONOMY_LIMIT=max(
                0, _get_int_env("CLASSIFY_TAXONOMY_LIMIT", 100)
            ),
            CLASSIFY_MAX_PAGES=max(0, _get_int_env("CLASSIFY_MAX_PAGES", 3)),
            CLASSIFY_TAIL_PAGES=max(0, _get_int_env("CLASSIFY_TAIL_PAGES", 2)),
            CLASSIFY_HEADERLESS_CHAR_LIMIT=max(
                0, _get_int_env("CLASSIFY_HEADERLESS_CHAR_LIMIT", 15000)
            ),
            INDEX_DB_PATH=os.getenv("INDEX_DB_PATH", _DEFAULT_INDEX_DB_PATH),
            EMBEDDING_MODEL=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            EMBEDDING_DIMENSIONS=_require_at_least_one(
                "EMBEDDING_DIMENSIONS", _get_int_env("EMBEDDING_DIMENSIONS", 1536)
            ),
            # 0 means unbounded, mirroring LLM_MAX_CONCURRENT.
            EMBEDDING_MAX_CONCURRENT=max(
                0, _get_int_env("EMBEDDING_MAX_CONCURRENT", 4)
            ),
            RECONCILE_INTERVAL=_require_at_least_one(
                "RECONCILE_INTERVAL", _get_int_env("RECONCILE_INTERVAL", 300)
            ),
            DELETION_SWEEP_INTERVAL=_require_at_least_one(
                "DELETION_SWEEP_INTERVAL",
                _get_int_env("DELETION_SWEEP_INTERVAL", 3600),
            ),
            CHUNK_SIZE=chunk_size,
            CHUNK_OVERLAP=_resolve_chunk_overlap(chunk_size),
            SEARCH_TOP_K=_require_at_least_one(
                "SEARCH_TOP_K", _get_int_env("SEARCH_TOP_K", 10)
            ),
            SEARCH_MAX_REFINEMENTS=_resolve_search_max_refinements(),
            SEARCH_PLANNER_MODEL=os.getenv(
                "SEARCH_PLANNER_MODEL", default_planner_model
            ),
            SEARCH_ANSWER_MODEL=os.getenv(
                "SEARCH_ANSWER_MODEL", default_answer_model
            ),
            # 0.0.0.0 is deliberate: the server is auth-gated (SEARCH_API_KEY
            # is mandatory, CODE_GUIDELINES §10.1); binding all interfaces lets
            # the operator restrict exposure at the reverse proxy / port map.
            SEARCH_SERVER_HOST=os.getenv("SEARCH_SERVER_HOST", "0.0.0.0"),
            SEARCH_SERVER_PORT=_resolve_server_port(),
            # Empty default is intentional — the search server validates
            # non-empty at preflight; the indexer does not need this key.
            SEARCH_API_KEY=os.getenv("SEARCH_API_KEY", ""),
            SEARCH_SESSION_TTL=_require_at_least_one(
                "SEARCH_SESSION_TTL", _get_int_env("SEARCH_SESSION_TTL", 604800)
            ),
            # 0 means unbounded, mirroring LLM_MAX_CONCURRENT.
            SEARCH_MAX_CONCURRENT=max(
                0, _get_int_env("SEARCH_MAX_CONCURRENT", 4)
            ),
        )
