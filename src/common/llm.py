"""
Shared LLM helpers.

This module centralizes the OpenAI-compatible chat completion call so OCR and
classification reuse the same retry behavior and logging patterns.
"""

import openai

from .retry import retry

RETRYABLE_OPENAI_EXCEPTIONS = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class OpenAIChatMixin:
    """
    Mixin providing a retried OpenAI-compatible chat completion call.

    The mixin expects ``self.settings`` to expose ``MAX_RETRIES`` and
    ``MAX_RETRY_BACKOFF_SECONDS`` for the retry decorator.
    """

    @retry(retryable_exceptions=RETRYABLE_OPENAI_EXCEPTIONS)
    def _create_completion(self, **kwargs):
        """Call the OpenAI-compatible chat completion API with retries."""
        return openai.chat.completions.create(**kwargs)


def unique_models(models: list[str]) -> list[str]:
    """Deduplicate a model list while preserving insertion order."""
    seen: set[str] = set()
    unique: list[str] = []
    for model in models:
        if model not in seen:
            seen.add(model)
            unique.append(model)
    return unique
