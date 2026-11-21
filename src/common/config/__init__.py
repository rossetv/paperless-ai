"""Configuration for every daemon and the search server.

:func:`load_settings` layers the ``app.db`` config table over the environment
(table, then env var, then default); :meth:`Settings.from_environment` reads the
environment alone. Both parse, validate and clamp through the same code and
raise ``ValueError`` naming the offending variable.
"""

from __future__ import annotations

from ._catalogue import BOOTSTRAP_KEYS, CONFIG_KEYS, REINDEX_KEYS, SECRET_KEYS
from ._loader import current_settings, current_settings_with_version, load_settings
from ._settings import Settings, build_settings

# Re-exported for tests that reset the hot-load cache between cases; private, so
# absent from __all__. The redundant alias marks the re-export as intentional.
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
