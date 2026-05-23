"""Shared startup sequences for the project's entry points.

:func:`bootstrap_process` is the universal per-process startup — steps 1–5
below — run identically by every daemon and by the search server::

    1. Settings          – parse and validate environment variables
    2. Logging           – configure structlog / stdlib logging
    3. Libraries         – initialise the OpenAI client (``_openai_holder``)
    4. Signal handlers   – register SIGTERM / SIGINT
    5. Concurrency       – ``llm_limiter.init()``

:func:`bootstrap_daemon` extends it with the steps a tag daemon also needs::

    6. Paperless client
    7. Preflight checks  – verify Paperless-ngx connectivity and tags
    8. Stale-lock recovery

Steps 3 and 5 initialise module-global singletons that raise ``RuntimeError``
if used before their init functions are called.  The fixed order guarantees
dependents are ready before any consumer code runs; defining it in exactly one
place is what stops an entry point from silently omitting a step.
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

    Builds and validates :class:`~common.config.Settings` via
    :func:`~common.config.current_settings` — the ``config`` table in ``app.db``
    layered over the process environment, hot-loaded so a later config change
    is picked up with no restart. Then configures logging, initialises the
    shared library singletons (the OpenAI client and the LLM concurrency
    limiter), and registers the SIGTERM / SIGINT handlers — the five steps
    every daemon and the search server must perform identically, in this
    order, before any consumer code runs.

    This function is the single source of truth for that sequence.  An entry
    point that re-implemented it inline would drift silently: a dropped
    ``llm_limiter.init()`` is invisible until the first LLM call raises
    ``RuntimeError`` at request time.

    Returns:
        The validated :class:`~common.config.Settings`. The returned value is
        the *initial* snapshot for the one-time startup steps; consumers that
        must see later changes call :func:`~common.config.current_settings`
        again at a safe boundary.

    Raises:
        ValueError: A required configuration key is missing from both ``app.db``
            and the environment, or a value is invalid.
            :func:`bootstrap_daemon` catches this and returns ``None``; the
            search server lets it abort startup loudly.
    """
    # The hot-load accessor: it reads APP_DB_PATH from the environment, layers
    # the config table over the environment, and caches the result keyed by
    # config_version. This first call primes that cache; every later read —
    # a daemon between documents, the search server per request — calls
    # current_settings() again and gets a rebuild only when config changed
    # (web-redesign spec §5). No restart is ever needed.
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

    Extends :func:`bootstrap_process` — the universal per-process startup —
    with the steps a tag daemon also needs: constructing the Paperless client,
    running preflight checks, and recovering stale processing locks.

    *get_processing_tag_id* and *get_pre_tag_id* are callables that extract the
    relevant tag IDs from the loaded settings, avoiding stringly-typed
    ``getattr`` lookups.
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
