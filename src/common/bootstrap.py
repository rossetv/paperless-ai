"""
Daemon Bootstrap
================

Shared startup sequence for both the OCR and classification daemons.

Both daemons follow the same bootstrap pattern:

1. Load configuration from environment variables.
2. Configure structured logging.
3. Set up third-party libraries (OpenAI, Pillow).
4. Register signal handlers for graceful shutdown.
5. Initialise the LLM concurrency limiter.
6. Run preflight checks (Paperless reachable, tags exist, LLM reachable).
7. Recover stale processing-lock tags from a previous crash.

This module extracts that shared logic so the daemon entry points stay thin.
"""

from __future__ import annotations

import structlog

from .concurrency import init_llm_semaphore
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
    processing_tag_id_attr: str,
    pre_tag_id_attr: str,
) -> tuple[Settings, PaperlessClient] | None:
    """Run the shared daemon startup sequence.

    Args:
        processing_tag_id_attr: Name of the Settings attribute holding the
            processing-lock tag ID (e.g. ``"OCR_PROCESSING_TAG_ID"``).
        pre_tag_id_attr: Name of the Settings attribute holding the
            queue tag ID (e.g. ``"PRE_TAG_ID"``).

    Returns:
        A ``(settings, list_client)`` tuple on success, or ``None`` if startup
        fails (configuration error or fatal preflight failure).
    """
    try:
        settings = Settings()
        configure_logging(settings)
        setup_libraries(settings)
        register_signal_handlers()
        init_llm_semaphore(settings.LLM_MAX_CONCURRENT)
    except ValueError as e:
        log.error("Configuration error", error=e)
        return None

    list_client = PaperlessClient(settings)
    try:
        run_preflight_checks(settings, list_client)
    except PreflightError as e:
        log.error("Preflight check failed", error=str(e))
        list_client.close()
        return None

    recover_stale_locks(
        list_client,
        processing_tag_id=getattr(settings, processing_tag_id_attr),
        pre_tag_id=getattr(settings, pre_tag_id_attr),
    )

    return settings, list_client
