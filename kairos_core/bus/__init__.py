"""Message-bus abstraction and concrete backends."""

from __future__ import annotations

from .base import BusEnvelope, MessageBus
from .factory import build_bus
from .inmemory import InMemoryBus

__all__ = ["BusEnvelope", "MessageBus", "InMemoryBus", "build_bus"]
