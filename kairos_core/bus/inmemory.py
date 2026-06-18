"""In-process bus backed by asyncio queues — used in unit tests and demos."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import AsyncIterator, Dict, List

from .base import BusEnvelope, MessageBus, Publishable


class InMemoryBus(MessageBus):
    def __init__(self) -> None:
        self._queues: Dict[str, List[asyncio.Queue]] = defaultdict(list)
        self._counter = 0

    async def publish(self, topic: str, message: Publishable) -> str:
        payload = self._to_payload(message)
        self._counter += 1
        msg_id = f"mem-{self._counter}"
        env = BusEnvelope(id=msg_id, topic=topic, payload=payload)
        for queue in list(self._queues[topic]):
            await queue.put(env)
        return msg_id

    async def subscribe(  # type: ignore[override]
        self,
        topic: str,
        *,
        group: str | None = None,
        consumer: str | None = None,
    ) -> AsyncIterator[BusEnvelope]:
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[topic].append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._queues[topic].remove(queue)

    async def ack(self, topic: str, envelope: BusEnvelope, *, group: str | None = None) -> None:
        # Nothing to do for the in-memory transport.
        return None
