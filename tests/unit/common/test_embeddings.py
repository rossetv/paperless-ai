"""Tests for common.embeddings.EmbeddingClient."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import openai
import pytest

from common.embeddings import EmbeddingClient, EmbeddingError
from tests.helpers.mocks import make_mock_embeddings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(
    *,
    max_retries: int = 3,
    max_retry_backoff: int = 0,
    embedding_model: str = "text-embedding-3-small",
    embedding_max_concurrent: int = 0,
    embedding_dimensions: int = 1536,
    openai_api_key: str = "sk-test",
) -> MagicMock:
    settings = MagicMock()
    settings.MAX_RETRIES = max_retries
    settings.MAX_RETRY_BACKOFF_SECONDS = max_retry_backoff
    settings.EMBEDDING_MODEL = embedding_model
    settings.EMBEDDING_MAX_CONCURRENT = embedding_max_concurrent
    settings.EMBEDDING_DIMENSIONS = embedding_dimensions
    settings.OPENAI_API_KEY = openai_api_key
    return settings


@contextmanager
def _client_with(mock_openai: MagicMock) -> Iterator[None]:
    """Patch ``openai.OpenAI`` so EmbeddingClient builds *mock_openai*.

    EmbeddingClient constructs its own OpenAI client pinned to OPENAI_API_KEY
    (it does not reuse the shared singleton), so tests patch the constructor.
    """
    with patch("common.embeddings.openai.OpenAI", return_value=mock_openai):
        yield


# ---------------------------------------------------------------------------
# Test: client is pinned to OpenAI with the configured API key
# ---------------------------------------------------------------------------


class TestClientIsPinnedToOpenAI:

    def test_constructs_openai_client_with_configured_api_key(self) -> None:
        """EmbeddingClient builds its own openai.OpenAI with OPENAI_API_KEY.

        Embeddings always go to OpenAI, never to the Ollama-pointed shared
        singleton — so the client must be constructed explicitly with the
        configured key and OpenAI's default base_url.
        """
        settings = _make_settings(openai_api_key="sk-embeddings-key")

        with patch("common.embeddings.openai.OpenAI") as mock_openai_cls:
            EmbeddingClient(settings)

        mock_openai_cls.assert_called_once()
        call = mock_openai_cls.call_args
        assert call.kwargs.get("api_key") == "sk-embeddings-key"
        # No base_url override — embeddings use OpenAI's default endpoint.
        assert "base_url" not in call.kwargs or call.kwargs["base_url"] is None


# ---------------------------------------------------------------------------
# Test: empty input
# ---------------------------------------------------------------------------


class TestEmptyInput:

    def test_empty_sequence_returns_empty_list(self) -> None:
        """embed([]) returns [] without calling the OpenAI API."""
        settings = _make_settings()
        mock_openai = MagicMock()

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)
            result = client.embed([])

        assert result == []
        mock_openai.embeddings.create.assert_not_called()


# ---------------------------------------------------------------------------
# Test: one vector returned per input, in order
# ---------------------------------------------------------------------------


class TestReturnOrder:

    def test_single_text_returns_one_vector(self) -> None:
        """embed returns exactly one vector for a single input."""
        settings = _make_settings()
        mock_openai, _ = make_mock_embeddings(n=1, dimensions=4)

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)
            result = client.embed(["hello"])

        assert len(result) == 1

    def test_multiple_texts_preserves_input_order(self) -> None:
        """embed returns one vector per input, in the same order as the input."""
        settings = _make_settings()
        vec_a = [1.0, 0.0]
        vec_b = [0.0, 1.0]
        vec_c = [0.5, 0.5]
        mock_openai = make_mock_embeddings(vectors=[vec_a, vec_b, vec_c])[0]

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)
            result = client.embed(["a", "b", "c"])

        assert result == [vec_a, vec_b, vec_c]


# ---------------------------------------------------------------------------
# Test: batching (>96 inputs split into multiple requests)
# ---------------------------------------------------------------------------


class TestBatching:

    def test_exactly_one_batch_for_small_input(self) -> None:
        """96 texts or fewer are sent in a single API request."""
        settings = _make_settings()
        texts = [f"text {i}" for i in range(96)]
        mock_openai, _ = make_mock_embeddings(n=96, dimensions=2)

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)
            result = client.embed(texts)

        assert mock_openai.embeddings.create.call_count == 1
        assert len(result) == 96

    def test_97_inputs_split_into_two_requests(self) -> None:
        """97 texts (one over the 96-cap) produce two API calls."""
        settings = _make_settings()
        texts = [f"text {i}" for i in range(97)]
        mock_openai, _ = make_mock_embeddings(n=97, dimensions=2)

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)
            result = client.embed(texts)

        assert mock_openai.embeddings.create.call_count == 2
        assert len(result) == 97

    def test_large_input_split_into_correct_number_of_batches(self) -> None:
        """200 inputs → ceil(200/96) = 3 API calls, all vectors returned."""
        settings = _make_settings()
        texts = [f"text {i}" for i in range(200)]
        mock_openai, _ = make_mock_embeddings(n=200, dimensions=2)

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)
            result = client.embed(texts)

        assert mock_openai.embeddings.create.call_count == 3
        assert len(result) == 200

    def test_cross_batch_vectors_preserve_order(self) -> None:
        """Vectors from multiple batches are returned in input order."""
        settings = _make_settings()
        # Build 100 distinct vectors that are recognisable by their first element.
        vectors = [[float(i), 0.0] for i in range(100)]
        mock_openai = make_mock_embeddings(vectors=vectors)[0]

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)
            texts = [f"text {i}" for i in range(100)]
            result = client.embed(texts)

        assert result == vectors


# ---------------------------------------------------------------------------
# Test: transient error is retried then succeeds
# ---------------------------------------------------------------------------


class TestRetry:

    @patch("common.retry._sleep_backoff")
    def test_transient_error_retried_then_succeeds(self, mock_sleep) -> None:
        """A single transient API error triggers a retry and ultimately succeeds."""
        settings = _make_settings(max_retries=3)
        vec = [1.0, 2.0]

        # Build a minimal success response manually so we control the vector.
        success_response = MagicMock()
        success_response.data = [MagicMock(embedding=vec, index=0)]

        mock_openai = MagicMock()
        mock_openai.embeddings.create.side_effect = [
            openai.APIConnectionError(request=MagicMock()),
            success_response,
        ]

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)
            result = client.embed(["hello"])

        assert result == [vec]
        assert mock_openai.embeddings.create.call_count == 2

    @patch("common.retry._sleep_backoff")
    def test_non_retryable_openai_error_raises_embedding_error(self, mock_sleep) -> None:
        """A non-retryable openai.OpenAIError is wrapped in EmbeddingError."""
        settings = _make_settings(max_retries=3)
        mock_openai = MagicMock()
        original = openai.BadRequestError(
            message="bad request",
            response=MagicMock(status_code=400),
            body=None,
        )
        mock_openai.embeddings.create.side_effect = original

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)
            with pytest.raises(EmbeddingError) as exc_info:
                client.embed(["hello"])

        # The original exception must be chained.
        assert exc_info.value.__cause__ is original

    @patch("common.retry._sleep_backoff")
    def test_programming_error_is_not_swallowed(self, mock_sleep) -> None:
        """A non-OpenAI bug (TypeError) propagates rather than becoming EmbeddingError.

        _embed_batch catches only openai.OpenAIError; a genuine programming
        bug must surface unmasked so it is not mislabelled as a non-retryable
        API failure.
        """
        settings = _make_settings(max_retries=3)
        mock_openai = MagicMock()
        mock_openai.embeddings.create.side_effect = TypeError("not an API error")

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)
            with pytest.raises(TypeError):
                client.embed(["hello"])

    @patch("common.retry._sleep_backoff")
    def test_all_retries_exhausted_raises_retryable_exception(self, mock_sleep) -> None:
        """When all retries are exhausted, the retryable exception propagates."""
        settings = _make_settings(max_retries=2)
        mock_openai = MagicMock()
        mock_openai.embeddings.create.side_effect = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)
            with pytest.raises(openai.RateLimitError):
                client.embed(["hello"])

        assert mock_openai.embeddings.create.call_count == 2


# ---------------------------------------------------------------------------
# Test: concurrency guard bounds concurrency
# ---------------------------------------------------------------------------


class TestConcurrencyGuard:

    def test_max_concurrent_zero_means_unbounded(self) -> None:
        """EMBEDDING_MAX_CONCURRENT=0 creates an unbounded guard (no semaphore)."""
        settings = _make_settings(embedding_max_concurrent=0)
        mock_openai, _ = make_mock_embeddings(n=1, dimensions=2)

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)

        assert client._concurrency._semaphore is None

    def test_max_concurrent_positive_creates_semaphore(self) -> None:
        """EMBEDDING_MAX_CONCURRENT>0 gives the guard a bounded semaphore."""
        settings = _make_settings(embedding_max_concurrent=4)
        mock_openai, _ = make_mock_embeddings(n=1, dimensions=2)

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)

        assert client._concurrency._semaphore is not None

    def test_semaphore_1_serialises_concurrent_calls(self) -> None:
        """With EMBEDDING_MAX_CONCURRENT=1, two threads never overlap inside the API call.

        A counting fake records the peak concurrency level and we assert it
        never exceeds 1.  A release_gate event makes the first call block until
        both threads have started, maximising the overlap window if the
        guard's semaphore were absent.
        """
        settings = _make_settings(embedding_max_concurrent=1)

        in_flight_peak = 0
        in_flight_current = 0
        counter_lock = threading.Lock()
        # Fires once thread_a is inside fake_create.
        thread_a_entered = threading.Event()
        # Fires to allow thread_a to return (after thread_b has tried to enter).
        release_gate = threading.Event()

        def fake_create(*, model: str, input: Sequence[str], **kwargs):  # type: ignore[override]
            nonlocal in_flight_current, in_flight_peak
            with counter_lock:
                in_flight_current += 1
                in_flight_peak = max(in_flight_peak, in_flight_current)
            thread_a_entered.set()
            # Block until the test tells us to continue.
            release_gate.wait(timeout=5)
            with counter_lock:
                in_flight_current -= 1
            response = MagicMock()
            response.data = [
                MagicMock(embedding=[0.0], index=i) for i in range(len(input))
            ]
            return response

        mock_openai = MagicMock()
        mock_openai.embeddings.create.side_effect = fake_create

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)

        errors: list[Exception] = []

        def run_embed() -> None:
            try:
                client.embed(["text"])
            except Exception as exc:
                errors.append(exc)

        thread_a = threading.Thread(target=run_embed, name="embed-a", daemon=True)
        thread_b = threading.Thread(target=run_embed, name="embed-b", daemon=True)

        thread_a.start()
        # Wait for thread_a to be inside fake_create (semaphore held).
        thread_a_entered.wait(timeout=5)

        thread_b.start()
        # Thread_b is now blocked on the semaphore.  Release thread_a so
        # thread_b can acquire and complete.
        release_gate.set()

        thread_a.join(timeout=5)
        thread_b.join(timeout=5)

        assert not errors, f"Threads raised: {errors}"
        # Both threads ran fake_create, but never simultaneously.
        assert in_flight_peak == 1, (
            f"Expected peak of 1 concurrent call, saw peak={in_flight_peak}"
        )
        assert mock_openai.embeddings.create.call_count == 2


# ---------------------------------------------------------------------------
# Test: configured model is passed to the API
# ---------------------------------------------------------------------------


class TestModelPassthrough:

    def test_configured_model_sent_to_api(self) -> None:
        """embed passes settings.EMBEDDING_MODEL to the OpenAI embeddings.create call."""
        settings = _make_settings(embedding_model="text-embedding-3-large")
        mock_openai, _ = make_mock_embeddings(n=1, dimensions=2)

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)
            client.embed(["test text"])

        mock_openai.embeddings.create.assert_called_once()
        call_kwargs = mock_openai.embeddings.create.call_args
        assert call_kwargs.kwargs.get("model") == "text-embedding-3-large"


# ---------------------------------------------------------------------------
# Test: configured dimensions are passed to the API
# ---------------------------------------------------------------------------


class TestDimensionsPassthrough:

    def test_configured_dimensions_sent_to_api(self) -> None:
        """embed passes settings.EMBEDDING_DIMENSIONS to the OpenAI embeddings.create call.

        Without this, a non-default EMBEDDING_DIMENSIONS setting is silently ignored:
        the API returns vectors of the model's native width while meta records the
        configured number, creating a silent dimension mismatch.
        """
        settings = _make_settings(
            embedding_model="text-embedding-3-small",
            embedding_dimensions=512,
        )
        mock_openai, _ = make_mock_embeddings(n=1, dimensions=2)

        with _client_with(mock_openai):
            client = EmbeddingClient(settings)
            client.embed(["test text"])

        mock_openai.embeddings.create.assert_called_once()
        call_kwargs = mock_openai.embeddings.create.call_args
        assert call_kwargs.kwargs.get("dimensions") == 512, (
            "EMBEDDING_DIMENSIONS must be forwarded to the API as the 'dimensions' kwarg"
        )
