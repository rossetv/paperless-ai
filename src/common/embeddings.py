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

Provider-aware embeddings
-------------------------
Embeddings follow the ``EMBEDDING_PROVIDER`` setting, which is **independent of
``LLM_PROVIDER`` and defaults to ``openai``**: chat and embeddings are chosen
separately, so a fully-local ``ollama`` deployment sets ``EMBEDDING_PROVIDER=ollama``
explicitly to vectorise chunks on the local box. ``EmbeddingClient`` builds its
own ``openai.OpenAI`` client rather than reusing the provider-dependent shared
singleton in :mod:`common.llm` (CODE_GUIDELINES §10.8, §15.4):

* ``EMBEDDING_PROVIDER=openai`` (the default, and the production posture) —
  pinned to ``OPENAI_API_KEY`` and OpenAI's default
  ``base_url``, byte-for-byte identical to the historic OpenAI-only behaviour.
* ``EMBEDDING_PROVIDER=ollama`` — pointed at ``OLLAMA_BASE_URL`` (the
  OpenAI-compatible ``/v1/`` endpoint) with a placeholder API key, mirroring how
  :func:`common.library_setup.setup_libraries` builds the Ollama chat client.
  ``EMBEDDING_MODEL`` must name a local embedding model with a matching
  ``EMBEDDING_DIMENSIONS``.

``OPENAI_API_KEY`` is required by ``Settings`` whenever OpenAI is used by either
provider, so an ``openai`` embedding client can always be built; only a
fully-local (both ``ollama``) deployment may omit it.

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

# Placeholder key for Ollama's OpenAI-compatible endpoint: it ignores the key,
# but the SDK requires a non-empty string. Same sentinel and rationale as the
# chat client in common.library_setup (CODE_GUIDELINES §10.8).
_OLLAMA_PLACEHOLDER_API_KEY = "dummy"


def _build_embedding_client(settings: Settings) -> openai.OpenAI:
    """Build the provider-pinned ``openai.OpenAI`` client for embeddings.

    Branches on ``settings.EMBEDDING_PROVIDER`` (see the module docstring):
    under ``ollama`` it targets ``OLLAMA_BASE_URL`` with a placeholder key;
    otherwise (``openai``, the default and prod posture) it constructs the
    client exactly as before — ``api_key=OPENAI_API_KEY`` and OpenAI's default
    ``base_url`` (no override), so the OpenAI path stays byte-for-byte unchanged.
    """
    if settings.EMBEDDING_PROVIDER == "ollama":
        return openai.OpenAI(
            api_key=_OLLAMA_PLACEHOLDER_API_KEY,
            base_url=settings.OLLAMA_BASE_URL,
        )
    return openai.OpenAI(api_key=settings.OPENAI_API_KEY)


class EmbeddingClient:
    """Batched, retried embedding client, provider-aware via ``EMBEDDING_PROVIDER``.

    The client owns its own ``openai.OpenAI`` instance — it does **not** use the
    shared :mod:`common.llm` singleton (see the module docstring). Construction
    branches on ``settings.EMBEDDING_PROVIDER``:

    * ``openai`` — ``api_key=settings.OPENAI_API_KEY`` and OpenAI's default
      ``base_url`` (no override). This is the default for an ``openai``
      deployment and is byte-for-byte identical to the historic behaviour.
    * ``ollama`` — ``base_url=settings.OLLAMA_BASE_URL`` with a placeholder key
      (Ollama's OpenAI-compatible endpoint ignores it), mirroring
      :func:`common.library_setup.setup_libraries`.

    Args:
        settings: The daemon ``Settings`` instance.  Must expose
            ``EMBEDDING_PROVIDER``, ``OPENAI_API_KEY``, ``OLLAMA_BASE_URL``,
            ``EMBEDDING_MODEL``, ``EMBEDDING_DIMENSIONS``,
            ``EMBEDDING_MAX_CONCURRENT``, ``MAX_RETRIES``, and
            ``MAX_RETRY_BACKOFF_SECONDS``.

    The client stores ``settings`` as ``self.settings`` so that the
    :func:`~common.retry.retry` decorator — which reads ``self.settings`` — is
    applicable to instance methods.
    """

    def __init__(self, settings: Settings) -> None:
        # ``self.settings`` must be the attribute name; the @retry decorator
        # reads it via duck-typing — it must not be renamed.
        self.settings = settings
        self._client = _build_embedding_client(settings)
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
