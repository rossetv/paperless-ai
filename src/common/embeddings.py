"""Batched, retried OpenAI embedding client.

Public surface
--------------
``EmbeddingClient``            — the sole embedding entry point for the codebase.
``EmbeddingError``             — raised on a non-retryable failure.
``EMBEDDING_FAILURE_EXCEPTIONS`` — the exception tuple a caller catches to
    degrade gracefully when an embedding cannot be produced.

All embedding calls in the project must go through ``EmbeddingClient``; a
bare ``openai.embeddings.create`` call outside this module is a guidelines
violation (CODE_GUIDELINES §8.1, §17.8).  Likewise, a caller that needs to
catch an embedding failure imports ``EMBEDDING_FAILURE_EXCEPTIONS`` rather
than importing ``openai`` to name its error types — the OpenAI SDK stays an
implementation detail of this module.

Embeddings always use OpenAI
----------------------------
Unlike the LLM (chat-completion) calls, which follow the ``LLM_PROVIDER``
setting, embeddings **always** go to OpenAI's ``text-embedding-3-*`` models —
local Ollama embeddings are not supported. ``EmbeddingClient`` therefore builds
its own ``openai.OpenAI`` client pinned to ``OPENAI_API_KEY`` and the default
OpenAI ``base_url``, rather than reusing the provider-dependent shared singleton
in :mod:`common.llm`. Reusing that singleton would, under ``LLM_PROVIDER=ollama``,
silently route embedding requests to the Ollama URL with a dummy key
(CODE_GUIDELINES §10.8, §15.4). ``OPENAI_API_KEY`` is required by ``Settings``
regardless of ``LLM_PROVIDER`` precisely so this client can always be built.

Concurrency
-----------
``EMBEDDING_MAX_CONCURRENT`` controls how many in-flight embedding requests are
allowed simultaneously.  ``0`` means unbounded.  The limit is applied through a
:class:`~common.concurrency.ConcurrencyGuard` — the same "0 means unbounded,
otherwise a bounded semaphore" guard the LLM wrapper uses.

Batching
--------
The OpenAI embedding endpoint caps requests at ~2048 inputs; we use a
conservative ``_BATCH_SIZE`` of 96 so a single document's worth of chunks is
always sent in one request and the cap is never approached.
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


# The exception types ``EmbeddingClient.embed`` can raise that a caller should
# catch to degrade gracefully rather than propagate a 500.  ``EmbeddingError``
# is the non-retryable wrapper (bad/expired key, 400); ``openai.APIError`` is
# the base of the retryable family (connection drop, rate limit, 5xx) that
# ``embed`` re-raises once its own retries are exhausted.  A caller catches
# this tuple so it never has to ``import openai`` to name an error type
# (CODE_GUIDELINES §8.1) — the OpenAI SDK stays internal to this module.
EMBEDDING_FAILURE_EXCEPTIONS: tuple[type[Exception], ...] = (
    EmbeddingError,
    openai.APIError,
)


class EmbeddingClient:
    """Batched, retried embedding client pinned to OpenAI.

    The client owns its own ``openai.OpenAI`` instance, constructed with
    ``settings.OPENAI_API_KEY`` and OpenAI's default ``base_url`` — it does
    **not** use the shared :mod:`common.llm` singleton, because that singleton
    points at the Ollama URL when ``LLM_PROVIDER=ollama`` whereas embeddings
    always go to OpenAI (see the module docstring).

    Args:
        settings: The daemon ``Settings`` instance.  Must expose
            ``OPENAI_API_KEY``, ``EMBEDDING_MODEL``, ``EMBEDDING_DIMENSIONS``,
            ``EMBEDDING_MAX_CONCURRENT``, ``MAX_RETRIES``, and
            ``MAX_RETRY_BACKOFF_SECONDS``.

    The client stores ``settings`` as ``self.settings`` so that the
    :func:`~common.retry.retry` decorator — which reads ``self.settings`` — is
    applicable to instance methods.
    """

    def __init__(self, settings: Settings) -> None:
        # ``self.settings`` must be the attribute name; the @retry decorator
        # reads it via the HasRetrySettings protocol.
        self.settings = settings
        # Pin to OpenAI explicitly: api_key from OPENAI_API_KEY, default
        # base_url. Embeddings never go to Ollama (CODE_GUIDELINES §10.8).
        self._client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        self._concurrency = ConcurrencyGuard(settings.EMBEDDING_MAX_CONCURRENT)

    def close(self) -> None:
        """Close the underlying OpenAI client's httpx connection pool.

        Mirrors :meth:`common.paperless.PaperlessClient.close`.  The indexer's
        config hot-reload path replaces the ``EmbeddingClient`` between cycles;
        closing the outgoing one releases its ``httpx`` pool deterministically
        instead of stranding it until CPython finalises the abandoned object —
        the project's explicit-close convention for I/O clients (CODE_GUIDELINES
        §8).  Safe to call once; the client is not used again after close.
        """
        self._client.close()

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

        # Fail-fast contract (IDX-02): batches are embedded in order and the
        # first non-retryable batch failure raises immediately. A document
        # either embeds wholly (one vector per input, in order) or fails wholly
        # — embed never returns a short vector list, so upsert_document is never
        # handed an incomplete document (fail-loud, CODE_GUIDELINES §1.11).
        vectors: list[list[float]] = []
        for batch_index, batch_start in enumerate(range(0, len(texts), _BATCH_SIZE)):
            batch = list(texts[batch_start : batch_start + _BATCH_SIZE])
            batch_vectors = self._embed_batch(batch, batch_index)
            vectors.extend(batch_vectors)

        return vectors

    @retry(retryable_exceptions=_RETRYABLE_EMBEDDING_EXCEPTIONS)
    def _embed_batch(self, batch: list[str], batch_index: int) -> list[list[float]]:
        """Send a single batch to the OpenAI embedding endpoint.

        This method is decorated with :func:`~common.retry.retry` so transient
        errors (connection drops, rate limits, 5xx) are retried with exponential
        backoff.  The :class:`~common.concurrency.ConcurrencyGuard` bounds how
        many batches are in flight at once.

        Args:
            batch: A non-empty list of strings (at most ``_BATCH_SIZE`` items).
            batch_index: The zero-based position of this batch within the
                document's inputs — included in the failure message so an
                operator can locate the offending chunk window (IDX-02).

        Returns:
            Vectors in the same order as ``batch``.

        Raises:
            EmbeddingError: On a non-retryable API failure.
        """
        try:
            with self._concurrency.acquire():
                response = self._client.embeddings.create(
                    model=self.settings.EMBEDDING_MODEL,
                    input=batch,
                    dimensions=self.settings.EMBEDDING_DIMENSIONS,
                )
        except _RETRYABLE_EMBEDDING_EXCEPTIONS:
            # Re-raise so the @retry decorator can act on it.
            raise
        except openai.OpenAIError as exc:
            # The SDK's base error — covers every non-retryable API failure
            # (AuthenticationError, BadRequestError, …). A programming bug
            # (AttributeError, TypeError) is deliberately NOT caught here so it
            # surfaces unmasked rather than being mislabelled non-retryable.
            raise EmbeddingError(
                f"Non-retryable embedding failure on batch {batch_index} "
                f"({len(batch)} texts)"
            ) from exc

        # The API returns items in arbitrary order; sort by index to guarantee
        # the output matches the input order.
        items = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in items]
