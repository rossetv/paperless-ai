"""The application database (``app.db``) — accounts, sessions, and config.

``appdb`` owns a SQLite database, separate from the search index
(``index.db``), so that rebuilding the index never destroys user accounts,
API keys, or configuration. Wave 1 puts the ``users`` and ``sessions`` tables
here; later waves add ``api_keys`` (Wave 3) and ``config`` (Wave 4) by
further migrations.

``appdb`` is deliberately **not** part of ``store``: the OCR and classifier
daemons are barred from importing ``store`` (see ``common/__init__.py``), and
Wave 4 needs those daemons to read ``app.db`` config. The migration machinery
here is adapted from ``store.migrations`` — copied, not shared — so the two
databases version independently.

Allowed dependencies: the standard library (notably ``sqlite3``), ``argon2``,
and ``structlog``. Forbidden: any import from ``store``, ``search``,
``indexer``, ``ocr``, ``classifier``; FastAPI; ``httpx``; ``openai``.
"""

from __future__ import annotations
