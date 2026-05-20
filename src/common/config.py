"""Environment-variable configuration for the OCR and classification daemons."""

from __future__ import annotations

import os
from typing import Literal

from .constants import REFUSAL_PHRASES

# Default store path used by the indexer and search server.
_DEFAULT_INDEX_DB_PATH = "/data/index.db"

# Default URLs used when environment variables are not set.
_DEFAULT_PAPERLESS_URL = "http://paperless:8000"
_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1/"


class Settings:

    PAPERLESS_URL: str
    PAPERLESS_TOKEN: str

    LLM_PROVIDER: Literal["openai", "ollama"]
    OLLAMA_BASE_URL: str | None
    OPENAI_API_KEY: str | None

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

    REFUSAL_MARK: str = "CHATGPT REFUSED TO TRANSCRIBE"

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

    def __init__(self):
        self._load_api_settings()
        self._load_llm_settings()
        self._load_tag_settings()
        self._load_daemon_settings()
        self._load_image_settings()
        self._load_logging_settings()
        self._load_classification_settings()
        self._load_index_settings()
        self._load_search_settings()

    def _load_api_settings(self) -> None:
        self.PAPERLESS_URL = os.getenv("PAPERLESS_URL", _DEFAULT_PAPERLESS_URL).rstrip(
            "/"
        )
        self.PAPERLESS_TOKEN = self._get_required_env("PAPERLESS_TOKEN")

    def _load_llm_settings(self) -> None:
        _llm_provider = os.getenv("LLM_PROVIDER", "openai")
        if _llm_provider not in ("openai", "ollama"):
            raise ValueError("LLM_PROVIDER must be 'openai' or 'ollama'")
        # Validated above; narrow from str to Literal.
        self.LLM_PROVIDER: Literal["openai", "ollama"] = _llm_provider  # type: ignore[assignment]

        if self.LLM_PROVIDER == "ollama":
            self.OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE_URL)
            self.OPENAI_API_KEY = None
            default_ai_models = ["gemma3:27b", "gemma3:12b"]
        else:
            self.OLLAMA_BASE_URL = None
            self.OPENAI_API_KEY = self._get_required_env("OPENAI_API_KEY")
            default_ai_models = ["gpt-5.4-mini", "gpt-5.4", "o4-mini"]
        self.AI_MODELS = self._get_csv_env(
            "AI_MODELS", default_ai_models, require_non_empty=True
        )
        default_ocr_refusal_markers = list(REFUSAL_PHRASES) + [self.REFUSAL_MARK]
        self.OCR_REFUSAL_MARKERS = [
            marker.lower()
            for marker in self._get_csv_env(
                "OCR_REFUSAL_MARKERS", default_ocr_refusal_markers
            )
        ]
        self.OCR_INCLUDE_PAGE_MODELS = self._get_bool_env(
            "OCR_INCLUDE_PAGE_MODELS", False
        )

    def _load_tag_settings(self) -> None:
        self.PRE_TAG_ID = int(os.getenv("PRE_TAG_ID", "443"))
        self.POST_TAG_ID = int(os.getenv("POST_TAG_ID", "444"))
        self.OCR_PROCESSING_TAG_ID = self._get_optional_positive_int_env(
            "OCR_PROCESSING_TAG_ID"
        )
        # The default is POST_TAG_ID (an int), so the result is never None in
        # practice; the helper's return type is int | None because it cannot
        # express "only None when the default is None".
        self.CLASSIFY_PRE_TAG_ID = self._get_optional_int_env(  # type: ignore[assignment]
            "CLASSIFY_PRE_TAG_ID", self.POST_TAG_ID
        )
        self.CLASSIFY_POST_TAG_ID = self._get_optional_positive_int_env(
            "CLASSIFY_POST_TAG_ID"
        )
        self.CLASSIFY_PROCESSING_TAG_ID = self._get_optional_positive_int_env(
            "CLASSIFY_PROCESSING_TAG_ID"
        )
        self.ERROR_TAG_ID = self._get_optional_positive_int_env("ERROR_TAG_ID", 552)

    def _load_daemon_settings(self) -> None:
        self.POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "15"))
        self.MAX_RETRIES = int(os.getenv("MAX_RETRIES", "20"))
        if self.MAX_RETRIES < 1:
            raise ValueError("MAX_RETRIES must be >= 1")
        self.MAX_RETRY_BACKOFF_SECONDS = int(
            os.getenv("MAX_RETRY_BACKOFF_SECONDS", "30")
        )
        if self.MAX_RETRY_BACKOFF_SECONDS < 1:
            raise ValueError("MAX_RETRY_BACKOFF_SECONDS must be >= 1")
        self.REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "180"))
        self.LLM_MAX_CONCURRENT = max(0, int(os.getenv("LLM_MAX_CONCURRENT", "0")))

    def _load_image_settings(self) -> None:
        self.OCR_DPI = int(os.getenv("OCR_DPI", "300"))
        self.OCR_MAX_SIDE = int(os.getenv("OCR_MAX_SIDE", "1600"))
        self.PAGE_WORKERS = max(1, int(os.getenv("PAGE_WORKERS", "8")))
        self.DOCUMENT_WORKERS = max(1, int(os.getenv("DOCUMENT_WORKERS", "4")))

    def _load_logging_settings(self) -> None:
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
        _log_format = os.getenv("LOG_FORMAT", "console")
        if _log_format not in ("json", "console"):
            raise ValueError("LOG_FORMAT must be 'json' or 'console'")
        # Validated above; narrow from str to Literal.
        self.LOG_FORMAT: Literal["json", "console"] = _log_format  # type: ignore[assignment]

    def _load_classification_settings(self) -> None:
        self.CLASSIFY_PERSON_FIELD_ID = self._get_optional_int_env(
            "CLASSIFY_PERSON_FIELD_ID"
        )
        self.CLASSIFY_DEFAULT_COUNTRY_TAG = os.getenv(
            "CLASSIFY_DEFAULT_COUNTRY_TAG", ""
        ).strip()
        self.CLASSIFY_MAX_CHARS = int(os.getenv("CLASSIFY_MAX_CHARS", "0"))
        self.CLASSIFY_MAX_TOKENS = max(0, int(os.getenv("CLASSIFY_MAX_TOKENS", "0")))
        self.CLASSIFY_TAG_LIMIT = max(0, int(os.getenv("CLASSIFY_TAG_LIMIT", "5")))
        self.CLASSIFY_TAXONOMY_LIMIT = max(
            0, int(os.getenv("CLASSIFY_TAXONOMY_LIMIT", "100"))
        )
        self.CLASSIFY_MAX_PAGES = max(0, int(os.getenv("CLASSIFY_MAX_PAGES", "3")))
        self.CLASSIFY_TAIL_PAGES = max(0, int(os.getenv("CLASSIFY_TAIL_PAGES", "2")))
        self.CLASSIFY_HEADERLESS_CHAR_LIMIT = max(
            0, int(os.getenv("CLASSIFY_HEADERLESS_CHAR_LIMIT", "15000"))
        )

    def _load_index_settings(self) -> None:
        """Load indexer and store settings (semantic-search spec §10)."""
        self.INDEX_DB_PATH = os.getenv("INDEX_DB_PATH", _DEFAULT_INDEX_DB_PATH)
        self.EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        self.EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
        self.EMBEDDING_MAX_CONCURRENT = int(os.getenv("EMBEDDING_MAX_CONCURRENT", "4"))
        self.RECONCILE_INTERVAL = int(os.getenv("RECONCILE_INTERVAL", "300"))
        self.DELETION_SWEEP_INTERVAL = int(os.getenv("DELETION_SWEEP_INTERVAL", "3600"))
        self.CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "2000"))
        self.CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "256"))

    def _load_search_settings(self) -> None:
        """Load search-server settings (semantic-search spec §10).

        Provider-aware defaults for SEARCH_PLANNER_MODEL and SEARCH_ANSWER_MODEL
        mirror the _load_llm_settings pattern: cheaper/faster model for planning,
        stronger model for answer synthesis.
        """
        self.SEARCH_TOP_K = int(os.getenv("SEARCH_TOP_K", "10"))
        self.SEARCH_MAX_REFINEMENTS = int(os.getenv("SEARCH_MAX_REFINEMENTS", "1"))

        if self.LLM_PROVIDER == "ollama":
            default_planner_model = "gemma3:12b"
            default_answer_model = "gemma3:27b"
        else:
            default_planner_model = "gpt-5.4-mini"
            default_answer_model = "gpt-5.4"

        self.SEARCH_PLANNER_MODEL = os.getenv("SEARCH_PLANNER_MODEL", default_planner_model)
        self.SEARCH_ANSWER_MODEL = os.getenv("SEARCH_ANSWER_MODEL", default_answer_model)
        self.SEARCH_SERVER_HOST = os.getenv("SEARCH_SERVER_HOST", "0.0.0.0")
        self.SEARCH_SERVER_PORT = int(os.getenv("SEARCH_SERVER_PORT", "8080"))
        # Empty default is intentional — the search server validates non-empty at
        # preflight; the indexer does not require this key (spec §10, §10.1).
        self.SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
        self.SEARCH_SESSION_TTL = int(os.getenv("SEARCH_SESSION_TTL", "604800"))
        self.SEARCH_MAX_CONCURRENT = int(os.getenv("SEARCH_MAX_CONCURRENT", "4"))

    def _get_required_env(self, var_name: str) -> str:
        value = os.getenv(var_name)
        if value is None:
            raise ValueError(f"Required environment variable '{var_name}' is not set.")
        return value

    def _get_optional_int_env(self, var_name: str, default: int | None = None) -> int | None:
        value = os.getenv(var_name)
        if value is None:
            return default
        value = value.strip()
        if not value:
            return default
        return int(value)

    def _get_optional_positive_int_env(
        self, var_name: str, default: int | None = None
    ) -> int | None:
        value = self._get_optional_int_env(var_name, default)
        if value is not None and value <= 0:
            return None
        return value

    def _get_csv_env(
        self,
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

    def _get_bool_env(self, var_name: str, default: bool) -> bool:
        value = os.getenv(var_name)
        if value is None:
            return default
        value = value.strip().lower()
        if value in ("1", "true", "yes", "y", "on"):
            return True
        if value in ("0", "false", "no", "n", "off"):
            return False
        raise ValueError(f"{var_name} must be a boolean value.")
