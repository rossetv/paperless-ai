"""Pure parsing, validation, and clamping helpers for configuration values.

Every helper takes a string mapping (the environment, or the config table
layered over it) and returns a parsed, validated value — raising ``ValueError``
naming the offending variable on bad input, fail-closed at config-build time
(CODE_GUIDELINES §1.11, §6.6). No I/O, no state: these are the building blocks
:func:`common.config._settings._build_settings` composes into a
:class:`~common.config._settings.Settings`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import structlog

log = structlog.get_logger(__name__)

# Default Ollama base URL, used when LLM_PROVIDER=ollama and OLLAMA_BASE_URL is
# unset. Lives here because the provider-default resolver in _settings imports
# it; kept beside the parsers that share the "coded default" role.
_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1/"

# ---------------------------------------------------------------------------
# String-mapping parsing helpers (pure functions)
# ---------------------------------------------------------------------------


def _get_required_env(source: Mapping[str, str], var_name: str) -> str:
    """Return *var_name* from *source*, raising ``ValueError`` if it is unset.

    An absent key, an empty string and a whitespace-only string are all
    treated as "unset" — a required secret that round-trips ``""`` through
    the Settings API (e.g. an admin saved ``PAPERLESS_TOKEN=""``) must be
    rejected at this boundary rather than discovered when a daemon
    authenticates with an empty token and Paperless answers 401.
    """
    value = source.get(var_name)
    if value is None or not value.strip():
        raise ValueError(f"Required environment variable '{var_name}' is not set.")
    return value


def _get_int_env(source: Mapping[str, str], var_name: str, default: int) -> int:
    """Parse *var_name* from *source* as an integer, falling back to *default*.

    An unset, empty, or whitespace-only value falls back to *default* — the
    Settings UI round-trips a cleared numeric field as ``""``, so a blanked
    field must mean "use the coded default" rather than crash the daemon on its
    next hot-reload. This mirrors :func:`_get_optional_int_env`'s blank handling
    so the required-int and optional-int paths agree (COMMON-20).

    Raises a ``ValueError`` naming *var_name* when the value is set to a
    non-blank string that is not a valid integer.
    """
    raw = source.get(var_name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{var_name} must be an integer, got {raw!r}.") from exc


def _get_optional_int_env(
    source: Mapping[str, str], var_name: str, default: int | None = None
) -> int | None:
    """Parse *var_name* from *source* as an integer, returning *default* when
    unset or blank."""
    raw = source.get(var_name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{var_name} must be an integer, got {raw!r}.") from exc


def _get_optional_positive_int_env(
    source: Mapping[str, str], var_name: str, default: int | None = None
) -> int | None:
    """Like :func:`_get_optional_int_env`, but maps a non-positive value to None."""
    value = _get_optional_int_env(source, var_name, default)
    if value is not None and value <= 0:
        return None
    return value


def _get_csv_env(
    source: Mapping[str, str],
    var_name: str,
    default: list[str],
    *,
    require_non_empty: bool = False,
) -> list[str]:
    """Parse a comma-separated value from *source*, falling back to *default*.

    When *require_non_empty* is ``True``, raises ``ValueError`` if the value
    is set but yields no items (used for model lists).
    """
    value = source.get(var_name)
    if value is None:
        return [item for item in default if item]
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if require_non_empty and not parts:
        raise ValueError(f"{var_name} must contain at least one model name.")
    return parts


def _get_bool_env(source: Mapping[str, str], var_name: str, default: bool) -> bool:
    """Parse *var_name* from *source* as a boolean, falling back to *default*.

    An unset, empty, or whitespace-only value falls back to *default*, matching
    the numeric parsers (COMMON-20). A blank boolean is reachable and its
    rejection was unrecoverable: ``STALE_LOCK_RECOVERY=`` in a compose file is
    copied verbatim into the ``config`` table by ``appdb.config.seed_from_env``,
    so raising here failed every daemon's boot *and* every Settings save (which
    rebuilds the whole merged configuration to validate it) — leaving no way to
    clear the value through the UI that wrote it.

    Raises a ``ValueError`` naming *var_name* when the value is set to a
    non-blank string that is not a recognised boolean.
    """
    value = source.get(var_name)
    if value is None or not value.strip():
        return default
    value = value.strip().lower()
    if value in ("1", "true", "yes", "y", "on"):
        return True
    if value in ("0", "false", "no", "n", "off"):
        return False
    raise ValueError(f"{var_name} must be a boolean value.")


def _get_float_env(source: Mapping[str, str], var_name: str, default: float) -> float:
    """Parse *var_name* from *source* as a float, falling back to *default*.

    A non-numeric value raises a ``ValueError`` naming *var_name* — a typo'd
    float cost knob fails loud at startup rather than silently defaulting
    (CODE_GUIDELINES §1.11). Unset or blank falls back to *default*.
    """
    raw = source.get(var_name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{var_name} must be a number, got {raw!r}.") from exc


def _require_at_least_one(var_name: str, value: int, minimum: int = 1) -> int:
    """Return *value*, raising a contextful ``ValueError`` if it is below *minimum*."""
    if value < minimum:
        raise ValueError(f"{var_name} must be >= {minimum}")
    return value


def _resolve_llm_provider(source: Mapping[str, str]) -> Literal["openai", "ollama"]:
    """Resolve and validate ``LLM_PROVIDER`` (defaults to ``openai``)."""
    provider = source.get("LLM_PROVIDER", "openai")
    if provider not in ("openai", "ollama"):
        raise ValueError("LLM_PROVIDER must be 'openai' or 'ollama'")
    # rationale: validated above; mypy cannot narrow `str` → `Literal[...]`.
    return provider  # type: ignore[return-value]


def _resolve_embedding_provider(
    source: Mapping[str, str],
) -> Literal["openai", "ollama"]:
    """Resolve and validate ``EMBEDDING_PROVIDER`` (defaults to ``openai``).

    The embedding provider decides whether document chunks are vectorised by
    OpenAI or a local Ollama model. It is **independent of ``LLM_PROVIDER``**
    and defaults to ``openai`` — chat and embeddings are chosen separately, so
    flipping the chat provider never moves the embedding space (and so never
    triggers a re-embed). A fully-local deployment sets
    ``EMBEDDING_PROVIDER=ollama`` explicitly.

    A blank or unset value is the ``openai`` default; any non-blank value other
    than ``openai`` / ``ollama`` fails closed naming the key (CODE_GUIDELINES
    §1.11), mirroring :func:`_resolve_llm_provider`.
    """
    raw = source.get("EMBEDDING_PROVIDER")
    if raw is None or not raw.strip():
        return "openai"
    provider = raw.strip()
    if provider not in ("openai", "ollama"):
        raise ValueError("EMBEDDING_PROVIDER must be 'openai' or 'ollama'")
    # rationale: validated above; mypy cannot narrow `str` → `Literal[...]`.
    return provider  # type: ignore[return-value]


def _resolve_step_provider(
    source: Mapping[str, str],
    key: str,
    default: Literal["openai", "ollama"],
) -> Literal["openai", "ollama"]:
    """Resolve a per-step provider key (``OCR_PROVIDER``, ``CLASSIFY_PROVIDER``,
    ``SEARCH_PLANNER_PROVIDER`` / ``_JUDGE_`` / ``_ANSWER_``).

    Mirrors :func:`_resolve_embedding_provider`: a blank or unset value resolves
    to *default* — the per-step keys seed from ``LLM_PROVIDER`` (and the judge
    seeds from the planner) so an existing deployment that set only
    ``LLM_PROVIDER`` keeps behaving identically. Any non-blank value other than
    ``openai`` / ``ollama`` fails closed naming the key (CODE_GUIDELINES §1.11).
    """
    raw = source.get(key)
    if raw is None or not raw.strip():
        return default
    provider = raw.strip()
    if provider not in ("openai", "ollama"):
        raise ValueError(f"{key} must be 'openai' or 'ollama'")
    # rationale: validated above; mypy cannot narrow `str` → `Literal[...]`.
    return provider  # type: ignore[return-value]


def _resolve_log_format(source: Mapping[str, str]) -> Literal["json", "console"]:
    """Resolve and validate ``LOG_FORMAT`` (defaults to ``console``)."""
    log_format = source.get("LOG_FORMAT", "console")
    if log_format not in ("json", "console"):
        raise ValueError("LOG_FORMAT must be 'json' or 'console'")
    # rationale: validated above; mypy cannot narrow `str` → `Literal[...]`.
    return log_format  # type: ignore[return-value]


def _resolve_ocr_image_detail(
    source: Mapping[str, str],
) -> Literal["low", "high", "auto"]:
    """Resolve and validate ``OCR_IMAGE_DETAIL`` (defaults to ``high``).

    Mirrors the OpenAI chat-vision ``image_url.detail`` field. Defaulting to
    ``high`` keeps the OCR request byte-identical to the value hardcoded before
    this setting existed; an operator opts into the cheaper ``auto`` / ``low``
    paths explicitly.
    """
    detail = source.get("OCR_IMAGE_DETAIL", "high")
    if detail not in ("low", "high", "auto"):
        raise ValueError("OCR_IMAGE_DETAIL must be 'low', 'high', or 'auto'")
    # rationale: validated above; mypy cannot narrow `str` → `Literal[...]`.
    return detail  # type: ignore[return-value]


# Allowed reasoning-effort values. Matches the live OpenAI API (verified
# 2026-07-15 with one test call per value against gpt-5.6-sol/-terra/-luna and
# gpt-5.4-mini): every current model reports supported values
# none/low/medium/high/xhigh. "minimal" is gone from every current model and
# is coerced to "none" below for configs saved before this change. "max" is
# deliberately absent: the docs' model-index chips list it but the live API
# rejects it on every 5.6 model, and a rejected effort gets stripped by the
# compat layer so the model silently runs at its own default ("medium") —
# more expensive than the operator asked for. Do not add values from docs
# alone; verify against the live API first.
_REASONING_EFFORT_CHOICES: frozenset[str] = frozenset(
    {"none", "low", "medium", "high", "xhigh"}
)


def _resolve_reasoning_effort(
    source: Mapping[str, str], var_name: str, default: str = "medium"
) -> str:
    """Resolve and validate a reasoning-effort knob, returning a normalised string.

    Shared by OCR, classify, and search-stage resolvers, each passing its own
    step-specific *default*: OCR ``"none"`` and classify ``"low"`` spend the
    minimum reasoning tier on their high-volume, low-deliberation calls, while
    the search planner/answer stages keep ``"medium"`` — the models' own
    default effort, a deliberate zero-cost no-op. The operator tunes the knob
    up or down from the step's default to trade cost against reasoning depth.
    A model that does not accept the parameter has it stripped and cached by
    the shared adaptive-compat layer rather than failing the call
    (foundation-llm-plumbing-design §4.1, spec §4.8).

    Raises ``ValueError`` naming *var_name* on an unrecognised value so that
    typos fail loud at startup rather than silently sending a wrong effort
    (CODE_GUIDELINES §1.11).

    Args:
        source: The environment mapping.
        var_name: The setting key — named in the error message on a bad value.
        default: The coded default effort for this step (``"medium"`` unless
            the caller passes its own step-specific default).
    """
    effort = source.get(var_name, default).strip().lower()
    if effort == "minimal":
        # Legacy tier removed by OpenAI (verified 2026-07-15). Validation
        # fails closed at daemon startup AND on every Settings save, so
        # raising here would brick a stored config the UI could no longer
        # edit. "none" is the nearest current tier — minimal sat below "low"
        # on the old scale.
        log.warning(
            "config.reasoning_effort_minimal_coerced",
            var_name=var_name,
            coerced_to="none",
        )
        effort = "none"
    if effort not in _REASONING_EFFORT_CHOICES:
        raise ValueError(
            f"{var_name} must be one of "
            f"{sorted(_REASONING_EFFORT_CHOICES)}, got {effort!r}."
        )
    return effort


def _resolve_ocr_reasoning_effort(
    source: Mapping[str, str],
) -> Literal["none", "low", "medium", "high", "xhigh"]:
    """Resolve and validate ``OCR_REASONING_EFFORT`` (defaults to ``none``).

    Transcription is perception, not reasoning, and OCR is the highest-volume
    call in the system (one per page), so the default spends zero reasoning
    tokens. An operator opts *up* to ``low``+ if transcription quality on
    complex layouts ever warrants it.
    """
    # rationale: validated by shared helper; mypy cannot narrow `str` → `Literal[...]`.
    return _resolve_reasoning_effort(source, "OCR_REASONING_EFFORT", default="none")  # type: ignore[return-value]


def _resolve_classify_reasoning_effort(source: Mapping[str, str]) -> str:
    """Resolve and validate ``CLASSIFY_REASONING_EFFORT`` (defaults to ``low``).

    Schema-constrained extraction needs little deliberation, so the default
    spends only the minimum reasoning tier rather than the model's own
    ``medium`` default.
    """
    return _resolve_reasoning_effort(source, "CLASSIFY_REASONING_EFFORT", default="low")


def _resolve_search_reasoning_effort(
    source: Mapping[str, str], var_name: str, default: str = "medium"
) -> str:
    """Resolve and validate a search-stage reasoning-effort knob.

    Args:
        source: The environment mapping.
        var_name: The setting key (planner / answer / judge effort) — named in
            the error on a typo.
        default: The coded default effort (``"medium"`` unless specified; the
            judge passes ``"low"``).
    """
    return _resolve_reasoning_effort(source, var_name, default)


def _resolve_chunk_overlap(source: Mapping[str, str], chunk_size: int) -> int:
    """Resolve and validate ``CHUNK_OVERLAP`` against *chunk_size*.

    The overlap must be non-negative and strictly less than the chunk size,
    otherwise a chunk could never advance past its own overlap.
    """
    chunk_overlap = _get_int_env(source, "CHUNK_OVERLAP", 256)
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError(
            f"CHUNK_OVERLAP must be >= 0 and < CHUNK_SIZE ({chunk_size}), "
            f"got {chunk_overlap}."
        )
    return chunk_overlap


def _resolve_search_max_refinements(source: Mapping[str, str]) -> int:
    """Resolve and validate ``SEARCH_MAX_REFINEMENTS`` — any non-negative count.

    There is no hard cap: the operator sets the number of agentic refinement
    passes from the UI. Each pass costs one planner (re-)call, one optional
    judge call, and one synthesiser call, so the chat-call ceiling is
    ``(2 + j) * (1 + SEARCH_MAX_REFINEMENTS)`` where ``j`` is 1 when
    ``SEARCH_GATE_JUDGE`` is on — 6 calls at shipped defaults, not 3 — and
    cost/latency scale with it. Only a negative value is rejected.
    """
    value = _get_int_env(source, "SEARCH_MAX_REFINEMENTS", 1)
    if value < 0:
        raise ValueError(f"SEARCH_MAX_REFINEMENTS must be >= 0, got {value}.")
    return value


@dataclass(frozen=True, slots=True)
class RelevanceTiers:
    """The three relevance-badge cut-point floats resolved together.

    Returned by :func:`_resolve_relevance_tiers` so the caller unpacks by
    name (``tiers.strong``, ``tiers.good``, ``tiers.partial``) rather than
    by position — guarding against a silent swap that would miscalibrate the
    badges (CODE_GUIDELINES §5.8).
    """

    strong: float
    good: float
    partial: float


def _resolve_relevance_tiers(source: Mapping[str, str]) -> RelevanceTiers:
    """Resolve and validate the three relevance-badge cut-points together.

    Parses ``SEARCH_RELEVANCE_TIER_STRONG`` / ``_GOOD`` / ``_PARTIAL`` (defaults
    0.70 / 0.66 / 0.60, calibrated against a ``text-embedding-3-large`` @
    3072-dim index — see the field docstrings for the caveat when running on
    the default ``text-embedding-3-small`` / 1536-dim model) and enforces the
    badge invariant ``0 ≤ partial ≤ good ≤ strong ≤ 1`` — each value is a
    vector similarity in [0, 1], and the bands must not cross or a tier becomes
    unreachable. A value outside the range, or one that breaks the ordering,
    raises ``ValueError`` naming the offending key so the Settings API surfaces
    a precise message (fail-closed at config-build time, CODE_GUIDELINES §1.11).
    Equal adjacent cut-points are allowed (they collapse a band rather than
    corrupt it).

    Returns:
        A :class:`RelevanceTiers` named triple — strong, good, partial.
    """
    strong = _get_float_env(source, "SEARCH_RELEVANCE_TIER_STRONG", 0.70)
    good = _get_float_env(source, "SEARCH_RELEVANCE_TIER_GOOD", 0.66)
    partial = _get_float_env(source, "SEARCH_RELEVANCE_TIER_PARTIAL", 0.60)

    for key, value in (
        ("SEARCH_RELEVANCE_TIER_STRONG", strong),
        ("SEARCH_RELEVANCE_TIER_GOOD", good),
        ("SEARCH_RELEVANCE_TIER_PARTIAL", partial),
    ):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{key} must be between 0.0 and 1.0, got {value}.")

    if not partial <= good <= strong:
        raise ValueError(
            "Relevance tiers must be ordered "
            "SEARCH_RELEVANCE_TIER_PARTIAL <= SEARCH_RELEVANCE_TIER_GOOD <= "
            f"SEARCH_RELEVANCE_TIER_STRONG, got partial={partial}, good={good}, "
            f"strong={strong}."
        )
    return RelevanceTiers(strong=strong, good=good, partial=partial)


def _resolve_server_port(source: Mapping[str, str]) -> int:
    """Resolve and validate ``SEARCH_SERVER_PORT`` to the valid TCP port range."""
    port = _get_int_env(source, "SEARCH_SERVER_PORT", 8080)
    if not 1 <= port <= 65535:
        raise ValueError(f"SEARCH_SERVER_PORT must be between 1 and 65535, got {port}.")
    return port


def _resolve_pricing_refresh_url(source: Mapping[str, str]) -> str:
    """Resolve and validate ``PRICING_REFRESH_URL`` (defaults to ``""`` = disabled).

    An empty, unset, or whitespace-only value means the price-refresh feature is
    disabled — the price book uses the bundled seed only, makes no network call,
    and prices the identical dollar figures the hardcoded table did. This is the
    default and prod's configuration.

    A non-empty value must be an absolute ``http``/``https`` URL with a host;
    anything else (a bare path, a ``file://`` URL, a typo'd scheme) fails closed
    naming the key (CODE_GUIDELINES §1.11, §10.8) rather than being discovered
    when the first refresh fails. The URL is returned stripped of surrounding
    whitespace; no trailing-slash normalisation is applied because it is fetched
    verbatim, not used as a base for path joins.
    """
    raw = source.get("PRICING_REFRESH_URL", "")
    url = raw.strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(
            "PRICING_REFRESH_URL must be an absolute http:// or https:// URL "
            f"(or empty to disable), got {raw!r}."
        )
    return url
