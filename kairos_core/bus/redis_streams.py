"""Redis Streams bus — the production transport.

Each topic is a Redis Stream. Consumers read through a consumer group so that
work is shared and unacked messages can be re-delivered (XAUTOCLAIM) after a
crash. Payloads are stored as a single ``data`` field containing JSON.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

from .base import BusEnvelope, MessageBus, Publishable

try:  # redis is an optional dependency at import time
    from redis import asyncio as aioredis
except Exception:  # pragma: no cover
    aioredis = None  # type: ignore


class RedisStreamsBus(MessageBus):
    def __init__(self, url: str = "redis://localhost:6379/0", *, maxlen: int = 10_000) -> None:
        if aioredis is None:  # pragma: no cover
            raise RuntimeError("redis is not installed; `pip install redis>=5`. ")
        self._redis = aioredis.from_url(url, decode_responses=True)
        self._maxlen = maxlen
        self._groups_ready: set[tuple[str, str]] = set()

    async def publish(self, topic: str, message: Publishable) -> str:
        payload = self._to_payload(message)
        return await self._redis.xadd(
            topic, {"data": json.dumps(payload)}, maxlen=self._maxlen, approximate=True
        )

    async def _ensure_group(self, topic: str, group: str) -> None:
        key = (topic, group)
        if key in self._groups_ready:
            return
        try:
            await self._redis.xgroup_create(topic, group, id="0", mkstream=True)
        except Exception as exc:  # group already exists
            if "BUSYGROUP" not in str(exc):
                raise
        self._groups_ready.add(key)

    async def subscribe(  # type: ignore[override]
        self,
        topic: str,
        *,
        group: str | None = None,
        consumer: str | None = None,
        block_ms: int = 5000,
    ) -> AsyncIterator[BusEnvelope]:
        group = group or "default"
        consumer = consumer or "c1"
        await self._ensure_group(topic, group)
        while True:
            resp = await self._redis.xreadgroup(
                group, consumer, {topic: ">"}, count=16, block=block_ms
            )
            if not resp:
                continue
            for _stream, messages in resp:
                for msg_id, fields in messages:
                    payload = json.loads(fields.get("data", "{}"))
                    yield BusEnvelope(id=msg_id, topic=topic, payload=payload, meta={"group": group})

    async def ack(self, topic: str, envelope: BusEnvelope, *, group: str | None = None) -> None:
        group = group or envelope.meta.get("group", "default")
        await self._redis.xack(topic, group, envelope.id)

    async def close(self) -> None:
        await self._redis.aclose()
