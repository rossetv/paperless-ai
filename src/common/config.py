"""Environment-variable configuration for every daemon and the search server.

The :class:`Settings` dataclass is the single, immutable description of a
process's configuration. It is **frozen** (CODE_GUIDELINES §5.2): once built it
cannot be mutated, so no code path can change configuration mid-run.

Two construction paths exist:

* :func:`load_settings` — the production entry point. Layers the ``config``
  table (in ``app.db``) over the process environment, so a value in the table
  wins, then an environment variable, then the coded default.
* :meth:`Settings.from_environment` — the environment-only path, preserved
  for tests and any caller that has no ``app.db``. Parses, validates, and
  clamps every environment variable, raising ``ValueError`` with a message
  naming the offending variable (CODE_GUIDELINES §1.11, §6.6).

Both paths share :func:`_build_settings`: the same parsing, validation and
clamping is applied to whichever string mapping is presented as the source.
"""

from __future__ import annotations

# rationale: this module exceeds CODE_GUIDELINES §3.1's 500-line ceiling
# (currently ~785 lines) because the `Settings` dataclass IS the single,
# immutable contract for every process. The catalogue, parsers, validators,
# clamping, defaults, env-only constructor, the DB-backed `load_settings`, and
# the version-keyed `current_settings` hot-load accessor are one cohesive
# concern: splitting them would scatter the schema's source of truth, add
# import cycles between the parser and the loader, and break the rule that one
# place defines what each setting is and how it is parsed.

import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from .constants import REFUSAL_PHRASES

# Default store path used by the indexer and search server.
_DEFAULT_INDEX_DB_PATH = "/data/index.db"
# Default application-database path. app.db holds accounts, sessions, and
# (from later waves) config; it is separate from index.db so rebuilding the
# search index never destroys accounts.
_DEFAULT_APP_DB_PATH = "/data/app.db"

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
# Config-in-database key catalogue (web-redesign spec §5, Wave 4)
# ---------------------------------------------------------------------------

# The two bootstrap variables. They tell a process where its databases live,
# so they cannot themselves be stored in a database — they stay environment
# variables and are never written to the config table.
BOOTSTRAP_KEYS: frozenset[str] = frozenset({"APP_DB_PATH", "INDEX_DB_PATH"})

# Config keys whose value is a secret. The Settings API masks these in
# GET /api/settings responses; a value is revealed only via the explicit
# reveal mechanism. app.db sits on the protected /data volume, so the secrets
# are stored there in clear — masking is an API-surface concern, not storage.
SECRET_KEYS: frozenset[str] = frozenset({"OPENAI_API_KEY", "PAPERLESS_TOKEN"})

# The canonical universe of config-table keys — every value the application
# reads from the config table rather than as a bootstrap env-var. This is the
# complete enumeration of the env-driven Settings fields; PUT /api/settings
# rejects any key not in this set. The two BOOTSTRAP_KEYS and the fixed
# REFUSAL_MARK constant are deliberately absent. SEARCH_API_KEY is absent too
# — Wave 3 retired the legacy bearer-token path, so no process reads it.
CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "PAPERLESS_URL",
        "PAPERLESS_PUBLIC_URL",
        "PAPERLESS_TOKEN",
        "LLM_PROVIDER",
        "OLLAMA_BASE_URL",
        "OPENAI_API_KEY",
        "AI_MODELS",
        "OCR_REFUSAL_MARKERS",
        "OCR_INCLUDE_PAGE_MODELS",
        "PRE_TAG_ID",
        "POST_TAG_ID",
        "OCR_PROCESSING_TAG_ID",
        "CLASSIFY_PRE_TAG_ID",
        "CLASSIFY_POST_TAG_ID",
        "CLASSIFY_PROCESSING_TAG_ID",
        "ERROR_TAG_ID",
        "POLL_INTERVAL",
        "MAX_RETRIES",
        "MAX_RETRY_BACKOFF_SECONDS",
        "REQUEST_TIMEOUT",
        "LLM_MAX_CONCURRENT",
        "OCR_DPI",
        "OCR_MAX_SIDE",
        "PAGE_WORKERS",
        "DOCUMENT_WORKERS",
        "LOG_LEVEL",
        "LOG_FORMAT",
        "CLASSIFY_PERSON_FIELD_ID",
        "CLASSIFY_DEFAULT_COUNTRY_TAG",
        "CLASSIFY_MAX_CHARS",
        "CLASSIFY_MAX_TOKENS",
        "CLASSIFY_TAG_LIMIT",
        "CLASSIFY_TAXONOMY_LIMIT",
        "CLASSIFY_MAX_PAGES",
        "CLASSIFY_TAIL_PAGES",
        "CLASSIFY_HEADERLESS_CHAR_LIMIT",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIMENSIONS",
        "EMBEDDING_MAX_CONCURRENT",
        "RECONCILE_INTERVAL",
        "DELETION_SWEEP_INTERVAL",
        "CHUNK_SIZE",
        "CHUNK_OVERLAP",
        "SEARCH_TOP_K",
        "SEARCH_MAX_REFINEMENTS",
        "SEARCH_PLANNER_MODEL",
        "SEARCH_ANSWER_MODEL",
        "SEARCH_SERVER_HOST",
        "SEARCH_SERVER_PORT",
        "SEARCH_SESSION_TTL",
        "SEARCH_MAX_CONCURRENT",
    }
)

# Config keys whose change requires re-indexing every document — they govern
# how text is chunked and embedded, so a change is only consistent once the
# whole index is rebuilt. Saving still hot-loads (no restart); the Settings
# UI warns the operator to run a full re-index from the Index page for these
# keys, and only these. EMBEDDING_DIMENSIONS is deliberately excluded: it is
# locked to the embedding model and the index schema pins it on first
# reconcile, so a lone change is rejected by validation rather than warned.
REINDEX_KEYS: frozenset[str] = frozenset(
    {"EMBEDDING_MODEL", "CHUNK_SIZE", "CHUNK_OVERLAP"}
)


# ---------------------------------------------------------------------------
# String-mapping parsing helpers (pure functions)
# ---------------------------------------------------------------------------


def _get_required_env(source: Mapping[str, str], var_name: str) -> str:
    """Return *var_name* from *source*, raising ``ValueError`` if it is unset.

    An absent key, an empty string and a whitespace-only string are all
    treated as "unset" — a required secret that round-trips ``""`` through
    the Settings API (e.g. an admin saved ``PAPERLESS_TOKEN=""``) must be
    rejected at this boundary rather than discovered when a daemon
    authenticates with an empty token and Paperless answers 401.
    """
    value = source.get(var_name)
    if value is None or not value.strip():
        raise ValueError(f"Required environment variable '{var_name}' is not set.")
    return value


def _get_int_env(source: Mapping[str, str], var_name: str, default: int) -> int:
    """Parse *var_name* from *source* as an integer, falling back to *default*.

    Raises a ``ValueError`` naming *var_name* when the value is set but is not
    a valid integer.
    """
    raw = source.get(var_name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{var_name} must be an integer, got {raw!r}.") from exc


def _get_optional_int_env(
    source: Mapping[str, str], var_name: str, default: int | None = None
) -> int | None:
    """Parse *var_name* from *source* as an integer, returning *default* when
    unset or blank."""
    raw = source.get(var_name)
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
    source: Mapping[str, str], var_name: str, default: int | None = None
) -> int | None:
    """Like :func:`_get_optional_int_env`, but maps a non-positive value to None."""
    value = _get_optional_int_env(source, var_name, default)
    if value is not None and value <= 0:
        return None
    return value


def _get_csv_env(
    source: Mapping[str, str],
    var_name: str,
    default: list[str],
    *,
    require_non_empty: bool = False,
) -> list[str]:
    """Parse a comma-separated value from *source*, falling back to *default*.

    When *require_non_empty* is ``True``, raises ``ValueError`` if the value
    is set but yields no items (used for model lists).
    """
    value = source.get(var_name)
    if value is None:
        return [item for item in default if item]
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if require_non_empty and not parts:
        raise ValueError(f"{var_name} must contain at least one model name.")
    return parts


def _get_bool_env(source: Mapping[str, str], var_name: str, default: bool) -> bool:
    """Parse *var_name* from *source* as a boolean, falling back to *default*."""
    value = source.get(var_name)
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


def _resolve_llm_provider(source: Mapping[str, str]) -> Literal["openai", "ollama"]:
    """Resolve and validate ``LLM_PROVIDER`` (defaults to ``openai``)."""
    provider = source.get("LLM_PROVIDER", "openai")
    if provider not in ("openai", "ollama"):
        raise ValueError("LLM_PROVIDER must be 'openai' or 'ollama'")
    # rationale: validated above; mypy cannot narrow `str` → `Literal[...]`.
    return provider  # type: ignore[return-value]


def _resolve_log_format(source: Mapping[str, str]) -> Literal["json", "console"]:
    """Resolve and validate ``LOG_FORMAT`` (defaults to ``console``)."""
    log_format = source.get("LOG_FORMAT", "console")
    if log_format not in ("json", "console"):
        raise ValueError("LOG_FORMAT must be 'json' or 'console'")
    # rationale: validated above; mypy cannot narrow `str` → `Literal[...]`.
    return log_format  # type: ignore[return-value]


def _resolve_chunk_overlap(source: Mapping[str, str], chunk_size: int) -> int:
    """Resolve and validate ``CHUNK_OVERLAP`` against *chunk_size*.

    The overlap must be non-negative and strictly less than the chunk size,
    otherwise a chunk could never advance past its own overlap.
    """
    chunk_overlap = _get_int_env(source, "CHUNK_OVERLAP", 256)
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError(
            f"CHUNK_OVERLAP must be >= 0 and < CHUNK_SIZE ({chunk_size}), "
            f"got {chunk_overlap}."
        )
    return chunk_overlap


def _resolve_search_max_refinements(source: Mapping[str, str]) -> int:
    """Resolve and validate ``SEARCH_MAX_REFINEMENTS`` against the §14.3 ceiling."""
    value = _get_int_env(source, "SEARCH_MAX_REFINEMENTS", 1)
    if not 0 <= value <= _SEARCH_MAX_REFINEMENTS_CEILING:
        # The three-LLM-call budget is a hard correctness property, not a knob.
        raise ValueError(
            f"SEARCH_MAX_REFINEMENTS must be between 0 and "
            f"{_SEARCH_MAX_REFINEMENTS_CEILING} (the §14.3 three-LLM-call "
            f"budget), got {value}."
        )
    return value


def _resolve_server_port(source: Mapping[str, str]) -> int:
    """Resolve and validate ``SEARCH_SERVER_PORT`` to the valid TCP port range."""
    port = _get_int_env(source, "SEARCH_SERVER_PORT", 8080)
    if not 1 <= port <= 65535:
        raise ValueError(f"SEARCH_SERVER_PORT must be between 1 and 65535, got {port}.")
    return port


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
    SEARCH_SESSION_TTL: int
    SEARCH_MAX_CONCURRENT: int

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

    if llm_provider == "ollama":
        ollama_base_url: str | None = source.get(
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
    classify_pre_tag_id = _get_optional_int_env(
        source, "CLASSIFY_PRE_TAG_ID", post_tag_id
    )
    assert classify_pre_tag_id is not None  # default is an int → never None

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
        POLL_INTERVAL=_get_int_env(source, "POLL_INTERVAL", 15),
        MAX_RETRIES=_require_at_least_one(
            "MAX_RETRIES", _get_int_env(source, "MAX_RETRIES", 20)
        ),
        MAX_RETRY_BACKOFF_SECONDS=_require_at_least_one(
            "MAX_RETRY_BACKOFF_SECONDS",
            _get_int_env(source, "MAX_RETRY_BACKOFF_SECONDS", 30),
        ),
        REQUEST_TIMEOUT=_get_int_env(source, "REQUEST_TIMEOUT", 180),
        LLM_MAX_CONCURRENT=max(0, _get_int_env(source, "LLM_MAX_CONCURRENT", 0)),
        OCR_DPI=_get_int_env(source, "OCR_DPI", 300),
        OCR_MAX_SIDE=_get_int_env(source, "OCR_MAX_SIDE", 1600),
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
            0, _get_int_env(source, "CLASSIFY_TAXONOMY_LIMIT", 100)
        ),
        CLASSIFY_MAX_PAGES=max(0, _get_int_env(source, "CLASSIFY_MAX_PAGES", 3)),
        CLASSIFY_TAIL_PAGES=max(0, _get_int_env(source, "CLASSIFY_TAIL_PAGES", 2)),
        CLASSIFY_HEADERLESS_CHAR_LIMIT=max(
            0, _get_int_env(source, "CLASSIFY_HEADERLESS_CHAR_LIMIT", 15000)
        ),
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
        SEARCH_SESSION_TTL=_require_at_least_one(
            "SEARCH_SESSION_TTL", _get_int_env(source, "SEARCH_SESSION_TTL", 604800)
        ),
        # 0 means unbounded, mirroring LLM_MAX_CONCURRENT.
        SEARCH_MAX_CONCURRENT=max(0, _get_int_env(source, "SEARCH_MAX_CONCURRENT", 4)),
    )


def load_settings(app_db_path: str) -> Settings:
    """Build a validated :class:`Settings` from ``app.db`` and the environment.

    The production configuration entry point (web-redesign spec §5). It layers
    the ``config`` table over the process environment so that, for every key,
    a value in the table wins, then an environment variable, then the coded
    default.

    On first run — when the ``config`` table is empty — it seeds the table
    from the current environment (:func:`appdb.config.seed_from_env`), so a
    deployment previously configured with environment variables keeps working
    with no change and its settings become editable in the Settings screen.

    The two bootstrap variables ``APP_DB_PATH`` and ``INDEX_DB_PATH`` are
    never read from the table — they tell the process where its databases
    live, so they stay environment-only.

    Args:
        app_db_path: Filesystem path to ``app.db``. Comes from the
            ``APP_DB_PATH`` bootstrap environment variable (resolved by the
            caller, normally :func:`common.bootstrap.bootstrap_process`).

    Returns:
        The validated :class:`Settings`.

    Raises:
        ValueError: A required key is missing from both the table and the
            environment, or a stored value fails validation. The message
            names the offending key.
        appdb.migrations.AppDbError: ``app.db`` was written by newer code.

    rationale: ``app.db`` is opened and closed within this function — the
    loader needs only a transient connection. The search server opens its own
    long-lived ``app.db`` connection for the Settings API; the daemons only
    ever read config once, at startup, so a per-call connection is correct
    and avoids leaking a handle a daemon would never use again.
    """
    # Deferred imports: common is the leaf package, and importing appdb at
    # module scope would run on every `import common.config`. A function-body
    # import keeps the dependency where it is actually used and matches the
    # relaxed import boundary (appdb is permitted; store is not).
    from appdb import config as config_store  # noqa: PLC0415
    from appdb.connection import connect  # noqa: PLC0415
    from appdb.schema import ensure_schema  # noqa: PLC0415

    conn = connect(app_db_path)
    try:
        ensure_schema(conn)
        config_store.seed_from_env(conn, environ=os.environ, keys=set(CONFIG_KEYS))
        stored = config_store.get_all(conn)
    finally:
        conn.close()

    # Merge: the environment first, the config table layered on top — so a
    # config-table value overrides an environment value. The bootstrap
    # variables are environment-only, so they survive from os.environ; they
    # are never in `stored` because seed_from_env only seeds CONFIG_KEYS.
    merged: dict[str, str] = dict(os.environ)
    merged.update(stored)
    # The bootstrap variables are never in the config table, but app_db_path
    # is known explicitly here — inject it so _build_settings resolves
    # Settings.APP_DB_PATH to the path the caller actually used, regardless
    # of whether APP_DB_PATH is set in the environment.
    merged["APP_DB_PATH"] = app_db_path
    return _build_settings(merged)


# Process-local hot-load cache: app.db path -> (config_version, Settings).
# current_settings() rebuilds Settings only when the stored config_version
# has advanced, so a polling daemon pays one cheap SELECT per check.
_SETTINGS_CACHE: dict[str, tuple[int, Settings]] = {}


# Lock serialising rebuilds of ``_SETTINGS_CACHE``. The dict ops themselves are
# GIL-atomic, but two concurrent first-callers (or two callers landing on a
# fresh ``config_version``) would otherwise both build a Settings and both
# write — the loser's expensive build is wasted. The lock collapses that into
# one builder per version. The lookup path stays lock-free; only the rebuild
# is serialised.
_SETTINGS_CACHE_LOCK = threading.Lock()


def current_settings(app_db_path: str | None = None) -> Settings:
    """Return the up-to-date :class:`Settings`, rebuilding it on a config change.

    The hot-load accessor (web-redesign §5, Wave 4). Saving configuration does
    not restart any process; instead every process calls this at a safe
    boundary — a daemon at the top of its poll loop, the search server per
    request — and gets a :class:`Settings` that reflects the latest saved
    configuration.

    It takes no argument in normal use: *app_db_path* defaults to the
    ``APP_DB_PATH`` bootstrap environment variable (the same value
    :func:`common.bootstrap.bootstrap_process` resolves), so every process
    can simply ``from common.config import current_settings`` and call it.
    The explicit parameter exists for tests, which point it at a temp file.

    It is cheap to call repeatedly. It opens ``app.db`` and takes a single
    snapshot of ``(config_version, config_table)`` via
    :func:`appdb.config.snapshot_config_with_version` — one connection, one
    ``BEGIN DEFERRED`` transaction — so the version and the data it describes
    are always consistent. When that integer is unchanged since the last
    call for this *app_db_path*, it returns the **cached** :class:`Settings`
    untouched. Only when ``config_version`` has advanced (or on the first
    call) does it rebuild from the snapshot and re-cache under the very
    version the snapshot reported.

    The cache is process-local module state. Cross-process coordination is the
    shared ``config_version`` row alone — when one process writes config
    through the Settings API, every other process sees the bumped version on
    its next check and rebuilds. No signal, no IPC, no restart.

    Args:
        app_db_path: Filesystem path to ``app.db``. When ``None`` (the normal
            case) it is read from the ``APP_DB_PATH`` environment variable,
            with the same ``/data/app.db`` default the other entry points use.

    Returns:
        The current validated :class:`Settings`.

    Raises:
        ValueError: A stored value fails validation (same as
            :func:`load_settings`).
        appdb.migrations.AppDbError: ``app.db`` was written by newer code.
    """
    # Deferred import — see load_settings for the rationale.
    from appdb import config as config_store  # noqa: PLC0415
    from appdb.connection import connect  # noqa: PLC0415
    from appdb.schema import ensure_schema  # noqa: PLC0415

    resolved = (
        app_db_path
        if app_db_path is not None
        else os.environ.get("APP_DB_PATH", "/data/app.db")
    )

    # Fast path: read the version under a snapshot, take the cache value if
    # it matches. The snapshot also captures the config_table we will need
    # if the version has moved, so we never re-open the DB on the rebuild
    # path — the version and the data are consistent by construction.
    conn = connect(resolved)
    try:
        ensure_schema(conn)
        version, config_table = config_store.snapshot_config_with_version(conn)
    finally:
        conn.close()

    cached = _SETTINGS_CACHE.get(resolved)
    if cached is not None and cached[0] == version:
        return cached[1]

    # Slow path under a lock: re-check the cache (another caller may have
    # rebuilt while we waited), then build a Settings from the snapshot we
    # took above and cache it under the version that snapshot reported. If
    # the config table is empty we first seed it from the environment — that
    # bumps config_version, so we re-snapshot and rebuild from the seeded
    # data — and the cached pair is always (version, Settings-built-from-it).
    with _SETTINGS_CACHE_LOCK:
        cached = _SETTINGS_CACHE.get(resolved)
        if cached is not None and cached[0] == version:
            return cached[1]

        if not config_table:
            # First-run seed (web-redesign §5). The seed runs inside its own
            # ``BEGIN IMMEDIATE`` and bumps config_version; re-snapshot so the
            # cache key matches the post-seed version.
            conn = connect(resolved)
            try:
                config_store.seed_from_env(
                    conn, environ=os.environ, keys=set(CONFIG_KEYS)
                )
                version, config_table = config_store.snapshot_config_with_version(conn)
            finally:
                conn.close()

        settings = _build_settings(_merge_environment(config_table, resolved))
        _SETTINGS_CACHE[resolved] = (version, settings)
        return settings


def current_settings_with_version(
    app_db_path: str | None = None,
) -> tuple[int, Settings]:
    """Return ``(config_version, Settings)`` atomically, rebuilding on change.

    A thin companion to :func:`current_settings` for callers that need to key
    a downstream cache against the *exact* version the settings snapshot was
    built from. The version comes from the same ``BEGIN DEFERRED`` snapshot
    used to read the config table, so it is guaranteed to match the data in
    the returned :class:`Settings` — it cannot be a later version stamped onto
    an earlier dataset.

    The typical caller is :func:`search.api._resolve_search_core`: it caches a
    ``SearchCore`` built from the settings and must key that cache against the
    version the settings actually describe, so a concurrent admin write cannot
    produce a ``(newer_version, core_from_older_settings)`` pair that sticks
    until a *further* unrelated write bumps the counter again.

    All caching logic (including the rebuild-under-lock slow path) is delegated
    to :func:`current_settings`; after it returns the ``_SETTINGS_CACHE`` entry
    for *resolved* is guaranteed to be at the version the settings were built
    from (or a later one if another thread rebuilt first — which is fine, the
    returned version always matches the returned Settings).

    Args:
        app_db_path: Filesystem path to ``app.db``. When ``None`` (the normal
            case) it is read from the ``APP_DB_PATH`` environment variable.

    Returns:
        ``(config_version, Settings)`` where ``config_version`` is the
        version the settings snapshot was built from.
    """
    resolved = (
        app_db_path
        if app_db_path is not None
        else os.environ.get("APP_DB_PATH", "/data/app.db")
    )

    # Delegate to current_settings for all snapshot + cache logic.
    settings = current_settings(resolved)

    # After current_settings returns, _SETTINGS_CACHE[resolved] holds exactly
    # the (version, settings) pair that was built and is now current. Read it
    # back to get the version — this is a GIL-atomic dict read, no lock needed.
    cached = _SETTINGS_CACHE.get(resolved)
    if cached is not None:
        return cached[0], cached[1]

    # Defensive fallback: the cache was cleared between current_settings and
    # the read above (only possible if _reset_core_cache_for_test was called
    # from another thread, which tests never do concurrently). Call once more.
    settings = current_settings(resolved)
    cached = _SETTINGS_CACHE.get(resolved)
    if cached is not None:
        return cached[0], cached[1]

    # Should never reach here; return version 0 so callers rebuild next time.
    return 0, settings


def _merge_environment(
    config_table: Mapping[str, str], app_db_path: str
) -> dict[str, str]:
    """Layer *config_table* over ``os.environ`` for :func:`_build_settings`.

    Mirrors the merge :func:`load_settings` performs, factored out so the
    hot-load fast path can reuse it without re-opening ``app.db``: the table
    value wins over an environment value, the bootstrap variables stay
    environment-only, and ``APP_DB_PATH`` is forced to the *app_db_path* the
    caller resolved (it is never in the table).
    """
    merged: dict[str, str] = dict(os.environ)
    merged.update(config_table)
    merged["APP_DB_PATH"] = app_db_path
    return merged
