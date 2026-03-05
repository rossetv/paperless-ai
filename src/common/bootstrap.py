"""Shared daemon startup sequence: config, logging, preflight, and stale-lock recovery."""

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
    """Run the shared daemon startup. Returns (settings, client) or None on failure."""
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
