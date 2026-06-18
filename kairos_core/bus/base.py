"""Transport-agnostic message bus interface.

The bus is intentionally dumb: it moves JSON payloads between topics. Services
are responsible for validating payloads back into the right
:class:`~kairos_core.contracts.base.KairosMessage` subclass. This keeps the
core free of any per-message-type coupling.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import AsyncIterator, Union

from ..contracts.base import KairosMessage

Publishable = Union[KairosMessage, dict]


@dataclass(slots=True)
class BusEnvelope:
    """A single message pulled from the bus."""

    id: str
    topic: str
    payload: dict
    attempt: int = 1
    meta: dict = field(default_factory=dict)


class MessageBus(abc.ABC):
    """Abstract pub/sub transport.

    Implementations must provide at-least-once delivery semantics and an
    explicit ``ack`` so that a crashing consumer does not lose messages.
    """

    @staticmethod
    def _to_payload(message: Publishable) -> dict:
        if isinstance(message, KairosMessage):
            return message.to_payload()
        if isinstance(message, dict):
            return message
        raise TypeError(f"Cannot publish object of type {type(message)!r}")

    @abc.abstractmethod
    async def publish(self, topic: str, message: Publishable) -> str:
        """Publish ``message`` to ``topic``; return the bus message id."""

    @abc.abstractmethod
    def subscribe(
        self,
        topic: str,
        *,
        group: str | None = None,
        consumer: str | None = None,
    ) -> AsyncIterator[BusEnvelope]:
        """Yield :class:`BusEnvelope` objects from ``topic`` forever."""

    @abc.abstractmethod
    async def ack(self, topic: str, envelope: BusEnvelope, *, group: str | None = None) -> None:
        """Acknowledge successful processing of ``envelope``."""

    async def close(self) -> None:  # pragma: no cover - optional override
        return None
