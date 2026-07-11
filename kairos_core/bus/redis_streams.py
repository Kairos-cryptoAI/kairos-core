"""Redis Streams bus — the production transport.

Each topic is a Redis Stream. Consumers read through a consumer group so that
work is shared and unacked messages can be re-delivered (XAUTOCLAIM) after a
crash. Payloads are stored as a single ``data`` field containing JSON.
"""
from __future__ import annotations

import json
import time
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

    async def _reclaim_stale(
        self, topic: str, group: str, consumer: str, *, min_idle_ms: int
    ) -> list[tuple[str, dict]]:
        """XAUTOCLAIM messages another consumer read but never acked (crash recovery)."""
        try:
            _cursor, messages, _deleted = await self._redis.xautoclaim(
                topic, group, consumer, min_idle_time=min_idle_ms, start_id="0-0", count=16
            )
        except Exception:  # NOGROUP before first publish, older redis servers, etc.
            return []
        return [(msg_id, fields) for msg_id, fields in messages if fields]

    async def subscribe(  # type: ignore[override]
        self,
        topic: str,
        *,
        group: str | None = None,
        consumer: str | None = None,
        block_ms: int = 5000,
        reclaim_idle_ms: int = 60_000,
        reclaim_every_s: float = 30.0,
    ) -> AsyncIterator[BusEnvelope]:
        group = group or "default"
        consumer = consumer or "c1"
        await self._ensure_group(topic, group)
        last_reclaim = 0.0
        while True:
            # Periodically steal messages stuck in another consumer's PEL after a crash.
            now = time.monotonic()
            if now - last_reclaim >= reclaim_every_s:
                last_reclaim = now
                for msg_id, fields in await self._reclaim_stale(
                    topic, group, consumer, min_idle_ms=reclaim_idle_ms
                ):
                    payload = json.loads(fields.get("data", "{}"))
                    yield BusEnvelope(
                        id=msg_id, topic=topic, payload=payload,
                        meta={"group": group, "reclaimed": True},
                    )
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
