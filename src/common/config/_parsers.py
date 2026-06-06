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
from typing import Literal

# Default Ollama base URL, used when LLM_PROVIDER=ollama and OLLAMA_BASE_URL is
# unset. Lives here because the provider-default resolver in _settings imports
# it; kept beside the parsers that share the "coded default" role.
_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1/"

# Hard ceiling on SEARCH_MAX_REFINEMENTS. The agentic pipeline's three-LLM-call
# budget (CODE_GUIDELINES §14.3) is a correctness and cost property, not a
# tuning knob: planner (1) + retrieve + refine. SEARCH_MAX_REFINEMENTS counts
# refinement steps, so it is capped here rather than left unbounded.
_SEARCH_MAX_REFINEMENTS_CEILING = 3

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
    """Parse *var_name* from *source* as a boolean, falling back to *default*."""
    value = source.get(var_name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in ("1", "true", "yes", "y", "on"):
        return True
    if value in ("0", "false", "no", "n", "off"):
        return False
    raise ValueError(f"{var_name} must be a boolean value.")


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


def _resolve_ocr_reasoning_effort(
    source: Mapping[str, str],
) -> Literal["minimal", "low", "medium", "high"]:
    """Resolve and validate ``OCR_REASONING_EFFORT`` (defaults to ``medium``).

    Shares the classifier's ``_REASONING_EFFORT_CHOICES`` set and fail-closed
    contract (the OpenAI 1.109.1 ``ReasoningEffort`` literal). ``medium`` is the
    models' own default effort, so the default value keeps the OCR request
    behaviourally identical to before this setting existed; an operator opts into
    the cheaper ``minimal`` / ``low`` tiers explicitly to cut the reasoning-token
    premium on the highest-volume call.
    """
    effort = source.get("OCR_REASONING_EFFORT", "medium").strip().lower()
    if effort not in _REASONING_EFFORT_CHOICES:
        raise ValueError(
            "OCR_REASONING_EFFORT must be one of "
            f"{sorted(_REASONING_EFFORT_CHOICES)}, got {effort!r}."
        )
    # rationale: validated above; mypy cannot narrow `str` → `Literal[...]`.
    return effort  # type: ignore[return-value]


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
    """Resolve and validate ``SEARCH_MAX_REFINEMENTS`` against the §14.3 ceiling."""
    value = _get_int_env(source, "SEARCH_MAX_REFINEMENTS", 1)
    if not 0 <= value <= _SEARCH_MAX_REFINEMENTS_CEILING:
        # The three-LLM-call budget is a hard correctness property, not a knob.
        raise ValueError(
            f"SEARCH_MAX_REFINEMENTS must be between 0 and "
            f"{_SEARCH_MAX_REFINEMENTS_CEILING} (the §14.3 three-LLM-call "
            f"budget), got {value}."
        )
    return value


def _resolve_server_port(source: Mapping[str, str]) -> int:
    """Resolve and validate ``SEARCH_SERVER_PORT`` to the valid TCP port range."""
    port = _get_int_env(source, "SEARCH_SERVER_PORT", 8080)
    if not 1 <= port <= 65535:
        raise ValueError(f"SEARCH_SERVER_PORT must be between 1 and 65535, got {port}.")
    return port


# Allowed reasoning-effort values for the classifier. Matches the installed
# OpenAI SDK's ``ReasoningEffort`` literal (openai 1.109.1,
# openai/types/shared/reasoning_effort.py): all four of minimal/low/medium/high.
# "none" is intentionally excluded — it is not in that literal.
_REASONING_EFFORT_CHOICES: frozenset[str] = frozenset(
    {"minimal", "low", "medium", "high"}
)


def _resolve_classify_reasoning_effort(source: Mapping[str, str]) -> str:
    """Resolve and validate ``CLASSIFY_REASONING_EFFORT`` (defaults to ``medium``).

    ``medium`` is the models' own default effort, so the default is a deliberate,
    zero-cost no-op: it pins the knob and lets each environment tune *down* (to
    ``low``/``minimal``) to capture the saving. A model that does not accept the
    parameter never has it forced on it: the shared adaptive-compat layer strips
    ``reasoning_effort`` on a 400 and caches the rejection per model
    (foundation-llm-plumbing-design §4.1).
    """
    effort = source.get("CLASSIFY_REASONING_EFFORT", "medium").strip().lower()
    if effort not in _REASONING_EFFORT_CHOICES:
        raise ValueError(
            "CLASSIFY_REASONING_EFFORT must be one of "
            f"{sorted(_REASONING_EFFORT_CHOICES)}, got {effort!r}."
        )
    return effort


def _resolve_search_reasoning_effort(source: Mapping[str, str], var_name: str) -> str:
    """Resolve and validate a search-stage reasoning-effort knob (defaults ``medium``).

    Shares the classifier's ``_REASONING_EFFORT_CHOICES`` set and fail-closed
    contract: an unrecognised value raises a ``ValueError`` naming *var_name* at
    startup rather than silently sending a wrong (or, once the adaptive-compat
    layer strips it, no) effort. ``medium`` is the models' own default effort, so
    the default is a deliberate, zero-cost no-op the operator tunes *down* (to
    ``low``/``minimal``) per stage to capture the saving (spec §4.8).

    Args:
        source: The environment mapping.
        var_name: The setting key (``SEARCH_PLANNER_REASONING_EFFORT`` or
            ``SEARCH_ANSWER_REASONING_EFFORT``) — named in the error on a typo.
    """
    effort = source.get(var_name, "medium").strip().lower()
    if effort not in _REASONING_EFFORT_CHOICES:
        raise ValueError(
            f"{var_name} must be one of "
            f"{sorted(_REASONING_EFFORT_CHOICES)}, got {effort!r}."
        )
    return effort


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
