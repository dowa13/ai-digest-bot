"""Structured JSON logging via structlog.

Usage:
    from src.shared.logging import get_logger
    log = get_logger(__name__)
    log.info("pipeline_step", step="fetch", count=42)
"""

from __future__ import annotations

import logging
import sys

import structlog

from src.shared.config import get_settings


def configure() -> None:
    """Configure structlog + stdlib logging once per process."""
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level,
        format="%(message)s",
        stream=sys.stdout,
    )

    timestamper = structlog.processors.TimeStamper(fmt="iso")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configured = False


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a configured structured logger."""
    global _configured
    if not _configured:
        configure()
        _configured = True
    return structlog.get_logger(name)  # type: ignore[no-any-return]
