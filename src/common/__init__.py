"""Shared infrastructure for every daemon and the search side.

``common`` is the leaf package of the backend (CODE_GUIDELINES §2.1). It holds
the cross-cutting building blocks: environment configuration (:mod:`.config`),
the Paperless-ngx API client (:mod:`.paperless`), the LLM and embedding wrappers
(:mod:`.llm`, :mod:`.embeddings`), retry logic (:mod:`.retry`), the polling loop
(:mod:`.daemon_loop`), tag operations (:mod:`.tags`), concurrency guards
(:mod:`.concurrency`), preflight checks (:mod:`.preflight`), structured logging
(:mod:`.logging_config`), and the shared daemon startup sequence
(:mod:`.bootstrap`), and the best-effort daemon heartbeat (:mod:`.heartbeat`).

Allowed dependencies: the standard library and the project's third-party
runtime dependencies (``httpx``, ``openai``, ``structlog``, ``Pillow``,
``pdf2image``), plus the ``appdb`` package — :mod:`common.config` reads the
application database's ``config`` table to build :class:`Settings`, and
:mod:`common.heartbeat` writes the ``daemon_status`` heartbeat table
(web-redesign spec §5, Waves 4 and 6). ``appdb`` is a leaf package alongside
``common`` and imports nothing from any daemon, so this does not create a
cycle. **Forbidden:** any import from ``store``, ``ocr``, ``classifier``,
``indexer``, or ``search``; FastAPI; and business logic specific to a single
daemon. ``store`` in particular stays barred — it is the search-index database,
not the application database. The ``appdb`` imports are the deferred ones inside
:func:`common.config.load_settings` and :func:`common.config.current_settings`.
"""

from __future__ import annotations

from .config import Settings
from .paperless import PaperlessClient

__all__ = [
    "PaperlessClient",
    "Settings",
]
