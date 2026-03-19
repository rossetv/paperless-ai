"""Shared daemon startup sequence: config, logging, preflight, and stale-lock recovery.

Boot order (enforced by :func:`bootstrap_daemon`)::

    1. Settings          – parse and validate environment variables
    2. Logging           – configure structlog / stdlib logging
    3. Libraries         – initialise the OpenAI client (``_openai_holder``)
    4. Signal handlers   – register SIGTERM / SIGINT
    5. Concurrency       – ``llm_limiter.init()``
    6. Preflight checks  – verify Paperless-ngx connectivity and tags
    7. Stale-lock recovery

Steps 3 and 5 initialise module-global singletons that raise ``RuntimeError``
if used before their init functions are called.  The order above guarantees
that dependents are ready before any consumer code runs.
"""

from __future__ import annotations

from typing import Callable

import structlog

from .concurrency import llm_limiter
from .config import Settings
from .library_setup import setup_libraries
from .logging_config import configure_logging
from .paperless import PaperlessClient
from .preflight import PreflightError, run_preflight_checks
from .shutdown import register_signal_handlers
from .stale_lock import recover_stale_locks

log = structlog.get_logger(__name__)


def bootstrap_daemon(
    *,
    get_processing_tag_id: Callable[[Settings], int | None],
    get_pre_tag_id: Callable[[Settings], int],
) -> tuple[Settings, PaperlessClient] | None:
    """Run the shared daemon startup. Returns (settings, client) or None on failure.

    Initialization order: Settings → logging → libraries (OpenAI client,
    concurrency limiter) → signal handlers → preflight → stale-lock recovery.

    *get_processing_tag_id* and *get_pre_tag_id* are callables that extract
    the relevant tag IDs from the loaded settings, avoiding stringly-typed
    ``getattr`` lookups.
    """
    try:
        settings = Settings()
        configure_logging(settings)
        setup_libraries(settings)
        register_signal_handlers()
        llm_limiter.init(settings.LLM_MAX_CONCURRENT)
    except ValueError as e:
        log.error("Configuration error", error=e)
        return None

    client = PaperlessClient(settings)
    try:
        run_preflight_checks(settings, client)
    except PreflightError as e:
        log.error("Preflight check failed", error=str(e))
        client.close()
        return None

    recover_stale_locks(
        client,
        processing_tag_id=get_processing_tag_id(settings),
        pre_tag_id=get_pre_tag_id(settings),
    )

    return settings, client
