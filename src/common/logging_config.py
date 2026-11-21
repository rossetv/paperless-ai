"""Structlog and stdlib logging configuration (console or JSON output)."""

from __future__ import annotations

import logging
import sys
import structlog
from structlog.types import Processor

from .config import Settings


def configure_logging(settings: Settings) -> None:
    """Route structlog and stdlib logging through one formatter on stdout.

    Call once at daemon startup, before any log output.
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        # Must be the last processor in the chain.
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    structlog.configure(
        processors=shared_processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    if settings.LOG_FORMAT == "json":
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
        )
    else:  # console
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=True),
        )

    # Clear existing handlers so a repeated call does not duplicate every line.
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.LOG_LEVEL)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    for logger_name in ("openai", "openai._base_client"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.setLevel(logging.WARNING)
        logger.propagate = True
