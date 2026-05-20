"""Shared infrastructure for every daemon and the search side.

``common`` is the leaf package of the backend (CODE_GUIDELINES §2.1). It holds
the cross-cutting building blocks: environment configuration (:mod:`.config`),
the Paperless-ngx API client (:mod:`.paperless`), the LLM and embedding wrappers
(:mod:`.llm`, :mod:`.embeddings`), retry logic (:mod:`.retry`), the polling loop
(:mod:`.daemon_loop`), tag operations (:mod:`.tags`), concurrency guards
(:mod:`.concurrency`), preflight checks (:mod:`.preflight`), structured logging
(:mod:`.logging_config`), and the shared daemon startup sequence
(:mod:`.bootstrap`).

Allowed dependencies: the standard library and the project's third-party
runtime dependencies (``httpx``, ``openai``, ``structlog``, ``Pillow``,
``pdf2image``). **Forbidden:** any import from ``store``, ``ocr``,
``classifier``, ``indexer``, or ``search``; any ``sqlite3`` import; FastAPI; and
business logic specific to a single daemon. ``common`` imports nothing from
another internal package — every other package depends on it, not the reverse.
"""

from __future__ import annotations

from .config import Settings
from .paperless import PaperlessClient

__all__ = [
    "PaperlessClient",
    "Settings",
]
