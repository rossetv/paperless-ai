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
from .model_compat import model_compat_cache
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

    def _create_with_compat(
        self, params: dict[str, object], model: str
    ) -> ChatCompletion | None:
        """Send a chat completion, adapting to parameters *model* rejects.

        Three phases:

        1. **Pre-strip** every parameter already recorded as rejected for
           *model* in :data:`~common.model_compat.model_compat_cache`, so a
           model whose incompatibility was discovered earlier in this process
           never pays a wasted 400 round-trip again.
        2. **Send.** On success, return the completion.
        3. **Adapt.** On an ``openai.BadRequestError`` that names a strippable
           parameter present in *params*, strip it, record it in the cache, and
           retry the same model. Bounded by the registry length so a misfiring
           matcher cannot loop forever. A 400 bills no tokens, so the only cost
           of a first-time discovery is one extra round-trip.

        Any other ``openai.BadRequestError`` (a malformed request) or any other
        ``openai.APIError`` (rate limit, 5xx, timeout after the ``@retry`` on
        :meth:`_create_completion` is exhausted) is terminal: it is logged and
        ``None`` is returned so the caller can advance to the next model.
        """
        params = self._pre_strip_known_rejected(dict(params), model)
        for _attempt in range(len(_STRIPPABLE_PARAMS) + 1):
            try:
                self._record_attempt()
                return self._create_completion(**params)
            except openai.BadRequestError as error:
                stripped_params = self._strip_rejected_param(error, params, model)
                if stripped_params is None:
                    log.warning("llm.request_rejected", model=model, error=str(error))
                    self._record_api_error()
                    return None
                params = stripped_params
            except openai.APIError as error:
                log.warning("llm.model_failed", model=model, error=str(error))
                self._record_api_error()
                return None
        log.warning("llm.request_rejected_after_strips", model=model)
        self._record_api_error()
        return None

    def _pre_strip_known_rejected(
        self, params: dict[str, object], model: str
    ) -> dict[str, object]:
        """Remove from *params* every parameter the cache says *model* rejects."""
        for param_key in model_compat_cache.rejected_params_for(model):
            params.pop(param_key, None)
        return params

    def _strip_rejected_param(
        self, error: openai.BadRequestError, params: dict[str, object], model: str
    ) -> dict[str, object] | None:
        """Strip the parameter *error* names if it is present, else return ``None``.

        Returns a new params dict with the offending parameter removed (and the
        rejection cached + counted), or ``None`` when the 400 is not about a
        strippable parameter that is actually present — the signal to give up.
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
    ) -> str | None:
        """Run one chat completion, falling back through a chain of models.

        The model-fallback chain belongs in the shared LLM wrapper
        (CODE_GUIDELINES.md §8.1): the planner and the synthesiser both need
        exactly this loop, so it lives here once rather than in each stage.

        The chain is ``primary_model`` followed by every model in
        *fallback_models*, deduplicated by :func:`unique_models` so the primary
        is never tried twice when it also appears in the fallback list.  Each
        attempt goes through :meth:`_create_with_compat`, so it inherits the
        shared ``@retry`` exponential backoff, the ``llm_limiter`` global
        concurrency limiter, and the per-model parameter-compatibility cache.

        ``reasoning_effort``, ``response_format``, and ``timeout`` are optional
        and additive: each is forwarded to the model only when non-``None``.
        Every attempt is routed through :meth:`_create_with_compat`, so a model
        that rejects any of these parameters has it stripped-and-cached rather
        than failing the whole call. With none supplied the outgoing request is
        exactly ``{model, messages}`` and the behaviour is identical to the
        pre-extension direct path (pinned by the no-arg characterisation test).

        A model that still fails after retries surfaces an ``openai.APIError``
        subclass — this covers *both* a retry-exhausted retryable error and a
        non-retryable one (``AuthenticationError``, ``PermissionDeniedError``,
        ``NotFoundError``, ``BadRequestError``, …).  :meth:`_create_with_compat`
        turns every such terminal failure into ``None``; the next model is
        tried.

        Args:
            primary_model: The model to try first.
            messages: The chat messages to send (the ``messages`` kwarg of the
                OpenAI chat-completions call).
            fallback_models: Models to try, in order, after *primary_model*.
            log_event_prefix: The dotted event-name prefix for the
                per-model-failure warning, e.g. ``"planner"`` →
                ``"planner.model_failed"``.
            reasoning_effort: Optional OpenAI reasoning-effort hint (e.g.
                ``"low"``); omitted from the request when ``None``.
            response_format: Optional response-format object (e.g. a
                ``json_schema`` block); omitted when ``None``.
            timeout: Optional per-call timeout in seconds; omitted when ``None``
                so the SDK/client default applies (CODE_GUIDELINES §8.7).

        Returns:
            The raw text content of the first successful completion, or
            ``None`` when every model in the chain failed.
        """
        models = unique_models([primary_model, *fallback_models])
        optional_params = self._optional_completion_params(
            reasoning_effort=reasoning_effort,
            response_format=response_format,
            timeout=timeout,
        )
        for model in models:
            params: dict[str, object] = {
                "model": model,
                "messages": messages,
                **optional_params,
            }
            completion = self._create_with_compat(params, model)
            if completion is None:
                # Stable event name; the per-stage prefix is structured context,
                # not interpolated into the event string (§7.2, COMMON-22).
                log.warning(
                    "llm.fallback_model_failed", stage=log_event_prefix, model=model
                )
                continue
            return completion.choices[0].message.content or ""

        return None

    @staticmethod
    def _optional_completion_params(
        *,
        reasoning_effort: str | None,
        response_format: dict[str, object] | None,
        timeout: float | None,
    ) -> dict[str, object]:
        """Build the dict of optional completion params, dropping every ``None``."""
        candidates: dict[str, object | None] = {
            "reasoning_effort": reasoning_effort,
            "response_format": response_format,
            "timeout": timeout,
        }
        return {key: value for key, value in candidates.items() if value is not None}


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
