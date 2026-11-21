"""The application database (``app.db``): accounts, sessions, API keys and config.

Kept separate from the search index so rebuilding ``index.db`` never destroys
accounts or configuration, and kept out of ``store`` because the OCR and
classifier daemons, which must not import ``store``, read their config from here.
"""

from __future__ import annotations
