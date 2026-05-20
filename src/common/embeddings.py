"""Batched, retried OpenAI embedding client.

Public surface
--------------
``EmbeddingClient``  — the sole embedding entry point for the codebase.
``EmbeddingError``   — raised on a non-retryable failure.

All embedding calls in the project must go through ``EmbeddingClient``; a
bare ``openai.embeddings.create`` call outside this module is a guidelines
violation (CODE_GUIDELINES §8.1, §17.8).

Concurrency
-----------
``EMBEDDING_MAX_CONCURRENT`` controls how many in-flight embedding requests are
allowed simultaneously.  ``0`` means unbounded, mirroring the
``LLM_MAX_CONCURRENT`` pattern in :mod:`common.concurrency`.  A non-zero value
creates a :class:`threading.Semaphore` that every ``_embed_batch`` call acquires
before touching the network.

Batching
--------
The OpenAI embedding endpoint caps requests at ~2048 inputs; we use a
conservative ``_BATCH_SIZE`` of 96 so a single document's worth of chunks is
always sent in one request and the cap is never approached.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import TYPE_CHECKING

import openai
import structlog

from .llm import get_openai_client
from .retry import retry

if TYPE_CHECKING:
    from common.config import Settings

log = structlog.get_logger(__name__)

# Conservative cap well below OpenAI's 2048-input hard limit; keeps individual
# request sizes sensible and leaves headroom for future model limits.
_BATCH_SIZE = 96

_RETRYABLE_EMBEDDING_EXCEPTIONS = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class EmbeddingError(Exception):
    """Non-retryable failure from the embedding API.

    Raised when the embedding call fails with an error that is not in the
    retryable set (e.g. ``AuthenticationError``, ``BadRequestError``).  The
    original exception is always chained via ``raise EmbeddingError(...) from
    original`` so the traceback is preserved.
    """


class EmbeddingClient:
    """Batched, retried embedding client backed by the shared OpenAI singleton.

    Args:
        settings: The daemon ``Settings`` instance.  Must expose
            ``EMBEDDING_MODEL``, ``EMBEDDING_MAX_CONCURRENT``,
            ``MAX_RETRIES``, and ``MAX_RETRY_BACKOFF_SECONDS``.

    The client stores ``settings`` as ``self.settings`` so that the
    :func:`~common.retry.retry` decorator — which reads ``self.settings`` — is
    applicable to instance methods.
    """

    def __init__(self, settings: Settings) -> None:
        # ``self.settings`` must be the attribute name; the @retry decorator
        # reads it via the HasRetrySettings protocol.
        self.settings = settings
        self._client = get_openai_client()
        # Treat 0 as unbounded, exactly as llm.py treats LLM_MAX_CONCURRENT.
        if settings.EMBEDDING_MAX_CONCURRENT > 0:
            self._semaphore: threading.Semaphore | None = threading.Semaphore(
                settings.EMBEDDING_MAX_CONCURRENT
            )
        else:
            self._semaphore = None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a sequence of texts, returning one vector per input in order.

        Splits ``texts`` into batches of at most ``_BATCH_SIZE`` inputs,
        dispatches each batch via :meth:`_embed_batch`, and assembles the
        results in the original order.

        Args:
            texts: The strings to embed.  May be empty.

        Returns:
            A list of float vectors, one per element of ``texts``, in the same
            order.

        Raises:
            EmbeddingError: On a non-retryable API failure.
            openai.APIConnectionError / RateLimitError / …: On a retryable
                failure that exhausts all retries.
        """
        if not texts:
            return []

        vectors: list[list[float]] = []
        for batch_start in range(0, len(texts), _BATCH_SIZE):
            batch = list(texts[batch_start : batch_start + _BATCH_SIZE])
            batch_vectors = self._embed_batch(batch)
            vectors.extend(batch_vectors)

        return vectors

    @retry(retryable_exceptions=_RETRYABLE_EMBEDDING_EXCEPTIONS)
    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        """Send a single batch to the OpenAI embedding endpoint.

        This method is decorated with :func:`~common.retry.retry` so transient
        errors (connection drops, rate limits, 5xx) are retried with exponential
        backoff.  The semaphore is acquired around the API call to bound
        concurrency.

        Args:
            batch: A non-empty list of strings (at most ``_BATCH_SIZE`` items).

        Returns:
            Vectors in the same order as ``batch``.

        Raises:
            EmbeddingError: On a non-retryable API failure.
        """
        try:
            if self._semaphore is not None:
                self._semaphore.acquire()
                try:
                    response = self._client.embeddings.create(
                        model=self.settings.EMBEDDING_MODEL,
                        input=batch,
                    )
                finally:
                    self._semaphore.release()
            else:
                response = self._client.embeddings.create(
                    model=self.settings.EMBEDDING_MODEL,
                    input=batch,
                )
        except _RETRYABLE_EMBEDDING_EXCEPTIONS:
            # Re-raise so the @retry decorator can act on it.
            raise
        except Exception as exc:
            raise EmbeddingError(
                f"Non-retryable embedding failure for batch of {len(batch)} texts"
            ) from exc

        # The API returns items in arbitrary order; sort by index to guarantee
        # the output matches the input order.
        items = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in items]
