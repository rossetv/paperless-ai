"""Environment-variable configuration for the OCR and classification daemons."""

from __future__ import annotations

import os
from typing import Literal


class Settings:

    # --- Paperless-ngx API Configuration ---
    PAPERLESS_URL: str
    PAPERLESS_TOKEN: str

    # --- LLM Provider Configuration ---
    LLM_PROVIDER: Literal["openai", "ollama"]
    OLLAMA_BASE_URL: str | None
    OPENAI_API_KEY: str | None

    # --- Model Selection ---
    AI_MODELS: list[str]
    OCR_REFUSAL_MARKERS: list[str]
    OCR_INCLUDE_PAGE_MODELS: bool

    # --- Paperless-ngx Tag IDs ---
    PRE_TAG_ID: int
    POST_TAG_ID: int
    OCR_PROCESSING_TAG_ID: int | None

    # --- Classification Tag IDs ---
    CLASSIFY_PRE_TAG_ID: int
    CLASSIFY_POST_TAG_ID: int | None
    CLASSIFY_PROCESSING_TAG_ID: int | None
    ERROR_TAG_ID: int | None

    # --- Daemon Configuration ---
    POLL_INTERVAL: int
    MAX_RETRIES: int
    MAX_RETRY_BACKOFF_SECONDS: int
    REQUEST_TIMEOUT: int
    LLM_MAX_CONCURRENT: int

    # --- Image Processing Configuration ---
    OCR_DPI: int
    OCR_MAX_SIDE: int
    PAGE_WORKERS: int
    DOCUMENT_WORKERS: int

    # --- Logging ---
    LOG_LEVEL: str
    LOG_FORMAT: Literal["json", "console"]

    # --- Constants ---
    REFUSAL_MARK: str = "CHATGPT REFUSED TO TRANSCRIBE"

    # --- Classification Configuration ---
    CLASSIFY_PERSON_FIELD_ID: int | None
    CLASSIFY_DEFAULT_COUNTRY_TAG: str
    CLASSIFY_MAX_CHARS: int
    CLASSIFY_MAX_TOKENS: int
    CLASSIFY_TAG_LIMIT: int
    CLASSIFY_TAXONOMY_LIMIT: int
    CLASSIFY_MAX_PAGES: int
    CLASSIFY_TAIL_PAGES: int
    CLASSIFY_HEADERLESS_CHAR_LIMIT: int

    def __init__(self):
        """Loads settings from environment variables and performs validation."""
        self._load_api_settings()
        self._load_llm_settings()
        self._load_tag_settings()
        self._load_daemon_settings()
        self._load_image_settings()
        self._load_logging_settings()
        self._load_classification_settings()

    def _load_api_settings(self) -> None:
        self.PAPERLESS_URL = os.getenv("PAPERLESS_URL", "http://paperless:8000").rstrip(
            "/"
        )
        self.PAPERLESS_TOKEN = self._get_required_env("PAPERLESS_TOKEN")

    def _load_llm_settings(self) -> None:
        self.LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
        if self.LLM_PROVIDER not in ("openai", "ollama"):
            raise ValueError("LLM_PROVIDER must be 'openai' or 'ollama'")

        if self.LLM_PROVIDER == "ollama":
            self.OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1/")
            self.OPENAI_API_KEY = None
            default_ai_models = ["gemma3:27b", "gemma3:12b"]
        else:
            self.OLLAMA_BASE_URL = None
            self.OPENAI_API_KEY = self._get_required_env("OPENAI_API_KEY")
            default_ai_models = ["gpt-5-mini", "gpt-5.2", "o4-mini"]
        self.AI_MODELS = self._get_model_list("AI_MODELS", default_ai_models)
        default_ocr_refusal_markers = [
            "i can't assist",
            "i cannot assist",
            "i can't help with transcrib",
            "i cannot help with transcrib",
            self.REFUSAL_MARK,
        ]
        self.OCR_REFUSAL_MARKERS = [
            marker.lower()
            for marker in self._get_list_env(
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
        self.CLASSIFY_PRE_TAG_ID = self._get_optional_int_env(
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
        log_format = os.getenv("LOG_FORMAT", "console")
        if log_format not in ("json", "console"):
            raise ValueError("LOG_FORMAT must be 'json' or 'console'")
        self.LOG_FORMAT = log_format

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

    def _get_model_list(self, var_name: str, default: list[str]) -> list[str]:
        """
        Get a list of models from a comma-separated env var, falling back to defaults.

        The order is preserved and represents the fallback sequence.
        """
        value = os.getenv(var_name)
        if value is None:
            return [model for model in default if model]
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if not parts:
            raise ValueError(f"{var_name} must contain at least one model name.")
        return parts

    def _get_list_env(self, var_name: str, default: list[str]) -> list[str]:
        """
        Get a list of values from a comma-separated env var, falling back to defaults.
        """
        value = os.getenv(var_name)
        if value is None:
            return [item for item in default if item]
        return [part.strip() for part in value.split(",") if part.strip()]

    def _get_bool_env(self, var_name: str, default: bool) -> bool:
        """
        Get a boolean env var with common truthy/falsey values.
        """
        value = os.getenv(var_name)
        if value is None:
            return default
        value = value.strip().lower()
        if value in ("1", "true", "yes", "y", "on"):
            return True
        if value in ("0", "false", "no", "n", "off"):
            return False
        raise ValueError(f"{var_name} must be a boolean value.")
