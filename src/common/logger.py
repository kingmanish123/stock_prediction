"""Structured logging via structlog (JSON to file + pretty to terminal)."""
import logging
import sys
from pathlib import Path

import structlog

from . import config


def setup_logging(run_id: str | None = None) -> None:
    """Configure structlog once at startup."""
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

    # root Python logger config (structlog wraps this)
    logging.basicConfig(
        format="%(message)s",
        level=level,
        stream=sys.stdout,
    )

    # shared processors
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if run_id:
        structlog.contextvars.bind_contextvars(run_id=run_id)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a logger. Call after setup_logging()."""
    return structlog.get_logger(name)
