"""Shared startup sequences for the project's entry points.

:func:`bootstrap_process` is the per-process startup run by every daemon and by
the search server::

    1. Settings          – parse and validate environment variables
    2. Logging           – configure structlog / stdlib logging
    3. Libraries         – initialise the OpenAI client (``_openai_holder``)
    4. Signal handlers   – register SIGTERM / SIGINT
    5. Concurrency       – ``llm_limiter.init()``

:func:`bootstrap_daemon` extends it with the steps a tag daemon also needs::

    6. Paperless client
    7. Preflight checks  – verify Paperless-ngx connectivity and tags
    8. Stale-lock recovery

Steps 3 and 5 initialise singletons that raise ``RuntimeError`` if used before
init, so the order is fixed and defined only here.
"""

from __future__ import annotations

from collections.abc import Callable

import structlog

from .concurrency import llm_limiter
from .config import Settings, current_settings
from .library_setup import setup_libraries
from .logging_config import configure_logging
from .paperless import PaperlessClient
from .preflight import PreflightError, run_preflight_checks
from .shutdown import register_signal_handlers
from .stale_lock import recover_stale_locks

log = structlog.get_logger(__name__)


def bootstrap_process() -> Settings:
    """Run the per-process startup shared by every entry point.

    Returns the initial settings snapshot; consumers that must see later config
    changes call :func:`~common.config.current_settings` again at a safe
    boundary.

    Raises:
        ValueError: A required configuration key is missing or a value is
            invalid.
    """
    settings = current_settings()
    configure_logging(settings)
    setup_libraries(settings)
    register_signal_handlers()
    llm_limiter.init(settings.LLM_MAX_CONCURRENT)
    return settings


def bootstrap_daemon(
    *,
    get_processing_tag_id: Callable[[Settings], int | None],
    get_pre_tag_id: Callable[[Settings], int],
) -> tuple[Settings, PaperlessClient] | None:
    """Run the tag-daemon startup. Returns (settings, client) or None on failure.

    The two callables pick the daemon's tag ids out of the loaded settings.
    """
    try:
        settings = bootstrap_process()
    except ValueError as exc:
        log.error("Configuration error", error=str(exc))
        return None

    client = PaperlessClient(settings)
    try:
        run_preflight_checks(settings, client)
    except PreflightError as exc:
        log.error("Preflight check failed", error=str(exc))
        client.close()
        return None

    recover_stale_locks(
        client,
        processing_tag_id=get_processing_tag_id(settings),
        pre_tag_id=get_pre_tag_id(settings),
    )

    return settings, client
