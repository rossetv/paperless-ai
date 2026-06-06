"""Environment-variable configuration for every daemon and the search server.

The :class:`Settings` dataclass is the single, immutable description of a
process's configuration. It is **frozen** (CODE_GUIDELINES §5.2): once built it
cannot be mutated, so no code path can change configuration mid-run.

Two construction paths exist:

* :func:`load_settings` — the production entry point. Layers the ``config``
  table (in ``app.db``) over the process environment, so a value in the table
  wins, then an environment variable, then the coded default.
* :meth:`Settings.from_environment` — the environment-only path, preserved
  for tests and any caller that has no ``app.db``. Parses, validates, and
  clamps every environment variable, raising ``ValueError`` with a message
  naming the offending variable (CODE_GUIDELINES §1.11, §6.6).

Both paths share :func:`_build_settings`: the same parsing, validation and
clamping is applied to whichever string mapping is presented as the source.

This is a package (CODE_GUIDELINES §3.3) — the old single ``config.py`` grew
past the §3.1 ceiling (COMMON-01). The three concerns are split into private
modules, with this ``__init__`` re-exporting the public surface so every
``from common.config import X`` keeps working unchanged:

* :mod:`._catalogue` — which keys exist (``BOOTSTRAP_KEYS``, ``SECRET_KEYS``,
  ``CONFIG_KEYS``, ``REINDEX_KEYS``).
* :mod:`._settings` — the :class:`Settings` shape, the parsing/validation
  helpers, and :func:`build_settings` / :func:`_build_settings`.
* :mod:`._loader` — the DB-backed :func:`load_settings` and the hot-load
  :func:`current_settings` / :func:`current_settings_with_version`.

The dependency arrows flow one way: ``_loader`` → ``_settings`` →
``_catalogue``. No cycle.
"""

from __future__ import annotations

from ._catalogue import BOOTSTRAP_KEYS, CONFIG_KEYS, REINDEX_KEYS, SECRET_KEYS
from ._loader import current_settings, current_settings_with_version, load_settings
from ._settings import Settings, build_settings

# Re-exported for the daemon and search-server tests that reset the hot-load
# cache between cases (e.g. tests/unit/search/test_api_hot_reload.py). Private,
# so it is deliberately absent from __all__; the redundant alias marks the
# re-export as intentional for the linter.
from ._loader import _SETTINGS_CACHE as _SETTINGS_CACHE

__all__ = [
    "BOOTSTRAP_KEYS",
    "CONFIG_KEYS",
    "REINDEX_KEYS",
    "SECRET_KEYS",
    "Settings",
    "build_settings",
    "current_settings",
    "current_settings_with_version",
    "load_settings",
]
