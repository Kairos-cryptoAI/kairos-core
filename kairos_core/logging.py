"""Structured logging setup.

Emits JSON in production (easy to ship to Loki / ELK) and a colourful console
renderer in dev. Falls back to the stdlib logger if structlog is unavailable.
"""
from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO", *, json_logs: bool = True, service: str = "kairos") -> None:
    try:
        import structlog
    except Exception:  # pragma: no cover
        logging.basicConfig(level=level, stream=sys.stdout,
                            format="%(asctime)s %(levelname)s %(name)s %(message)s")
        return

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        timestamper,
    ]
    renderer = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=shared + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str | None = None):
    try:
        import structlog

        return structlog.get_logger(name)
    except Exception:  # pragma: no cover
        return logging.getLogger(name)
