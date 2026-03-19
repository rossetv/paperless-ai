"""Structlog and stdlib logging configuration (console or JSON output)."""

from __future__ import annotations

import logging
import sys
import structlog

from .config import Settings


def configure_logging(settings: Settings) -> None:
    """
    Set up structured logging for both structlog and stdlib loggers.

    Must be called once at daemon startup, before any log output.

    - Adds ISO timestamps, log level, and logger name to every event.
    - Routes stdlib ``logging`` records through the structlog formatter.
    - Suppresses noisy third-party loggers.
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        # This must be the last processor in the chain
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    # Configure structlog
    structlog.configure(
        processors=shared_processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure the chosen formatter
    if settings.LOG_FORMAT == "json":
        formatter = structlog.stdlib.ProcessorFormatter(
            # These run after the processors defined above
            processor=structlog.processors.JSONRenderer(),
        )
    else:  # console
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=True),
        )

    # Configure the root logger
    root_logger = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.LOG_LEVEL)

    # Suppress noisy logs from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    for logger_name in ("openai", "openai._base_client"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.setLevel(logging.WARNING)
        logger.propagate = True
