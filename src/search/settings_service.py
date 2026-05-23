"""Read, diff and re-index-impact logic for the Settings API (web-redesign §5).

The Settings endpoints (:mod:`search.settings_routes`) are a thin HTTP shell;
the logic they need that is worth testing in isolation lives here, FastAPI-free:

- :func:`view_settings` resolves every config key to its *effective* value
  and *source* (``database`` / ``environment`` / ``default``), so the Settings
  screen can show where each value comes from.
- :func:`validate_change_set` checks a proposed change against the catalogue
  and against :func:`common.config._build_settings`, so an invalid value is
  rejected *before* it touches ``app.db``.
- :func:`reindex_required` reports whether any changed key needs a full
  document re-index. Saving hot-loads with no restart (spec §5); the only
  operator-facing consequence of a change is whether the index must be
  rebuilt — true exactly when a :data:`common.config.REINDEX_KEYS` key moved.

Allowed deps: common.config (the key catalogue and the settings builder).
Forbidden: fastapi, sqlite3, appdb (the routes layer owns the DB connection).
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

# ---------------------------------------------------------------------------
# Coded-default map — built once at module load.
#
# Call build_settings with sentinel placeholders for the two required secret
# keys so the builder can parse every other key's default without failing on
# missing credentials. The resulting Settings instance is converted field-by-
# field to a string map: that is _CODED_DEFAULTS.
#
# Keys absent from CONFIG_KEYS (BOOTSTRAP_KEYS, REFUSAL_MARK) are not in the
# map. Secret keys get None rather than their sentinel-built value — a secret
# has no meaningful coded default to show.
# ---------------------------------------------------------------------------
_SENTINEL = "__defaults_probe__"

_defaults_instance = build_settings(
    {
        "PAPERLESS_TOKEN": _SENTINEL,
        "OPENAI_API_KEY": _SENTINEL,
    }
)


def _settings_to_str_map() -> dict[str, str | None]:
    """Convert the coded-default Settings instance to a key→string-or-None map.

    Iterates every field on the dataclass, converts the value to the
    wire-string form the config table would store, and returns the map. Secret
    keys are mapped to ``None`` — their sentinel values are not meaningful
    defaults to surface in the UI.
    """
    result: dict[str, str | None] = {}
    for f in dataclasses.fields(_defaults_instance):
        key = f.name
        if key not in CONFIG_KEYS:
            # BOOTSTRAP_KEYS (APP_DB_PATH, INDEX_DB_PATH) and REFUSAL_MARK
            # are on Settings but not in CONFIG_KEYS — skip them.
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
            # Optional keys that default to None (e.g. OLLAMA_BASE_URL when
            # provider is openai) have no coded default to show.
            result[key] = None
        else:
            result[key] = str(raw)
    return result


#: Single source of truth for coded defaults, keyed by config-key name.
#: ``None`` for secret keys and optional keys whose default is ``None``.
_CODED_DEFAULTS: dict[str, str | None] = _settings_to_str_map()


@dataclass(frozen=True, slots=True)
class SettingView:
    """One config key as the Settings screen sees it.

    Attributes:
        key: The canonical config key (an env-var name).
        effective_value: The precedence-resolved string the daemons would
            load — the ``config``-table value, else the environment value,
            else ``None`` when only a coded default applies (the default
            itself is not re-derived here; ``None`` means "shows the default").
        source: ``database`` / ``environment`` / ``default`` — where
            *effective_value* came from.
        is_secret: Whether this key holds a secret and must be masked in API
            responses.
        default_value: The coded default as a string, or ``None`` when the key
            has no coded default (secrets, optional keys that default to
            ``None``). Surfaced so the Settings screen can display the default
            even when ``source`` is ``"default"`` and ``effective_value`` is
            ``None``.
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
    """Return one :class:`SettingView` per config key, precedence-resolved.

    Args:
        config_table: The ``config`` table as a key→value dict.
        environ: The process environment mapping.

    Returns:
        A :class:`SettingView` for every key in
        :data:`common.config.CONFIG_KEYS`, in sorted key order.
    """
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
    """Validate a proposed configuration change and return the changed keys.

    Two checks. First, every key in *changes* must be a known config key —
    an unknown key is a client error, not something to silently store.
    Second, the would-be result (the change set layered over the current
    table over the environment) must build a valid :class:`Settings`, so a
    value that would break a daemon's startup is rejected here rather than
    after it is written and a daemon later fails to boot.

    Args:
        changes: The proposed key→value changes from the request body.
        config_table: The current ``config`` table.
        environ: The process environment.

    Returns:
        The subset of *changes* keys whose value actually differs from the
        current effective value — the keys that genuinely changed.

    Raises:
        ValueError: A key is not a known config key, or the resulting
            configuration fails validation. The message names the offender.
    """
    unknown = set(changes) - set(CONFIG_KEYS)
    if unknown:
        raise ValueError(f"unknown configuration key(s): {', '.join(sorted(unknown))}")

    # Build the would-be merged mapping and run the real Settings builder; it
    # raises ValueError naming the offending key on any invalid value.
    merged: dict[str, str] = dict(environ)
    merged.update(config_table)
    merged.update(changes)
    # build_settings requires PAPERLESS_TOKEN and OPENAI_API_KEY — the same
    # two keys as SECRET_KEYS. They may be absent when the caller changes an
    # unrelated key on a fresh instance that has not yet been configured. Inject
    # sentinel values so the builder can validate the type/range of the changed
    # keys without failing on an unrelated missing required key.
    _VALIDATION_SENTINEL = "__validation_placeholder__"
    for req in SECRET_KEYS:
        merged.setdefault(req, _VALIDATION_SENTINEL)
    build_settings(merged)  # raises ValueError on a bad value

    # Determine which keys genuinely change. The current effective value is
    # the table value if present, else the environment value, else absent.
    changed: set[str] = set()
    for key, new_value in changes.items():
        if key in config_table:
            current: str | None = config_table[key]
        else:
            current = environ.get(key)
        if new_value != current:
            changed.add(key)
    return changed


def reindex_required(changed_keys: set[str]) -> bool:
    """Return whether *changed_keys* needs a full document re-index.

    Saving configuration hot-loads — no daemon restarts (spec §5). The one
    operator-facing consequence of a change is whether the existing index
    becomes stale: that happens exactly when a key governing chunking or the
    embedding model changes. This is true when *changed_keys* intersects
    :data:`common.config.REINDEX_KEYS`.

    Args:
        changed_keys: The config keys that actually changed.

    Returns:
        ``True`` when at least one changed key requires re-indexing every
        document; ``False`` otherwise (including for an empty change set).
    """
    return bool(changed_keys & set(REINDEX_KEYS))
