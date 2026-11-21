"""Batched, retried embedding client; every embedding call goes through it.

Callers catch ``EMBEDDING_FAILURE_EXCEPTIONS`` instead of importing ``openai``.
``EMBEDDING_PROVIDER`` is independent of ``LLM_PROVIDER`` (default ``openai``),
so the client builds its own ``openai.OpenAI`` rather than sharing the chat
singleton; ``ollama`` points it at ``OLLAMA_BASE_URL``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import openai
import structlog

from .concurrency import ConcurrencyGuard
from .retry import retry

if TYPE_CHECKING:
    from .config import Settings

log = structlog.get_logger(__name__)

# Well below OpenAI's 2048-input limit; a typical document fits in one request.
_BATCH_SIZE = 96

_RETRYABLE_EMBEDDING_EXCEPTIONS = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class EmbeddingError(Exception):
    """Non-retryable failure from the embedding API (e.g. bad key, 400)."""


# What ``embed`` can raise: the non-retryable wrapper, or a retryable
# ``openai.APIError`` once retries are exhausted.
EMBEDDING_FAILURE_EXCEPTIONS: tuple[type[Exception], ...] = (
    EmbeddingError,
    openai.APIError,
)

# Ollama ignores the key, but the SDK requires a non-empty string.
_OLLAMA_PLACEHOLDER_API_KEY = "dummy"


def _build_embedding_client(settings: Settings) -> openai.OpenAI:
    """Build the ``openai.OpenAI`` client for ``settings.EMBEDDING_PROVIDER``.

    The explicit timeout makes a hung provider fail fast into retry instead of
    blocking on the SDK's ~600 s default.
    """
    if settings.EMBEDDING_PROVIDER == "ollama":
        return openai.OpenAI(
            api_key=_OLLAMA_PLACEHOLDER_API_KEY,
            base_url=settings.OLLAMA_BASE_URL,
            timeout=settings.REQUEST_TIMEOUT,
        )
    return openai.OpenAI(
        api_key=settings.OPENAI_API_KEY, timeout=settings.REQUEST_TIMEOUT
    )


class EmbeddingClient:
    """Batched, retried embedding client, provider-aware via ``EMBEDDING_PROVIDER``."""

    def __init__(self, settings: Settings) -> None:
        # The @retry decorator reads ``self.settings``; do not rename it.
        self.settings = settings
        self._client = _build_embedding_client(settings)
        self._concurrency = ConcurrencyGuard(settings.EMBEDDING_MAX_CONCURRENT)

    def close(self) -> None:
        """Close the underlying httpx connection pool; the client is unusable after."""
        self._client.close()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed *texts*, returning one vector per input in order.

        Raises:
            EmbeddingError: On a non-retryable API failure.
            openai.APIError: On a retryable failure that exhausts all retries.
        """
        if not texts:
            return []

        # The first batch failure raises: a document embeds wholly or not at
        # all, so a caller is never handed a short vector list.
        vectors: list[list[float]] = []
        for batch_index, batch_start in enumerate(range(0, len(texts), _BATCH_SIZE)):
            batch = list(texts[batch_start : batch_start + _BATCH_SIZE])
            batch_vectors = self._embed_batch(batch, batch_index)
            vectors.extend(batch_vectors)

        return vectors

    @retry(retryable_exceptions=_RETRYABLE_EMBEDDING_EXCEPTIONS)
    def _embed_batch(self, batch: list[str], batch_index: int) -> list[list[float]]:
        """Embed one batch; transient errors are retried with backoff.

        *batch_index* goes into the error message so an operator can locate the
        offending chunk window.
        """
        try:
            with self._concurrency.acquire():
                response = self._client.embeddings.create(
                    model=self.settings.EMBEDDING_MODEL,
                    input=batch,
                    dimensions=self.settings.EMBEDDING_DIMENSIONS,
                )
        except _RETRYABLE_EMBEDDING_EXCEPTIONS:
            raise
        except openai.OpenAIError as exc:
            # Only SDK errors: a programming bug must surface unmasked.
            raise EmbeddingError(
                f"Non-retryable embedding failure on batch {batch_index} "
                f"({len(batch)} texts)"
            ) from exc

        # The API may return items out of order.
        items = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in items]
