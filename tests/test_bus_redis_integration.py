"""Real Redis Streams integration tests, enabled when KAIROS_TEST_REDIS_URL is set."""
from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

pytest.importorskip("redis")

from kairos_core.bus.redis_streams import RedisStreamsBus  # noqa: E402

REDIS_URL = os.getenv("KAIROS_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not REDIS_URL, reason="KAIROS_TEST_REDIS_URL not configured")


def test_real_redis_publish_consume_ack_and_crash_reclaim():
    async def scenario() -> None:
        topic = f"kairos.test.{uuid4().hex}"
        group = f"group-{uuid4().hex}"
        producer = RedisStreamsBus(REDIS_URL or "")
        crashed = RedisStreamsBus(REDIS_URL or "")
        recovery = RedisStreamsBus(REDIS_URL or "")
        try:
            message_id = await producer.publish(topic, {"message_id": "logical-1", "value": 42})

            first = crashed.subscribe(
                topic, group=group, consumer="crashed", block_ms=50,
                reclaim_idle_ms=10_000, reclaim_every_s=60,
            )
            envelope = await asyncio.wait_for(anext(first), timeout=2)
            assert envelope.id == message_id
            assert envelope.payload["value"] == 42
            await first.aclose()  # deliberately do not ACK: simulate process death

            await asyncio.sleep(0.03)
            second = recovery.subscribe(
                topic, group=group, consumer="recovery", block_ms=50,
                reclaim_idle_ms=1, reclaim_every_s=0,
            )
            reclaimed = await asyncio.wait_for(anext(second), timeout=2)
            assert reclaimed.id == message_id
            assert reclaimed.meta["reclaimed"] is True
            await recovery.ack(topic, reclaimed, group=group)
            await second.aclose()

            pending = await recovery._redis.xpending(topic, group)
            assert pending["pending"] == 0
        finally:
            await producer._redis.delete(topic)
            await producer.close()
            await crashed.close()
            await recovery.close()

    asyncio.run(scenario())


def test_real_redis_consumer_group_delivers_each_message_once_per_group():
    async def scenario() -> None:
        topic = f"kairos.test.{uuid4().hex}"
        group = f"group-{uuid4().hex}"
        bus = RedisStreamsBus(REDIS_URL or "")
        try:
            ids = [await bus.publish(topic, {"sequence": number}) for number in range(3)]
            stream = bus.subscribe(topic, group=group, consumer="worker", block_ms=50)
            received = []
            for _ in ids:
                envelope = await asyncio.wait_for(anext(stream), timeout=2)
                received.append(envelope)
                await bus.ack(topic, envelope, group=group)
            await stream.aclose()
            assert [item.id for item in received] == ids
            assert [item.payload["sequence"] for item in received] == [0, 1, 2]
        finally:
            await bus._redis.delete(topic)
            await bus.close()

    asyncio.run(scenario())
