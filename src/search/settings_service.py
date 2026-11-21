"""Settings logic behind :mod:`search.settings_routes`, free of HTTP and DB.

- :func:`view_settings` resolves each key's effective value and its source.
- :func:`validate_change_set` rejects an invalid change before it is written.
- :func:`reindex_required` reports whether a change needs a full re-index.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from common.config import (
    CONFIG_KEYS,
    REINDEX_KEYS,
    SECRET_KEYS,
    build_settings,
)

# Where a key's effective value came from, in precedence order.
ValueSource = Literal["database", "environment", "default"]

# Per-step provider keys: a step may only select a provider whose connection
# is configured.
_STEP_PROVIDER_KEYS = (
    "OCR_PROVIDER",
    "CLASSIFY_PROVIDER",
    "SEARCH_PLANNER_PROVIDER",
    "SEARCH_JUDGE_PROVIDER",
    "SEARCH_ANSWER_PROVIDER",
    "EMBEDDING_PROVIDER",
)

# Coded defaults come from building Settings with placeholder secrets, so the
# builder parses every other key's default without real credentials.
_SENTINEL = "__defaults_probe__"

_defaults_instance = build_settings(
    {
        "PAPERLESS_TOKEN": _SENTINEL,
        "OPENAI_API_KEY": _SENTINEL,
    }
)


def _settings_to_str_map() -> dict[str, str | None]:
    """Map each config key to its coded default in config-table string form.

    Secrets map to ``None``: their placeholder values are not real defaults.
    """
    result: dict[str, str | None] = {}
    for f in dataclasses.fields(_defaults_instance):
        key = f.name
        if key not in CONFIG_KEYS:
            # Bootstrap keys and REFUSAL_MARK are not configurable.
            continue
        if key in SECRET_KEYS:
            result[key] = None
            continue
        raw = getattr(_defaults_instance, key)
        if isinstance(raw, bool):
            result[key] = "true" if raw else "false"
        elif isinstance(raw, list):
            result[key] = ", ".join(str(item) for item in raw)
        elif raw is None:
            result[key] = None
        else:
            result[key] = str(raw)
    return result


#: ``None`` for secret keys and optional keys whose default is ``None``.
_CODED_DEFAULTS: dict[str, str | None] = _settings_to_str_map()

# Fills missing secrets when building Settings only to validate other keys:
# an instance may not have its secrets configured yet.
_VALIDATION_SENTINEL = "__validation_placeholder__"


def _merged_for_build(
    *,
    config_table: Mapping[str, str],
    environ: Mapping[str, str],
    changes: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Layer *changes* over the config table over the environment, inject secret
    sentinels, and return a mapping ready for :func:`build_settings`."""
    merged: dict[str, str] = dict(environ)
    merged.update(config_table)
    if changes:
        merged.update(changes)
    for req in SECRET_KEYS:
        merged.setdefault(req, _VALIDATION_SENTINEL)
    return merged


def _is_openai_embedding_model(model: str) -> bool:
    """Whether *model* names an OpenAI embedding model (``text-embedding-*``)."""
    return model.startswith("text-embedding-")


@dataclass(frozen=True, slots=True)
class SettingView:
    """One config key as the Settings screen sees it.

    Attributes:
        effective_value: The ``config``-table value, else the environment
            value, else ``None`` when only the coded default applies.
        default_value: The coded default as a string, or ``None`` for secrets
            and keys whose default is ``None``.
    """

    key: str
    effective_value: str | None
    source: ValueSource
    is_secret: bool
    default_value: str | None


def view_settings(
    *,
    config_table: Mapping[str, str],
    environ: Mapping[str, str],
) -> list[SettingView]:
    """Return one :class:`SettingView` per config key, in sorted key order."""
    views: list[SettingView] = []
    for key in sorted(CONFIG_KEYS):
        if key in config_table:
            value: str | None = config_table[key]
            source: ValueSource = "database"
        elif key in environ:
            value = environ[key]
            source = "environment"
        else:
            value = None
            source = "default"
        views.append(
            SettingView(
                key=key,
                effective_value=value,
                source=source,
                is_secret=key in SECRET_KEYS,
                default_value=_CODED_DEFAULTS.get(key),
            )
        )
    return views


def validate_change_set(
    *,
    changes: Mapping[str, str],
    config_table: Mapping[str, str],
    environ: Mapping[str, str],
) -> set[str]:
    """Validate a proposed change and return the keys whose value differs.

    Every key must be known, and the result must build a valid
    :class:`Settings`, so a value that would stop a daemon from booting is
    rejected before it is written.

    Raises:
        ValueError: Naming the unknown key or the invalid value.
    """
    unknown = set(changes) - set(CONFIG_KEYS)
    if unknown:
        raise ValueError(f"unknown configuration key(s): {', '.join(sorted(unknown))}")

    merged = _merged_for_build(
        config_table=config_table, environ=environ, changes=changes
    )
    after = build_settings(merged)

    # Ollama cannot serve an OpenAI embedding model. Saving
    # EMBEDDING_PROVIDER=ollama with the default model would wipe the index
    # and then fail to re-embed, leaving search broken.
    if after.EMBEDDING_PROVIDER == "ollama" and _is_openai_embedding_model(
        after.EMBEDDING_MODEL
    ):
        raise ValueError(
            f"EMBEDDING_MODEL '{after.EMBEDDING_MODEL}' is an OpenAI model and "
            "cannot run on Ollama. Switching embeddings to Ollama wipes and "
            "rebuilds the whole index, so set EMBEDDING_MODEL to a local "
            "embedding model and EMBEDDING_DIMENSIONS to its width in the same "
            "save."
        )

    # A step may only select a provider whose connection is configured. Check
    # the raw merged source, not ``after``: the builder defaults
    # OLLAMA_BASE_URL to localhost and OPENAI_API_KEY holds a placeholder.
    raw_ollama_url = (merged.get("OLLAMA_BASE_URL") or "").strip()
    ollama_steps = [k for k in _STEP_PROVIDER_KEYS if getattr(after, k) == "ollama"]
    if ollama_steps and not raw_ollama_url:
        raise ValueError(
            "Configure OLLAMA_BASE_URL under Connections before selecting Ollama "
            f"for: {', '.join(ollama_steps)}."
        )
    # The OpenAI guard fires only when the change set selects OpenAI, so an
    # unrelated save never has to re-supply the masked OPENAI_API_KEY.
    raw_openai_key = (
        changes.get("OPENAI_API_KEY")
        or config_table.get("OPENAI_API_KEY")
        or environ.get("OPENAI_API_KEY")
        or ""
    ).strip()
    openai_selected = [k for k in _STEP_PROVIDER_KEYS if changes.get(k) == "openai"]
    if openai_selected and not raw_openai_key:
        raise ValueError(
            "Configure OPENAI_API_KEY under Connections before selecting OpenAI "
            f"for: {', '.join(openai_selected)}."
        )

    changed: set[str] = set()
    for key, new_value in changes.items():
        if key in config_table:
            current: str | None = config_table[key]
        else:
            current = environ.get(key)
        if new_value != current:
            changed.add(key)
    return changed


def reindex_required(
    *,
    changes: Mapping[str, str],
    config_table: Mapping[str, str],
    environ: Mapping[str, str],
) -> bool:
    """Return whether applying *changes* makes the existing index stale.

    True exactly when the resolved value of a
    :data:`common.config.REINDEX_KEYS` setting moves. The comparison is on the
    built :class:`~common.config.Settings`, not the raw keys, so a change that
    moves a re-index value indirectly is caught too.
    """
    before = build_settings(
        _merged_for_build(config_table=config_table, environ=environ)
    )
    after = build_settings(
        _merged_for_build(config_table=config_table, environ=environ, changes=changes)
    )
    return any(getattr(before, key) != getattr(after, key) for key in REINDEX_KEYS)
