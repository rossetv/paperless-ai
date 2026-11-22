"""Pure parsing and validation helpers for configuration values.

Each takes a string mapping and raises ``ValueError`` naming the variable on bad
input, so a misconfiguration fails at config-build time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import structlog

log = structlog.get_logger(__name__)

# Used when an Ollama provider is chosen and OLLAMA_BASE_URL is unset.
_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1/"


def _get_required_env(source: Mapping[str, str], var_name: str) -> str:
    """Return *var_name* from *source*, raising ``ValueError`` if it is unset.

    Blank counts as unset: a secret saved as ``""`` through the Settings API
    must be rejected here, not discovered when Paperless answers 401.
    """
    value = source.get(var_name)
    if value is None or not value.strip():
        raise ValueError(f"Required environment variable '{var_name}' is not set.")
    return value


def _get_str_env(source: Mapping[str, str], var_name: str, default: str) -> str:
    """Return *var_name* stripped, falling back to *default* when unset or blank.

    A blank value such as ``LOG_FORMAT=`` in a compose file means "not set",
    not an empty string that breaks at use.
    """
    value = source.get(var_name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _get_int_env(source: Mapping[str, str], var_name: str, default: int) -> int:
    """Parse *var_name* from *source* as an integer, falling back to *default*.

    Blank also falls back: the Settings UI saves a cleared numeric field as
    ``""``, which must mean "use the default", not crash the next hot-reload.
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

    When *require_non_empty* is ``True`` (model lists), a blank value counts as
    unset and gives *default*, while a value such as ``","`` that is set but
    yields no items raises ``ValueError``.
    """
    value = source.get(var_name)
    if value is None or (require_non_empty and not value.strip()):
        return [item for item in default if item]
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if require_non_empty and not parts:
        raise ValueError(f"{var_name} must contain at least one model name.")
    return parts


def _get_bool_env(source: Mapping[str, str], var_name: str, default: bool) -> bool:
    """Parse *var_name* from *source* as a boolean, falling back to *default*.

    Blank also falls back. A blank such as ``STALE_LOCK_RECOVERY=`` in a compose
    file is seeded verbatim into the config table, and rejecting it would fail
    every boot and every Settings save, leaving no way to fix it from the UI.
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

    Blank falls back; a non-numeric value raises rather than silently
    defaulting.
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
    provider = _get_str_env(source, "LLM_PROVIDER", "openai")
    if provider not in ("openai", "ollama"):
        raise ValueError("LLM_PROVIDER must be 'openai' or 'ollama'")
    # Validated above; mypy cannot narrow `str` to the Literal.
    return provider  # type: ignore[return-value]


def _resolve_embedding_provider(
    source: Mapping[str, str],
) -> Literal["openai", "ollama"]:
    """Resolve and validate ``EMBEDDING_PROVIDER`` (defaults to ``openai``).

    Independent of ``LLM_PROVIDER``, so switching the chat provider never moves
    the embedding space and never forces a re-embed. Blank means ``openai``.
    """
    raw = source.get("EMBEDDING_PROVIDER")
    if raw is None or not raw.strip():
        return "openai"
    provider = raw.strip()
    if provider not in ("openai", "ollama"):
        raise ValueError("EMBEDDING_PROVIDER must be 'openai' or 'ollama'")
    # Validated above; mypy cannot narrow `str` to the Literal.
    return provider  # type: ignore[return-value]


def _resolve_step_provider(
    source: Mapping[str, str],
    key: str,
    default: Literal["openai", "ollama"],
) -> Literal["openai", "ollama"]:
    """Resolve a per-step provider key (``OCR_PROVIDER``, ``CLASSIFY_PROVIDER``,
    ``SEARCH_PLANNER_PROVIDER`` / ``_JUDGE_`` / ``_ANSWER_``).

    Blank resolves to *default*, which callers seed from ``LLM_PROVIDER`` (the
    judge from the planner), so a deployment that set only ``LLM_PROVIDER``
    behaves the same.
    """
    raw = source.get(key)
    if raw is None or not raw.strip():
        return default
    provider = raw.strip()
    if provider not in ("openai", "ollama"):
        raise ValueError(f"{key} must be 'openai' or 'ollama'")
    # Validated above; mypy cannot narrow `str` to the Literal.
    return provider  # type: ignore[return-value]


def _resolve_log_format(source: Mapping[str, str]) -> Literal["json", "console"]:
    """Resolve and validate ``LOG_FORMAT`` (defaults to ``console``)."""
    log_format = _get_str_env(source, "LOG_FORMAT", "console")
    if log_format not in ("json", "console"):
        raise ValueError("LOG_FORMAT must be 'json' or 'console'")
    # Validated above; mypy cannot narrow `str` to the Literal.
    return log_format  # type: ignore[return-value]


def _resolve_ocr_image_detail(
    source: Mapping[str, str],
) -> Literal["low", "high", "auto"]:
    """Resolve and validate ``OCR_IMAGE_DETAIL`` (defaults to ``high``).

    Mirrors OpenAI's ``image_url.detail``; the cheaper ``auto`` / ``low`` are
    opt-in.
    """
    detail = _get_str_env(source, "OCR_IMAGE_DETAIL", "high")
    if detail not in ("low", "high", "auto"):
        raise ValueError("OCR_IMAGE_DETAIL must be 'low', 'high', or 'auto'")
    # Validated above; mypy cannot narrow `str` to the Literal.
    return detail  # type: ignore[return-value]


# What the live OpenAI API accepts (checked 2026-07-15 against gpt-5.6-sol,
# -terra, -luna and gpt-5.4-mini). "minimal" no longer exists and is coerced to
# "none" below. "max" is listed in the docs but rejected by the API, and the
# compat layer would strip it so the model silently runs at its pricier default.
# Verify against the live API before adding a value.
_REASONING_EFFORT_CHOICES: frozenset[str] = frozenset(
    {"none", "low", "medium", "high", "xhigh"}
)


def _resolve_reasoning_effort(
    source: Mapping[str, str], var_name: str, default: str = "medium"
) -> str:
    """Resolve and validate a reasoning-effort knob, returning a normalised string.

    Each step passes its own *default*. A model that rejects the parameter has
    it stripped by the adaptive-compat layer rather than failing the call. An
    unrecognised value raises rather than silently sending the wrong effort.
    """
    effort = _get_str_env(source, var_name, default).lower()
    if effort == "minimal":
        # Raising would brick a stored config: validation runs on every boot
        # and every Settings save. "none" is the nearest tier below "low".
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
    call (one per page), so the default spends no reasoning tokens.
    """
    # Validated by the shared helper; mypy cannot narrow `str` to the Literal.
    return _resolve_reasoning_effort(source, "OCR_REASONING_EFFORT", default="none")  # type: ignore[return-value]


def _resolve_classify_reasoning_effort(source: Mapping[str, str]) -> str:
    """Resolve and validate ``CLASSIFY_REASONING_EFFORT`` (defaults to ``low``).

    Schema-constrained extraction needs little deliberation.
    """
    return _resolve_reasoning_effort(source, "CLASSIFY_REASONING_EFFORT", default="low")


def _resolve_search_reasoning_effort(
    source: Mapping[str, str], var_name: str, default: str = "medium"
) -> str:
    """Resolve and validate a search-stage reasoning-effort knob."""
    return _resolve_reasoning_effort(source, var_name, default)


def _resolve_chunk_overlap(source: Mapping[str, str], chunk_size: int) -> int:
    """Resolve and validate ``CHUNK_OVERLAP`` against *chunk_size*.

    The overlap must be below the chunk size, or a chunk could never advance
    past its own overlap.
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

    No upper cap. Each pass costs a planner call, an optional judge call and a
    synthesiser call, so the chat-call ceiling is
    ``(2 + j) * (1 + SEARCH_MAX_REFINEMENTS)`` with ``j`` = 1 when
    ``SEARCH_GATE_JUDGE`` is on (6 calls at the defaults).
    """
    value = _get_int_env(source, "SEARCH_MAX_REFINEMENTS", 1)
    if value < 0:
        raise ValueError(f"SEARCH_MAX_REFINEMENTS must be >= 0, got {value}.")
    return value


@dataclass(frozen=True, slots=True)
class RelevanceTiers:
    """The three relevance-badge cut-points.

    Named fields rather than a tuple, so a silent swap cannot miscalibrate the
    badges.
    """

    strong: float
    good: float
    partial: float


def _resolve_relevance_tiers(source: Mapping[str, str]) -> RelevanceTiers:
    """Resolve and validate the three relevance-badge cut-points together.

    Defaults 0.70 / 0.66 / 0.60 are calibrated on a
    ``text-embedding-3-large`` 3072-dim index (see the field docstrings for the
    1536-dim caveat). Enforces ``0 <= partial <= good <= strong <= 1``, since
    crossed bands make a tier unreachable; equal cut-points just collapse a band.
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

    Blank disables refresh: the bundled seed is used and no network call is
    made. Otherwise it must be an absolute ``http``/``https`` URL with a host,
    rejected now rather than on the first failed refresh. No trailing-slash
    normalisation: the URL is fetched verbatim, never joined.
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
