"""Shared LLM helpers: retried chat completion, model dedup, thread-safe stats.

``_openai_holder`` holds one chat client per provider; it is filled by
:func:`common.library_setup.setup_libraries` during daemon bootstrap, and using
a slot before then raises ``RuntimeError``.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass

import openai
import structlog
from openai.types.chat import ChatCompletion

from .concurrency import llm_limiter
from .model_compat import model_compat_cache
from .retry import retry
from .shutdown import is_shutdown_requested

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LlmCallUsage:
    """Token usage for one successful LLM call and the model that served it.

    ``provider`` is the registry key of the endpoint that served the call, so
    search telemetry can price each step even when steps use different providers.
    """

    model: str
    provider: str
    prompt: int
    completion: int
    reasoning: int
    total: int


RETRYABLE_OPENAI_EXCEPTIONS = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)

# ``(param_key, error_message_substring, stat_key)``: a 400 whose lower-cased
# message contains the substring gets that parameter stripped and the call
# retried. The registry's length bounds the strip loop, so a misfiring matcher
# cannot loop forever. ``stat_key`` is counted only if the provider declares it.
# Order matters: ``max_completion_tokens`` must precede ``max_tokens`` so the
# more specific message matches first. The ``reasoning_effort`` and
# ``temperature`` matchers were verified against live gpt-6 400 responses
# (2026-11-23); ``verbosity`` and ``max_completion_tokens`` are unverified.
_STRIPPABLE_PARAMS: tuple[tuple[str, str, str], ...] = (
    ("temperature", "temperature", "temperature_retries"),
    ("response_format", "response_format", "response_format_retries"),
    ("response_format", "json_schema", "response_format_retries"),
    ("max_completion_tokens", "max_completion_tokens", "max_completion_tokens_retries"),
    ("max_tokens", "max_tokens", "max_tokens_retries"),
    ("max_tokens", "max tokens", "max_tokens_retries"),
    ("reasoning_effort", "reasoning_effort", "reasoning_effort_retries"),
    ("verbosity", "verbosity", "verbosity_retries"),
    ("service_tier", "service_tier", "service_tier_retries"),
)

# Param -> stat key. Several rows may share a param_key; the first one wins.
_PARAM_TO_STAT: dict[str, str] = {}
for _param, _matcher, _stat in _STRIPPABLE_PARAMS:
    _PARAM_TO_STAT.setdefault(_param, _stat)
del _param, _matcher, _stat

# Flex requests routinely run longer than standard-tier ones — OpenAI's own
# default timeout for them is 10 minutes — so flex calls floor their per-call
# timeout here instead of raising the global REQUEST_TIMEOUT (which would drag
# interactive search calls with it).
FLEX_MIN_TIMEOUT_SECONDS = 600

# Capacity-429 backoff for flex calls: exponential from 1s, capped here. The
# cap keeps the daemon responsive to recovered capacity without hammering the
# API during an outage.
_FLEX_BACKOFF_CAP_SECONDS = 60.0


def _wait_for_flex_capacity(wait_seconds: float) -> bool:
    """Sleep *wait_seconds* in ≤1s slices; ``False`` if shutdown interrupts.

    Chunked so a SIGTERM lands within ~1s instead of a full backoff interval —
    a hung shutdown would end in SIGKILL, and a SIGKILL mid-claim leaves the
    document skipped as "already claimed" on every later poll.
    """
    deadline = time.monotonic() + wait_seconds
    while True:
        if is_shutdown_requested():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(1.0, remaining))


def service_tier_params(
    *, flex_enabled: bool, request_timeout: int
) -> dict[str, object]:
    """``service_tier`` + ``timeout`` params for an OpenAI background-daemon call.

    Always names a tier explicitly — even ``"default"``. Verified live
    (2026-07-15): a 5.6 request with ``reasoning_effort: "none"`` and *no*
    ``service_tier`` was rejected 401 by the API while the identical request
    with an explicit tier succeeded; explicit is also deterministic and free.
    """
    if flex_enabled:
        return {
            "service_tier": "flex",
            "timeout": max(request_timeout, FLEX_MIN_TIMEOUT_SECONDS),
        }
    return {"service_tier": "default", "timeout": request_timeout}


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


class _ClientRegistry:
    """Thread-safe registry of OpenAI-compatible chat clients, one per provider.

    Each step picks its client by its own ``*_PROVIDER``, so one process can
    run, say, OCR on Ollama and search on OpenAI at the same time.
    """

    _PROVIDERS = ("openai", "ollama")

    def __init__(self) -> None:
        self._clients: dict[str, openai.OpenAI | None] = {
            provider: None for provider in self._PROVIDERS
        }

    def init(self, provider: str, client: openai.OpenAI | None) -> None:
        """Install (or clear, with ``None``) the client for *provider*."""
        if provider not in self._clients:
            raise ValueError(f"unknown provider: {provider!r}")
        self._clients[provider] = client

    def is_ready(self, provider: str) -> bool:
        return self._clients.get(provider) is not None

    def get(self, provider: str) -> openai.OpenAI:
        client = self._clients.get(provider)
        if client is None:
            raise RuntimeError(
                f"{provider} chat client not initialised: its connection is not "
                "configured (OPENAI_API_KEY for openai, OLLAMA_BASE_URL for "
                "ollama) or setup_libraries() has not run for this provider"
            )
        return client


_openai_holder = _ClientRegistry()


def get_openai_client() -> openai.OpenAI:
    """Return the OpenAI chat client."""
    return _openai_holder.get("openai")


def is_openai_client_ready() -> bool:
    """Whether the OpenAI chat client is installed."""
    return _openai_holder.is_ready("openai")


def set_chat_client(provider: str, client: openai.OpenAI | None) -> None:
    """Install (``client``) or clear (``None``) the registry slot for *provider*."""
    _openai_holder.init(provider, client)


class OpenAIChatMixin:
    """Retried OpenAI-compatible chat completion plus thread-safe stats.

    Subclasses define ``_STAT_KEYS``, call ``_init_stats()`` in ``__init__``,
    and expose ``self.settings`` with ``MAX_RETRIES`` and
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
        """Count one parameter strip, if the provider declared its stat key."""
        stat_key = _PARAM_TO_STAT.get(param_key)
        if stat_key is not None:
            self._increment_stat_if_declared(stat_key)

    def _increment_stat_if_declared(self, stat_key: str) -> None:
        """Increment *stat_key* only when this provider declared it in ``_STAT_KEYS``."""
        if stat_key in self._STAT_KEYS:
            self._stats.inc(stat_key)

    @property
    def _provider(self) -> str:
        """The provider whose chat client this step uses; steps override it."""
        return "openai"

    @retry(retryable_exceptions=RETRYABLE_OPENAI_EXCEPTIONS)
    def _create_completion(self, **kwargs: object) -> ChatCompletion:
        client = _openai_holder.get(self._provider)
        with llm_limiter.acquire():
            # create() is overloaded on `stream`, which **kwargs cannot satisfy.
            # Callers never pass stream=True, so the result is a ChatCompletion.
            return client.chat.completions.create(**kwargs)  # type: ignore[call-overload]

    def _create_with_compat(
        self, params: dict[str, object], model: str
    ) -> ChatCompletion | None:
        """Send a chat completion, adapting to parameters *model* rejects.

        Parameters already cached as rejected for *model* are stripped up front.
        A 400 naming a strippable parameter strips it, caches it and retries the
        same model; a 400 bills no tokens, so discovery costs one round-trip.

        Any other 400 or API error returns ``None``, meaning "this model failed,
        try the next": the fallback chain and its callers' degradation paths rely
        on a non-raising failure here (unlike embeddings, which have no chain).

        On the flex tier a 429 means "no spare capacity right now", not a broken
        model, so the call backs off and retries the same model until capacity
        returns or shutdown is requested. An ``insufficient_quota`` 429 is
        terminal even on flex: waiting cannot fix an empty account and would
        freeze the worker silently.
        """
        params = self._pre_strip_known_rejected(params, model)
        strip_attempts = 0
        flex_wait = 1.0
        while True:
            try:
                self._record_attempt()
                return self._create_completion(**params)
            except openai.BadRequestError as error:
                strip_attempts += 1
                if strip_attempts > len(_STRIPPABLE_PARAMS):
                    log.warning("llm.request_rejected_after_strips", model=model)
                    self._record_api_error()
                    return None
                stripped_params = self._strip_rejected_param(error, params, model)
                if stripped_params is None:
                    log.warning("llm.request_rejected", model=model, error=str(error))
                    self._record_api_error()
                    return None
                params = stripped_params
            # RateLimitError subclasses APIError, so it must be caught first.
            except openai.RateLimitError as error:
                if error.code == "insufficient_quota":
                    # Out of credit: waiting would freeze the worker until
                    # billing is topped up.
                    log.warning("llm.quota_exhausted", model=model, error=str(error))
                    self._record_api_error()
                    return None
                if params.get("service_tier") != "flex":
                    log.warning("llm.model_failed", model=model, error=str(error))
                    self._record_api_error()
                    return None
                # Flex capacity shortage: unbilled and transient, so wait it out
                # rather than fail the model or error-tag the document.
                log.warning(
                    "llm.flex_capacity_wait",
                    model=model,
                    wait_seconds=flex_wait,
                    error=str(error),
                )
                if not _wait_for_flex_capacity(flex_wait):
                    log.warning("llm.flex_wait_aborted_by_shutdown", model=model)
                    self._record_api_error()
                    return None
                flex_wait = min(flex_wait * 2, _FLEX_BACKOFF_CAP_SECONDS)
            except openai.APIError as error:
                log.warning("llm.model_failed", model=model, error=str(error))
                self._record_api_error()
                return None

    def _pre_strip_known_rejected(
        self, params: dict[str, object], model: str
    ) -> dict[str, object]:
        """Return a copy of *params* without the parameters cached as rejected."""
        rejected = model_compat_cache.rejected_params_for(model)
        return {key: value for key, value in params.items() if key not in rejected}

    def _strip_rejected_param(
        self, error: openai.BadRequestError, params: dict[str, object], model: str
    ) -> dict[str, object] | None:
        """Return *params* without the parameter *error* names, caching the rejection.

        ``None`` when the 400 names no strippable parameter present in *params*.
        """
        param_key = _strippable_param_for_error(error)
        if param_key is None or param_key not in params:
            return None
        log.warning("llm.param_unsupported_stripped", model=model, parameter=param_key)
        model_compat_cache.record_rejected(model, param_key)
        self._record_strip(param_key)
        remaining = dict(params)
        del remaining[param_key]
        return remaining

    def _complete_with_model_fallback(
        self,
        *,
        primary_model: str,
        messages: list[dict[str, str]],
        fallback_models: Iterable[str],
        log_event_prefix: str,
        reasoning_effort: str | None = None,
        response_format: dict[str, object] | None = None,
        timeout: float | None = None,
        service_tier: str | None = None,
        usage_sink: list[LlmCallUsage] | None = None,
    ) -> str | None:
        """Run one chat completion, falling back through a chain of models.

        Tries *primary_model* then each of *fallback_models* (deduplicated) and
        returns the first successful reply's text, or ``None`` if every model
        failed. The optional parameters are sent only when not ``None``.
        *log_event_prefix* names the stage in the per-model failure log.

        Search stages pass ``service_tier="default"`` on OpenAI, never
        ``"flex"``, because a person is waiting for the answer.

        Each successful call appends a :class:`LlmCallUsage` to *usage_sink*
        when given; usage fields the provider omits (e.g. Ollama) count as zero.
        """
        models = unique_models([primary_model, *fallback_models])
        optional_params = self._optional_completion_params(
            reasoning_effort=reasoning_effort,
            response_format=response_format,
            timeout=timeout,
            service_tier=service_tier,
        )
        for model in models:
            params: dict[str, object] = {
                "model": model,
                "messages": messages,
                **optional_params,
            }
            completion = self._create_with_compat(params, model)
            if completion is None:
                log.warning(
                    "llm.fallback_model_failed", stage=log_event_prefix, model=model
                )
                continue
            if usage_sink is not None:
                usage = getattr(completion, "usage", None)
                details = getattr(usage, "completion_tokens_details", None)
                usage_sink.append(
                    LlmCallUsage(
                        model=model,
                        provider=self._provider,
                        prompt=getattr(usage, "prompt_tokens", 0) or 0,
                        completion=getattr(usage, "completion_tokens", 0) or 0,
                        reasoning=getattr(details, "reasoning_tokens", 0) or 0,
                        total=getattr(usage, "total_tokens", 0) or 0,
                    )
                )
            if not completion.choices:
                log.warning("llm.empty_choices", stage=log_event_prefix, model=model)
                continue
            message = completion.choices[0].message
            if message is None or not isinstance(message.content, str | None):
                log.warning("llm.unusable_message", stage=log_event_prefix, model=model)
                continue
            return message.content or ""

        return None

    @staticmethod
    def _optional_completion_params(
        *,
        reasoning_effort: str | None,
        response_format: dict[str, object] | None,
        timeout: float | None,
        service_tier: str | None = None,
    ) -> dict[str, object]:
        """Build the dict of optional completion params, dropping every ``None``."""
        candidates: dict[str, object | None] = {
            "reasoning_effort": reasoning_effort,
            "response_format": response_format,
            "timeout": timeout,
            "service_tier": service_tier,
        }
        return {key: value for key, value in candidates.items() if value is not None}


def unique_models(models: list[str]) -> list[str]:
    """Deduplicate a model list while preserving insertion order."""
    return list(dict.fromkeys(models))


def extract_json_object(text: str) -> object:
    """Parse JSON from raw model output, tolerating code fences and preamble.

    Tries a strict parse, then the text from the first ``{`` to the last ``}``.
    The result may be any JSON value, so callers must check its type. Raises
    :class:`json.JSONDecodeError` when neither parse succeeds.
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
