"""
Classification Provider
=======================

The :class:`ClassificationProvider` calls an OpenAI-compatible chat completion
API to classify a document's OCR text.  It handles:

- Building the user message (taxonomy context + truncation notes + text).
- Model fallback: tries each model in ``AI_MODELS`` until one succeeds.
- Parameter compatibility: removes ``temperature``, ``response_format``, or
  ``max_tokens`` on the fly if the model rejects them.
- JSON response parsing via :func:`classifier.result.parse_classification_response`.
"""

from __future__ import annotations

import json

import openai
import structlog

from common.config import Settings
from common.llm import OpenAIChatMixin, unique_models
from .prompts import (
    CLASSIFICATION_JSON_SCHEMA,
    CLASSIFICATION_PROMPT,
    DEFAULT_CLASSIFY_TEMPERATURE,
)
from .result import ClassificationResult, parse_classification_response

log = structlog.get_logger(__name__)


class ClassificationProvider(OpenAIChatMixin):
    """
    Classification provider that uses OpenAI-compatible chat completions.

    One instance is created per document.  Call :meth:`classify_text` with the
    OCR content and taxonomy context lists.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._stats: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def _reset_stats(self) -> None:
        """Reset per-call classification counters."""
        self._stats = {
            "attempts": 0,
            "api_errors": 0,
            "invalid_json": 0,
            "fallback_successes": 0,
            "temperature_retries": 0,
            "response_format_retries": 0,
            "max_tokens_retries": 0,
        }

    def get_stats(self) -> dict:
        """Return a snapshot of classification stats for this provider instance."""
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Parameter compatibility helpers
    # ------------------------------------------------------------------

    def _supports_temperature(self, model: str) -> bool:
        """Return True if the model is known to support a temperature parameter."""
        return not model.startswith("gpt-5")

    def _is_temperature_error(self, error: openai.BadRequestError) -> bool:
        """Detect ``400 Bad Request`` caused by an unsupported ``temperature``."""
        message = str(error).lower()
        return "temperature" in message and "unsupported" in message

    def _is_response_format_error(self, error: openai.BadRequestError) -> bool:
        """Detect ``400 Bad Request`` caused by an unsupported ``response_format``."""
        message = str(error).lower()
        return "response_format" in message or "json_schema" in message

    def _is_max_tokens_error(self, error: openai.BadRequestError) -> bool:
        """Detect ``400 Bad Request`` caused by an unsupported ``max_tokens``."""
        message = str(error).lower()
        return "max_tokens" in message or "max tokens" in message

    def _response_format(self) -> dict | None:
        """Return a ``response_format`` payload when the provider supports it."""
        if self.settings.LLM_PROVIDER != "openai":
            return None
        return {"type": "json_schema", "json_schema": CLASSIFICATION_JSON_SCHEMA}

    # ------------------------------------------------------------------
    # Compatibility wrapper
    # ------------------------------------------------------------------

    # Maximum number of compatibility retries before giving up.  There are
    # at most three strippable parameters (temperature, response_format,
    # max_tokens), so 3 is the theoretical maximum.
    _MAX_COMPAT_RETRIES: int = 3

    def _create_with_compat(self, params: dict, model: str):
        """Call the chat completion API, retrying after stripping unsupported params.

        Ollama and some OpenAI models reject parameters they don't understand
        (``temperature``, ``response_format``, ``max_tokens``).  When we get a
        ``400 Bad Request`` whose message names the offending parameter, we
        remove it and retry the same model — up to one retry per parameter,
        bounded by :attr:`_MAX_COMPAT_RETRIES` to avoid infinite loops.

        Args:
            params: Keyword arguments for the chat completion call.
            model: Model name (for logging context).

        Returns:
            The API response, or ``None`` if all attempts fail.
        """
        compat_retries = 0
        while True:
            try:
                self._stats["attempts"] += 1
                return self._create_completion(**params)
            except openai.BadRequestError as e:
                # Try compat adjustments only while below the retry bound.
                if compat_retries < self._MAX_COMPAT_RETRIES:
                    if self._is_temperature_error(e) and "temperature" in params:
                        log.warning(
                            "Model does not support temperature; retrying with defaults",
                            model=model,
                        )
                        self._stats["temperature_retries"] += 1
                        params = dict(params)
                        params.pop("temperature", None)
                        compat_retries += 1
                        continue
                    if self._is_response_format_error(e) and "response_format" in params:
                        log.warning(
                            "Model does not support response_format; retrying without it",
                            model=model,
                        )
                        self._stats["response_format_retries"] += 1
                        params = dict(params)
                        params.pop("response_format", None)
                        compat_retries += 1
                        continue
                    if self._is_max_tokens_error(e) and "max_tokens" in params:
                        log.warning(
                            "Model does not support max_tokens; retrying without it",
                            model=model,
                        )
                        self._stats["max_tokens_retries"] += 1
                        params = dict(params)
                        params.pop("max_tokens", None)
                        compat_retries += 1
                        continue
                # Unrecognized error or compat retries exhausted — give up.
                log.warning("Classification request rejected", model=model, error=e)
                self._stats["api_errors"] += 1
                return None
            except openai.APIError as e:
                log.warning("Classification model failed", model=model, error=e)
                self._stats["api_errors"] += 1
                return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_text(
        self,
        text: str,
        correspondents: list[str],
        document_types: list[str],
        tags: list[str],
        truncation_note: str | None = None,
    ) -> tuple[ClassificationResult | None, str]:
        """
        Classify OCR text with taxonomy context, returning ``(result, model_used)``.

        Tries each model in ``settings.AI_MODELS`` in order.  Returns
        ``(None, "")`` when all models fail.
        """
        if not text.strip():
            log.warning("Document content is empty; skipping classification.")
            return None, ""
        self._reset_stats()

        user_content = self._build_user_message(
            text, correspondents, document_types, tags, truncation_note
        )
        messages = [
            {"role": "system", "content": CLASSIFICATION_PROMPT},
            {"role": "user", "content": user_content},
        ]

        models_to_try = unique_models(self.settings.AI_MODELS)
        primary_model = models_to_try[0] if models_to_try else ""

        for model in models_to_try:
            params = self._build_params(model, messages)
            response = self._create_with_compat(params, model)
            if response is None:
                continue

            try:
                content = response.choices[0].message.content or ""
                result = parse_classification_response(content)
                if model != primary_model:
                    self._stats["fallback_successes"] += 1
                return result, model
            except (json.JSONDecodeError, ValueError) as e:
                log.warning(
                    "Classification response invalid",
                    model=model,
                    error=str(e),
                )
                self._stats["invalid_json"] += 1
                continue

        log.error("All classification models failed")
        return None, ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_user_message(
        self,
        text: str,
        correspondents: list[str],
        document_types: list[str],
        tags: list[str],
        truncation_note: str | None,
    ) -> str:
        """Assemble the user-role message with context and document text."""
        parts: list[str] = []

        if truncation_note:
            parts.append(truncation_note)

        # Tag limit guidance for the LLM
        if self.settings.CLASSIFY_TAG_LIMIT == 0:
            parts.append(
                "Tag limit: return no optional tags. Required tags (year, country, "
                "model, error) are added automatically."
            )
        else:
            parts.append(
                f"Tag limit: return no more than {self.settings.CLASSIFY_TAG_LIMIT} "
                "optional tags. Required tags (year, country, model, error) are added "
                "automatically."
            )

        # Taxonomy context so the LLM can reuse existing items
        parts.append(
            "Existing correspondents (prefer these when possible):\n"
            f"{json.dumps(correspondents, ensure_ascii=True)}\n\n"
            "Existing document types (prefer these when possible):\n"
            f"{json.dumps(document_types, ensure_ascii=True)}\n\n"
            "Existing tags (prefer these when possible):\n"
            f"{json.dumps(tags, ensure_ascii=True)}\n\n"
            "Document transcription:\n"
            f"{text}"
        )

        return "\n\n".join(parts)

    def _build_params(self, model: str, messages: list[dict]) -> dict:
        """Build the keyword arguments for the chat completion call."""
        params: dict = {
            "model": model,
            "messages": messages,
            "timeout": self.settings.REQUEST_TIMEOUT,
        }
        if self._supports_temperature(model):
            params["temperature"] = DEFAULT_CLASSIFY_TEMPERATURE
        if self.settings.CLASSIFY_MAX_TOKENS > 0:
            params["max_tokens"] = self.settings.CLASSIFY_MAX_TOKENS
        response_format = self._response_format()
        if response_format is not None:
            params["response_format"] = response_format
        return params


