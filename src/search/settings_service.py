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

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from common.config import (
    CONFIG_KEYS,
    REINDEX_KEYS,
    SECRET_KEYS,
    _build_settings,
)

# Where a key's effective value came from, in precedence order.
ValueSource = Literal["database", "environment", "default"]


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
    """

    key: str
    effective_value: str | None
    source: ValueSource
    is_secret: bool


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
        raise ValueError(
            f"unknown configuration key(s): {', '.join(sorted(unknown))}"
        )

    # Build the would-be merged mapping and run the real Settings builder; it
    # raises ValueError naming the offending key on any invalid value.
    merged: dict[str, str] = dict(environ)
    merged.update(config_table)
    merged.update(changes)
    _build_settings(merged)  # raises ValueError on a bad value

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
