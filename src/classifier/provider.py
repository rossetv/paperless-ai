"""OpenAI-compatible classification provider with model fallback and parameter compatibility."""

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
    """Classifies document text using OpenAI-compatible chat completions."""

    _STAT_KEYS = (
        "attempts", "api_errors", "invalid_json", "fallback_successes",
        "temperature_retries", "response_format_retries", "max_tokens_retries",
    )

    def __init__(self, settings: Settings):
        self.settings = settings
        self._init_stats()

    def _supports_temperature(self, model: str) -> bool:
        # OpenAI's GPT-5 series does not accept a temperature parameter and
        # returns 400 if one is supplied.  This prefix check avoids a wasted
        # round-trip for known-unsupported models; unknown models will still be
        # handled gracefully by _create_with_compat's parameter-stripping logic.
        return not model.startswith("gpt-5")

    def _is_temperature_error(self, error: openai.BadRequestError) -> bool:
        message = str(error).lower()
        return "temperature" in message and "unsupported" in message

    def _is_response_format_error(self, error: openai.BadRequestError) -> bool:
        message = str(error).lower()
        return "response_format" in message or "json_schema" in message

    def _is_max_tokens_error(self, error: openai.BadRequestError) -> bool:
        message = str(error).lower()
        return "max_tokens" in message or "max tokens" in message

    def _response_format(self) -> dict | None:
        if self.settings.LLM_PROVIDER != "openai":
            return None
        return {"type": "json_schema", "json_schema": CLASSIFICATION_JSON_SCHEMA}

    # Strippable parameters: (param_key, error_detector_method, stat_key).
    _COMPAT_PARAMS: tuple[tuple[str, str, str], ...] = (
        ("temperature", "_is_temperature_error", "temperature_retries"),
        ("response_format", "_is_response_format_error", "response_format_retries"),
        ("max_tokens", "_is_max_tokens_error", "max_tokens_retries"),
    )

    def _create_with_compat(self, params: dict, model: str):
        """Call the chat completion API, retrying after stripping unsupported params.

        Ollama and some OpenAI models reject parameters they don't understand
        (``temperature``, ``response_format``, ``max_tokens``).  When we get a
        ``400 Bad Request`` whose message names the offending parameter, we
        remove it and retry the same model — up to ``len(_COMPAT_PARAMS)`` times.
        """
        compat_retries = 0
        while True:
            try:
                self._stats.inc("attempts")
                return self._create_completion(**params)
            except openai.BadRequestError as e:
                if compat_retries < len(self._COMPAT_PARAMS):
                    stripped = self._try_strip_compat_param(e, params, model)
                    if stripped is not None:
                        params = stripped
                        compat_retries += 1
                        continue
                log.warning("Classification request rejected", model=model, error=e)
                self._stats.inc("api_errors")
                return None
            except openai.APIError as e:
                log.warning("Classification model failed", model=model, error=e)
                self._stats.inc("api_errors")
                return None

    def _try_strip_compat_param(
        self, error: openai.BadRequestError, params: dict, model: str,
    ) -> dict | None:
        """Strip the first unsupported parameter from *params*, or return ``None``."""
        for param_key, detector_name, stat_key in self._COMPAT_PARAMS:
            if param_key in params and getattr(self, detector_name)(error):
                log.warning(
                    "Model does not support parameter; retrying without it",
                    model=model,
                    parameter=param_key,
                )
                self._stats.inc(stat_key)
                stripped = dict(params)
                del stripped[param_key]
                return stripped
        return None

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
                    self._stats.inc("fallback_successes")
                return result, model
            except (json.JSONDecodeError, ValueError) as e:
                log.warning(
                    "Classification response invalid",
                    model=model,
                    error=str(e),
                )
                self._stats.inc("invalid_json")
                continue

        log.error("All classification models failed")
        return None, ""

    def _build_user_message(
        self,
        text: str,
        correspondents: list[str],
        document_types: list[str],
        tags: list[str],
        truncation_note: str | None,
    ) -> str:
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


