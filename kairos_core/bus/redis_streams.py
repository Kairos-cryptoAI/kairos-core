"""Redis Streams bus — the production transport.

Each topic is a Redis Stream. Consumers read through a consumer group so that
work is shared and unacked messages can be re-delivered (XAUTOCLAIM) after a
crash. Payloads are stored as a single ``data`` field containing JSON.
"""

from __future__ import annotations

import json
import os
import socket
import time
from collections.abc import AsyncIterator
from typing import cast

from redis import asyncio as aioredis
from redis.exceptions import ResponseError

from .base import BusEnvelope, MessageBus, Publishable


class RedisStreamsBus(MessageBus):
    def __init__(self, url: str = "redis://localhost:6379/0", *, maxlen: int = 10_000) -> None:
        self._redis = aioredis.from_url(url, decode_responses=True)
        self._maxlen = maxlen
        self._groups_ready: set[tuple[str, str]] = set()
        self._reclaim_cursors: dict[tuple[str, str], str] = {}
        self._instance_id = f"{socket.gethostname()}-{os.getpid()}"

    async def publish(self, topic: str, message: Publishable) -> str:
        payload = self._to_payload(message)
        message_id = await self._redis.xadd(
            topic,
            {"data": json.dumps(payload)},
            maxlen=self._maxlen,
            approximate=True,
            ref_policy="ACKED",
        )
        return message_id.decode() if isinstance(message_id, bytes) else message_id

    async def _ensure_group(self, topic: str, group: str) -> None:
        key = (topic, group)
        if key in self._groups_ready:
            return
        try:
            await self._redis.xgroup_create(topic, group, id="0", mkstream=True)
        except ResponseError as exc:  # group already exists
            if "BUSYGROUP" not in str(exc):
                raise
        self._groups_ready.add(key)

    async def _reclaim_stale(
        self, topic: str, group: str, consumer: str, *, min_idle_ms: int
    ) -> list[tuple[str, dict[str, str], int]]:
        """XAUTOCLAIM messages another consumer read but never acked (crash recovery)."""
        cursor_key = (topic, group)
        start_id = self._reclaim_cursors.get(cursor_key, "0-0")
        try:
            cursor, messages, _deleted = cast(
                tuple[str, list[tuple[str, dict[str, str]]], list[str]],
                await self._redis.xautoclaim(
                    topic,
                    group,
                    consumer,
                    min_idle_time=min_idle_ms,
                    start_id=start_id,
                    count=16,
                ),
            )
        except ResponseError as exc:
            if "NOGROUP" in str(exc):
                self._groups_ready.discard(cursor_key)
                self._reclaim_cursors.pop(cursor_key, None)
                return []
            raise

        self._reclaim_cursors[cursor_key] = cursor
        reclaimed: list[tuple[str, dict[str, str], int]] = []
        for msg_id, fields in messages:
            if fields:
                reclaimed.append((msg_id, fields, await self._delivery_attempt(topic, group, msg_id)))
        return reclaimed

    async def _delivery_attempt(self, topic: str, group: str, message_id: str) -> int:
        """Return Redis' delivery counter for a pending message."""
        pending = await self._redis.xpending_range(topic, group, message_id, message_id, 1)
        if not pending:
            return 2
        return max(2, int(pending[0].get("times_delivered", 2)))

    async def subscribe(  # type: ignore[override]
        self,
        topic: str,
        *,
        group: str | None = None,
        consumer: str | None = None,
        block_ms: int = 5000,
        reclaim_idle_ms: int = 180_000,
        reclaim_every_s: float = 30.0,
    ) -> AsyncIterator[BusEnvelope]:
        group = group or "default"
        consumer = f"{consumer or 'consumer'}-{self._instance_id}"
        await self._ensure_group(topic, group)
        last_reclaim = 0.0
        while True:
            # Periodically steal messages stuck in another consumer's PEL after a crash.
            now = time.monotonic()
            if now - last_reclaim >= reclaim_every_s:
                last_reclaim = now
                for msg_id, fields, attempt in await self._reclaim_stale(
                    topic, group, consumer, min_idle_ms=reclaim_idle_ms
                ):
                    payload = json.loads(fields.get("data", "{}"))
                    yield BusEnvelope(
                        id=msg_id,
                        topic=topic,
                        payload=payload,
                        attempt=attempt,
                        meta={"group": group, "reclaimed": True},
                    )
            resp = cast(
                list[tuple[str, list[tuple[str, dict[str, str]]]]],
                await self._redis.xreadgroup(group, consumer, {topic: ">"}, count=16, block=block_ms),
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
