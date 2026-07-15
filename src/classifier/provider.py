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
from common.llm import OpenAIChatMixin, service_tier_params, unique_models
from common.prompt_fences import build_data_fence
from .prompts import (
    CLASSIFICATION_JSON_SCHEMA,
    CLASSIFICATION_PROMPT,
    DEFAULT_CLASSIFY_TEMPERATURE,
    DOCUMENT_FENCE_LABEL,
)
from .result import ClassificationResult, parse_classification_response
from .taxonomy import TaxonomyContext

log = structlog.get_logger(__name__)


class ClassificationProvider(OpenAIChatMixin):
    """Classifies document text using OpenAI-compatible chat completions."""

    # reasoning_effort strips are intentionally not counted here — the provider
    # opts into only the three param-retry counters it surfaces to the caller.
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

    @property
    def _provider(self) -> str:
        """Route classification's chat calls to the classify step's provider."""
        return self.settings.CLASSIFY_PROVIDER

    def classify_text(
        self,
        text: str,
        taxonomy: TaxonomyContext,
        truncation_note: str | None = None,
    ) -> tuple[ClassificationResult | None, str]:
        """
        Classify OCR text with taxonomy context, returning ``(result, model_used)``.

        Tries each model in ``settings.CLASSIFY_MODELS`` in order.  Returns
        ``(None, "")`` when all models fail.
        """
        if not text.strip():
            log.warning("classification.empty_content")
            return None, ""

        user_content = self._build_user_message(text, taxonomy, truncation_note)
        messages = [
            {"role": "system", "content": CLASSIFICATION_PROMPT},
            {"role": "user", "content": user_content},
        ]

        models_to_try = unique_models(self.settings.CLASSIFY_MODELS)
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
                    "classification.response_invalid",
                    model=model,
                    error=str(error),
                )
                self._stats.inc("invalid_json")
                continue

        log.error("classification.all_models_failed")
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
        # transcription is always the final segment, wrapped in a fresh
        # per-request nonce fence so untrusted document text cannot forge the
        # boundary or be read as an instruction (CODE_GUIDELINES §10.2 — the
        # system prompt tells the model that everything between the matching
        # nonce fences is data only). The nonce is generated here, after the
        # content exists, so the content cannot contain it; it lives only in
        # this per-document suffix, never in the cacheable prefix above.
        if truncation_note:
            parts.append(truncation_note)
        fence = build_data_fence(label=DOCUMENT_FENCE_LABEL)
        parts.append(fence.wrap(text))

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

        When ``CLASSIFY_TAXONOMY_LIMIT`` is a positive cap, a trailing note tells
        the model the lists are the most-used names only and the archive may hold
        more — so if the right name is not shown it should still give the correct
        name (the cache resolves or creates it afterwards).
        """
        limit = self.settings.CLASSIFY_TAXONOMY_LIMIT
        cap_note = (
            f"\n\nNote: each list above shows only the {limit} most-used names — "
            "the archive may contain more. If the right one is not shown, give "
            "the correct name anyway; it will be reused or created."
            if limit > 0
            else ""
        )
        return (
            "Existing correspondents (prefer these when possible):\n"
            f"{json.dumps(taxonomy.correspondents, ensure_ascii=True)}\n\n"
            "Existing document types (prefer these when possible):\n"
            f"{json.dumps(taxonomy.document_types, ensure_ascii=True)}\n\n"
            "Existing tags (prefer these when possible):\n"
            f"{json.dumps(taxonomy.tags, ensure_ascii=True)}"
            f"{cap_note}"
        )

    def _build_params(
        self, model: str, messages: list[dict[str, str]]
    ) -> dict[str, object]:
        """Build the chat-completion params, always requesting temperature.

        ``reasoning_effort`` and the ``json_schema`` response format are
        OpenAI-only, so both are gated on the classify step's *own* provider:
        omitted entirely when ``CLASSIFY_PROVIDER`` is not ``openai`` (an Ollama
        step never pays the wasted 400 round-trip the compat layer would
        otherwise need to discover the rejection). On OpenAI a model that still
        rejects one has it stripped/cached by :meth:`_create_with_compat`.
        ``max_tokens`` is requested only when ``CLASSIFY_MAX_TOKENS > 0``.
        ``service_tier`` is likewise provider-gated like ``reasoning_effort``;
        flex floors the per-call timeout (see :func:`common.llm.service_tier_params`).
        """
        params: dict[str, object] = {
            "model": model,
            "messages": messages,
            "timeout": self.settings.REQUEST_TIMEOUT,
            "temperature": DEFAULT_CLASSIFY_TEMPERATURE,
        }
        if self.settings.CLASSIFY_PROVIDER == "openai":
            params["reasoning_effort"] = self.settings.CLASSIFY_REASONING_EFFORT
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": CLASSIFICATION_JSON_SCHEMA,
            }
            params.update(
                service_tier_params(
                    flex_enabled=self.settings.OPENAI_FLEX_TIER,
                    request_timeout=self.settings.REQUEST_TIMEOUT,
                )
            )
        if self.settings.CLASSIFY_MAX_TOKENS > 0:
            params["max_tokens"] = self.settings.CLASSIFY_MAX_TOKENS
        return params
