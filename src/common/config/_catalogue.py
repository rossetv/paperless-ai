"""The catalogue of configuration keys.

Defines which environment / config-table keys exist and how they are
classified: the two bootstrap keys that stay environment-only, the secret keys
the Settings API masks, the full universe of config-table keys, and the keys
whose change forces a full re-index. This is the single enumeration the parsing
layer (:mod:`._settings`) and the DB-backed loader (:mod:`._loader`) both refer
to.
"""

from __future__ import annotations

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
        "OCR_MODELS",
        "CLASSIFY_MODELS",
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
        "STALE_LOCK_RECOVERY",
        "OCR_DPI",
        "OCR_MAX_SIDE",
        "OCR_IMAGE_DETAIL",
        "OCR_REASONING_EFFORT",
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
        "CLASSIFY_REASONING_EFFORT",
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
        "SEARCH_FORWARDED_ALLOW_IPS",
        "SEARCH_SESSION_TTL",
        "SEARCH_MAX_CONCURRENT",
        "SEARCH_PLANNER_REASONING_EFFORT",
        "SEARCH_ANSWER_REASONING_EFFORT",
        "SEARCH_CACHE_TTL_SECONDS",
        "SEARCH_SKIP_PLANNER_FOR_TRIVIAL",
        "SEARCH_GATE_ADEQUACY",
        "SEARCH_GATE_RELEVANCE",
        "SEARCH_RELEVANCE_MIN_SIMILARITY",
        "SEARCH_RELEVANCE_TIER_STRONG",
        "SEARCH_RELEVANCE_TIER_GOOD",
        "SEARCH_RELEVANCE_TIER_PARTIAL",
        "SEARCH_MIN_QUERY_CHARS",
        "SEARCH_GATE_JUDGE",
        "SEARCH_JUDGE_MODEL",
        "SEARCH_JUDGE_REASONING_EFFORT",
        "SEARCH_JUDGE_RATIONALES",
        "SEARCH_IDENTITY_AWARE",
        "SEARCH_PLANNER_MAX_SPECS",
        "SEARCH_PLANNER_TAXONOMY_LIMIT",
        "SEARCH_PER_SPEC_K",
        "SEARCH_MAX_CHUNKS_PER_DOC",
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
