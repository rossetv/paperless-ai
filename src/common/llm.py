"""Shared LLM helpers: retried chat completion, model dedup, thread-safe stats.

Module-global singletons
~~~~~~~~~~~~~~~~~~~~~~~~
``_openai_holder`` stores the shared :class:`openai.OpenAI` client.  It is
initialised by :func:`common.library_setup.setup_libraries` during
:func:`common.bootstrap.bootstrap_daemon`.  Calling :func:`get_openai_client`
before initialisation raises ``RuntimeError``.

Boot order: Settings -> logging -> ``setup_libraries`` (inits ``_openai_holder``)
-> signal handlers -> ``llm_limiter.init`` (see :mod:`common.concurrency`).
See :func:`common.bootstrap.bootstrap_daemon` for the canonical sequence.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable

import openai
import structlog
from openai.types.chat import ChatCompletion

from .concurrency import llm_limiter
from .retry import retry

log = structlog.get_logger(__name__)

RETRYABLE_OPENAI_EXCEPTIONS = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)

# Strippable-parameter registry: ``(param_key, error_message_substring, stat_key)``.
#
# When a model returns a 400 whose (lower-cased) message contains the substring,
# the matching parameter is stripped and retried. The substring matchers are
# deliberately broad and migrated from the prod-proven classifier detectors;
# the registry's fixed length bounds the strip loop so a misfiring matcher can
# never loop forever. ``stat_key`` is the optional per-strip counter a provider
# *may* declare in its ``_STAT_KEYS``; the shared layer increments it only when
# the provider declared it (see ``_record_strip``).
#
# Ordering matters: ``max_completion_tokens`` precedes ``max_tokens`` so the
# longer, more specific message wins before the shorter substring can match it.
#
# rationale (CODE_GUIDELINES §10.2 / spec §4.1): the matchers for
# ``reasoning_effort``, ``verbosity``, and ``max_completion_tokens`` are
# best-effort and MUST be verified against a real openai~=1.35 400 response
# before relying on them in production (see the plan's Task 9).
_STRIPPABLE_PARAMS: tuple[tuple[str, str, str], ...] = (
    ("temperature", "temperature", "temperature_retries"),
    ("response_format", "response_format", "response_format_retries"),
    ("response_format", "json_schema", "response_format_retries"),
    ("max_completion_tokens", "max_completion_tokens", "max_completion_tokens_retries"),
    ("max_tokens", "max_tokens", "max_tokens_retries"),
    ("max_tokens", "max tokens", "max_tokens_retries"),
    ("reasoning_effort", "reasoning_effort", "reasoning_effort_retries"),
    ("verbosity", "verbosity", "verbosity_retries"),
)


def _strippable_param_for_error(error: openai.BadRequestError) -> str | None:
    """Return the strippable parameter a 400 names as unsupported, or ``None``.

    Substring-matches the lower-cased error message against the registry, in
    order, so the first (most specific) match wins. ``None`` means the 400 is
    not about a strippable parameter — a malformed request the caller cannot
    recover by stripping.
    """
    message = str(error).lower()
    for param_key, matcher, _stat_key in _STRIPPABLE_PARAMS:
        if matcher in message:
            return param_key
    return None


class _OpenAIClientHolder:
    """Thread-safe holder for the shared OpenAI client singleton.

    Avoids a bare module-level mutable by encapsulating the state in an
    instance attribute with explicit init/get methods.
    """

    def __init__(self) -> None:
        self._client: openai.OpenAI | None = None

    def init(self, client: openai.OpenAI) -> None:
        self._client = client

    def is_ready(self) -> bool:
        return self._client is not None

    def get(self) -> openai.OpenAI:
        if self._client is None:
            raise RuntimeError(
                "OpenAI client not initialised; call setup_libraries() first"
            )
        return self._client


_openai_holder = _OpenAIClientHolder()


def init_openai_client(client: openai.OpenAI) -> None:
    _openai_holder.init(client)


def get_openai_client() -> openai.OpenAI:
    return _openai_holder.get()


def is_openai_client_ready() -> bool:
    return _openai_holder.is_ready()


class OpenAIChatMixin:
    """
    Mixin providing a retried OpenAI-compatible chat completion call and
    thread-safe stats helpers.

    Subclasses define a ``_STAT_KEYS`` class attribute and call
    ``_init_stats()`` in their ``__init__``.  The mixin then provides
    ``reset_stats()`` and ``get_stats()``.

    The mixin expects ``self.settings`` to expose ``MAX_RETRIES`` and
    ``MAX_RETRY_BACKOFF_SECONDS`` for the retry decorator.
    """

    _STAT_KEYS: tuple[str, ...] = ()

    def _init_stats(self) -> None:
        self._stats = ThreadSafeStats(self._STAT_KEYS)

    def reset_stats(self) -> None:
        self._stats.reset(self._STAT_KEYS)

    def get_stats(self) -> dict[str, int]:
        return self._stats.snapshot()

    def _record_attempt(self) -> None:
        """Count one outgoing chat-completion call, if the provider tracks it."""
        self._increment_stat_if_declared("attempts")

    def _record_api_error(self) -> None:
        """Count one give-up (non-strippable 400 or other API error), if tracked."""
        self._increment_stat_if_declared("api_errors")

    def _record_strip(self, param_key: str) -> None:
        """Count one parameter strip under its registry stat key, if the provider
        declared that key.

        A provider opts in to per-parameter strip counters by listing the
        registry ``stat_key`` (e.g. ``"temperature_retries"``) in its
        ``_STAT_KEYS``. Providers that do not — OCR, the planner, the
        synthesiser — silently skip the count, so the shared layer stays
        agnostic of any provider's stat schema (spec §4.1).
        """
        for param, _matcher, stat_key in _STRIPPABLE_PARAMS:
            if param == param_key:
                self._increment_stat_if_declared(stat_key)
                return

    def _increment_stat_if_declared(self, stat_key: str) -> None:
        """Increment *stat_key* only when this provider declared it in ``_STAT_KEYS``."""
        if stat_key in self._STAT_KEYS:
            self._stats.inc(stat_key)

    @retry(retryable_exceptions=RETRYABLE_OPENAI_EXCEPTIONS)
    def _create_completion(self, **kwargs: object) -> ChatCompletion:
        client = _openai_holder.get()
        with llm_limiter.acquire():
            # rationale: OpenAI SDK's create() is overloaded on `stream`; **kwargs:object
            # cannot satisfy those overloads. Callers never pass stream=True, so the
            # runtime return is always ChatCompletion; a tighter call-site type is impossible
            # without replacing **kwargs with an explicit typed signature.
            return client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
            # and narrowly scoped to this one call site.

    def _complete_with_model_fallback(
        self,
        *,
        primary_model: str,
        messages: list[dict[str, str]],
        fallback_models: Iterable[str],
        log_event_prefix: str,
    ) -> str | None:
        """Run one chat completion, falling back through a chain of models.

        The model-fallback chain belongs in the shared LLM wrapper
        (CODE_GUIDELINES.md §8.1): the planner and the synthesiser both need
        exactly this loop, so it lives here once rather than in each stage.

        The chain is ``primary_model`` followed by every model in
        *fallback_models*, deduplicated by :func:`unique_models` so the primary
        is never tried twice when it also appears in the fallback list.  Each
        attempt goes through :meth:`_create_completion`, so it inherits the
        shared ``@retry`` exponential backoff and the ``llm_limiter`` global
        concurrency limiter for free.

        A model that still fails after retries raises an ``openai.APIError``
        subclass — this covers *both* a retry-exhausted retryable error and a
        non-retryable one (``AuthenticationError``, ``PermissionDeniedError``,
        ``NotFoundError``, ``BadRequestError``, …).  Every one is caught here as
        the terminal "skip this model" branch; the next model is tried.

        Args:
            primary_model: The model to try first.
            messages: The chat messages to send (the ``messages`` kwarg of the
                OpenAI chat-completions call).
            fallback_models: Models to try, in order, after *primary_model*.
            log_event_prefix: The dotted event-name prefix for the
                per-model-failure warning, e.g. ``"planner"`` →
                ``"planner.model_failed"``.

        Returns:
            The raw text content of the first successful completion, or
            ``None`` when every model in the chain failed.
        """
        models = unique_models([primary_model, *fallback_models])
        for model in models:
            try:
                completion = self._create_completion(model=model, messages=messages)
            except openai.APIError as exc:
                # Catches BOTH retry-exhausted retryable errors and
                # non-retryable ones (AuthenticationError, PermissionDeniedError,
                # NotFoundError, BadRequestError, …) — every one is an
                # openai.APIError subclass.  Skip this model; try the next.
                log.warning(
                    f"{log_event_prefix}.model_failed",
                    model=model,
                    error=str(exc),
                )
                continue
            return completion.choices[0].message.content or ""

        return None


def unique_models(models: list[str]) -> list[str]:
    """Deduplicate a model list while preserving insertion order."""
    return list(dict.fromkeys(models))


def extract_json_object(text: str) -> object:
    """Parse JSON from raw model output, tolerating fences and preamble.

    LLMs frequently wrap a JSON response in markdown code fences
    (```` ``` ```` or ```` ```json ````) or prepend a sentence of preamble.
    This helper first attempts a strict :func:`json.loads`; on failure it
    falls back to the substring from the first ``{`` to the last ``}`` and
    re-parses that.  It is the single shared JSON extractor for every place
    that parses an LLM response — the planner, the synthesiser, and the
    classifier all route through it.

    Args:
        text: Raw model-output string.

    Returns:
        The parsed Python object.  Callers must check its concrete type (a
        well-behaved LLM returns an object, but the strict parse also accepts
        a bare array, string, or number) before using it.

    Raises:
        json.JSONDecodeError: When no valid JSON can be found — neither a
            strict parse nor the ``{…}`` substring fallback succeeded.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


class ThreadSafeStats:
    """Thread-safe counter dict used by OCR and classification providers."""

    def __init__(self, keys: Iterable[str]) -> None:
        self._lock = threading.Lock()
        self._stats = {k: 0 for k in keys}

    def inc(self, key: str) -> None:
        with self._lock:
            self._stats[key] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def reset(self, keys: Iterable[str]) -> None:
        with self._lock:
            self._stats = {k: 0 for k in keys}
