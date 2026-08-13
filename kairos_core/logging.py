"""Structured logging setup.

Emits JSON in production (easy to ship to Loki / ELK) and a colourful console
renderer in dev. Falls back to the stdlib logger if structlog is unavailable.
"""

from __future__ import annotations

import logging

import structlog
from structlog.typing import Processor


def configure_logging(level: str = "INFO", *, json_logs: bool = True, service: str = "kairos") -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        timestamper,
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=shared + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
