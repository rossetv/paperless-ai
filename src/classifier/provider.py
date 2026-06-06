"""OpenAI-compatible classification provider with model fallback.

Parameter compatibility (stripping a param a model rejects, with a per-model
process cache) is handled by the shared :class:`~common.llm.OpenAIChatMixin`
adaptive layer — this provider no longer carries its own. It always *requests*
temperature and (for OpenAI) a ``json_schema`` response format; the shared
layer strips whatever a given model rejects and caches the discovery.
"""

from __future__ import annotations

import json

import structlog

from common.config import Settings
from common.llm import OpenAIChatMixin, unique_models
from .prompts import (
    CLASSIFICATION_JSON_SCHEMA,
    CLASSIFICATION_PROMPT,
    DEFAULT_CLASSIFY_TEMPERATURE,
    DOCUMENT_CONTENT_DELIMITER,
)
from .result import ClassificationResult, parse_classification_response
from .taxonomy import TaxonomyContext

log = structlog.get_logger(__name__)


class ClassificationProvider(OpenAIChatMixin):
    """Classifies document text using OpenAI-compatible chat completions."""

    _STAT_KEYS = (
        "attempts",
        "api_errors",
        "invalid_json",
        "fallback_successes",
        "temperature_retries",
        "response_format_retries",
        "max_tokens_retries",
    )

    def __init__(self, settings: Settings):
        self.settings = settings
        self._init_stats()

    def _response_format(self) -> dict | None:
        if self.settings.LLM_PROVIDER != "openai":
            return None
        return {"type": "json_schema", "json_schema": CLASSIFICATION_JSON_SCHEMA}

    def classify_text(
        self,
        text: str,
        taxonomy: TaxonomyContext,
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

        user_content = self._build_user_message(text, taxonomy, truncation_note)
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
            except (json.JSONDecodeError, ValueError) as error:
                log.warning(
                    "Classification response invalid",
                    model=model,
                    error=str(error),
                )
                self._stats.inc("invalid_json")
                continue

        log.error("All classification models failed")
        return None, ""

    def _build_user_message(
        self,
        text: str,
        taxonomy: TaxonomyContext,
        truncation_note: str | None,
    ) -> str:
        # STABLE PREFIX — byte-identical across every document in a batch, so
        # OpenAI's prompt cache keys on it. Tag-limit guidance, then the three
        # taxonomy lists. Nothing per-document appears above this point.
        parts: list[str] = [
            self._tag_limit_guidance(),
            self._taxonomy_block(taxonomy),
        ]

        # VARIABLE SUFFIX — per-document content, last so it never shifts the
        # cacheable prefix. The note (if any) precedes the transcription; the
        # transcription is always the final segment, fenced below the
        # data-isolation delimiter so untrusted document text cannot be read as
        # an instruction (CODE_GUIDELINES §10.2 — the system prompt tells the
        # model to treat everything after this exact line as data only).
        if truncation_note:
            parts.append(truncation_note)
        parts.append(f"{DOCUMENT_CONTENT_DELIMITER}\n{text}")

        return "\n\n".join(parts)

    def _tag_limit_guidance(self) -> str:
        """Return the stable tag-count instruction for the cacheable prefix."""
        if self.settings.CLASSIFY_TAG_LIMIT == 0:
            return (
                "Tag limit: return no optional tags. Required tags (year, "
                "country, model, error) are added automatically."
            )
        return (
            f"Tag limit: return no more than {self.settings.CLASSIFY_TAG_LIMIT} "
            "optional tags. Required tags (year, country, model, error) are "
            "added automatically."
        )

    def _taxonomy_block(self, taxonomy: TaxonomyContext) -> str:
        """Return the stable taxonomy lists for the cacheable prefix.

        No per-document content is interpolated here, so the block is identical
        for every document in a batch — which is what lets OpenAI cache it.
        """
        return (
            "Existing correspondents (prefer these when possible):\n"
            f"{json.dumps(taxonomy.correspondents, ensure_ascii=True)}\n\n"
            "Existing document types (prefer these when possible):\n"
            f"{json.dumps(taxonomy.document_types, ensure_ascii=True)}\n\n"
            "Existing tags (prefer these when possible):\n"
            f"{json.dumps(taxonomy.tags, ensure_ascii=True)}"
        )

    def _build_params(self, model: str, messages: list[dict]) -> dict:
        """Build the chat-completion params, always requesting temperature.

        Temperature, ``reasoning_effort`` and (for OpenAI) the ``json_schema``
        response format are always *requested*; a model that rejects any of them
        has it stripped and cached by the shared :meth:`_create_with_compat`
        layer, so it is never *persistently* sent to a model that does not
        accept it. ``max_tokens`` is requested only when
        ``CLASSIFY_MAX_TOKENS > 0`` (default 0 → omitted).
        """
        params: dict = {
            "model": model,
            "messages": messages,
            "timeout": self.settings.REQUEST_TIMEOUT,
            "temperature": DEFAULT_CLASSIFY_TEMPERATURE,
            "reasoning_effort": self.settings.CLASSIFY_REASONING_EFFORT,
        }
        if self.settings.CLASSIFY_MAX_TOKENS > 0:
            params["max_tokens"] = self.settings.CLASSIFY_MAX_TOKENS
        response_format = self._response_format()
        if response_format is not None:
            params["response_format"] = response_format
        return params
