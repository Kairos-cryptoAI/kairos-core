"""Message-bus abstraction and concrete backends."""
from __future__ import annotations

from .base import BusEnvelope, MessageBus
from .inmemory import InMemoryBus
from .factory import build_bus

__all__ = ["BusEnvelope", "MessageBus", "InMemoryBus", "build_bus"]
