"""Build the configured bus backend from settings."""
from __future__ import annotations

from ..config import CoreSettings
from .base import MessageBus
from .inmemory import InMemoryBus


def build_bus(settings: CoreSettings | None = None) -> MessageBus:
    settings = settings or CoreSettings()
    backend = settings.bus_backend.lower()
    if backend == "memory":
        return InMemoryBus()
    if backend == "redis":
        from .redis_streams import RedisStreamsBus

        return RedisStreamsBus(settings.redis_url)
    raise ValueError(f"Unknown bus backend: {settings.bus_backend!r}")
