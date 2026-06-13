"""Shared LLM helpers: retried chat completion, model dedup, thread-safe stats.

Module-global singletons
~~~~~~~~~~~~~~~~~~~~~~~~
``_openai_holder`` is a :class:`_ClientRegistry` holding one
:class:`openai.OpenAI` client per configured provider (``"openai"``,
``"ollama"``).  It is populated by
:func:`common.library_setup.setup_libraries` during
:func:`common.bootstrap.bootstrap_daemon`.  Calling
:func:`get_openai_client` before initialisation raises ``RuntimeError``.

Boot order: Settings -> logging -> ``setup_libraries`` (inits ``_openai_holder``)
-> signal handlers -> ``llm_limiter.init`` (see :mod:`common.concurrency`).
See :func:`common.bootstrap.bootstrap_daemon` for the canonical sequence.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from dataclasses import dataclass

import openai
import structlog
from openai.types.chat import ChatCompletion

from .concurrency import llm_limiter
from .model_compat import model_compat_cache
from .retry import retry

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LlmCallUsage:
    """Token usage for one successful LLM call, naming the model that actually
    served it (post-fallback). Produced by the shared completion helper and
    consumed by callers that pass a ``usage_sink`` (the search telemetry).

    ``provider`` is the registry key (``"openai"`` or ``"ollama"``) for the
    endpoint that served the call — the same value
    :attr:`OpenAIChatMixin._provider` returned for this step.  Search telemetry
    uses it to look up per-provider pricing so that mixed-provider queries cost
    correctly even when the planner, judge, and answer steps run on different
    endpoints.
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

# Param → stat-key lookup built once from the registry. Multiple rows may share
# the same param_key (e.g. response_format); the first entry wins, which is
# consistent with the linear scan it replaces (registry ordering is stable).
_PARAM_TO_STAT: dict[str, str] = {}
for _param, _matcher, _stat in _STRIPPABLE_PARAMS:
    _PARAM_TO_STAT.setdefault(_param, _stat)
del _param, _matcher, _stat  # clean up loop variables from module namespace


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
    """Thread-safe registry of the per-provider OpenAI-compatible chat clients.

    Per-step provider selection (e.g. OCR on Ollama while Search Answer is on
    OpenAI, in one process) needs *both* endpoints reachable at once, so the old
    single shared client became a two-slot registry keyed by provider.
    :func:`common.library_setup.setup_libraries` installs whichever slot the
    configured providers need (and clears one whose connection was removed on a
    hot-reload); a step selects its client by its own ``*_PROVIDER`` through
    :attr:`OpenAIChatMixin._provider`.
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
    """Back-compat: the OpenAI-slot chat client (preflight, tests)."""
    return _openai_holder.get("openai")


def is_openai_client_ready() -> bool:
    """Back-compat: whether the OpenAI-slot chat client is installed."""
    return _openai_holder.is_ready("openai")


def set_chat_client(provider: str, client: openai.OpenAI | None) -> None:
    """Install (``client``) or clear (``None``) the registry slot for *provider*.

    Used by :func:`common.library_setup.setup_libraries` to install both the
    OpenAI and Ollama chat clients (or clear one whose connection was removed on
    a hot-reload).
    """
    _openai_holder.init(provider, client)


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
        stat_key = _PARAM_TO_STAT.get(param_key)
        if stat_key is not None:
            self._increment_stat_if_declared(stat_key)

    def _increment_stat_if_declared(self, stat_key: str) -> None:
        """Increment *stat_key* only when this provider declared it in ``_STAT_KEYS``."""
        if stat_key in self._STAT_KEYS:
            self._stats.inc(stat_key)

    @property
    def _provider(self) -> str:
        """The provider whose chat client this step routes to.

        Defaults to ``"openai"``; each step provider (OCR, classifier, the three
        search stages) overrides it to return its own ``settings.*_PROVIDER`` so
        per-step provider selection picks the right client from the registry.
        """
        return "openai"

    @retry(retryable_exceptions=RETRYABLE_OPENAI_EXCEPTIONS)
    def _create_completion(self, **kwargs: object) -> ChatCompletion:
        client = _openai_holder.get(self._provider)
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

        rationale (§5.4 carve-out, COMMON-12/13): the ``None`` here is a
        *designed* per-model signal — "this model failed, try the next" — not a
        half-baked exception. The model-fallback chain in
        :meth:`_complete_with_model_fallback` needs a non-throwing failure to
        iterate its candidate models, and its callers (the planner and the
        synthesiser) have explicit graceful-degradation paths keyed on the
        terminal ``None``. Raising a domain ``LLMError`` instead would break
        those degradation contracts, so the asymmetry with
        :class:`~common.embeddings.EmbeddingError` (embeddings have no fallback
        chain, so they raise) is deliberate, not an oversight.
        """
        params = self._pre_strip_known_rejected(params, model)
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
        """Return a copy of *params* without every parameter the cache says
        *model* rejects.

        Pure: it does not mutate the *params* it is handed, so the function both
        returning a value and leaving its argument untouched read consistently
        (§1.1/§4.1, COMMON-23).
        """
        rejected = model_compat_cache.rejected_params_for(model)
        return {key: value for key, value in params.items() if key not in rejected}

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
        usage_sink: list[LlmCallUsage] | None = None,
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
            usage_sink: Optional list to which a :class:`LlmCallUsage` record is
                appended on each successful call. Absent usage fields default to
                zero (guarding Ollama/older providers that omit them). When
                ``None`` (the default), no capture occurs.

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
