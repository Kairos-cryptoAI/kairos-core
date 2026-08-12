"""XAUTOCLAIM crash-recovery behaviour of RedisStreamsBus (fake redis client)."""

import asyncio
import json

import pytest

pytest.importorskip("redis")

from kairos_core.bus.redis_streams import RedisStreamsBus  # noqa: E402


class FakeRedis:
    """Minimal async stand-in covering the calls subscribe() makes."""

    def __init__(self):
        self.stale = [("1-0", {"data": json.dumps({"kind": "stale"})})]
        self.fresh = [("2-0", {"data": json.dumps({"kind": "fresh"})})]
        self.autoclaim_calls = 0
        self.autoclaim_start_ids = []
        self.next_cursor = "0-0"
        self.consumers = []

    async def xgroup_create(self, *a, **k):
        return True

    async def xautoclaim(self, topic, group, consumer, min_idle_time, start_id, count):
        self.autoclaim_calls += 1
        self.autoclaim_start_ids.append(start_id)
        self.consumers.append(consumer)
        stale, self.stale = self.stale, []
        return self.next_cursor, stale, []

    async def xpending_range(self, topic, group, min_id, max_id, count):
        return [{"message_id": min_id, "times_delivered": 3}]

    async def xreadgroup(self, group, consumer, streams, count, block):
        fresh, self.fresh = self.fresh, []
        if not fresh:
            await asyncio.sleep(0.01)
            return []
        return [(list(streams)[0], fresh)]

    async def xack(self, *a):
        return 1

    async def aclose(self):
        return None


def _bus_with_fake():
    bus = RedisStreamsBus.__new__(RedisStreamsBus)
    bus._redis = FakeRedis()
    bus._maxlen = 100
    bus._groups_ready = set()
    bus._reclaim_cursors = {}
    bus._instance_id = "test-instance"
    return bus


def test_subscribe_reclaims_stale_pending_messages_first():
    bus = _bus_with_fake()

    async def run():
        got = []
        async for env in bus.subscribe("topic", group="g", consumer="c2"):
            got.append(env)
            if len(got) == 2:
                break
        return got

    got = asyncio.run(asyncio.wait_for(run(), timeout=2))
    assert got[0].payload["kind"] == "stale"
    assert got[0].meta.get("reclaimed") is True
    assert got[0].attempt == 3
    assert got[1].payload["kind"] == "fresh"
    assert bus._redis.autoclaim_calls >= 1
    assert bus._redis.consumers == ["c2-test-instance"]


def test_reclaim_cursor_advances_between_batches():
    bus = _bus_with_fake()
    bus._redis.next_cursor = "9-0"

    async def run():
        await bus._reclaim_stale("topic", "g", "consumer", min_idle_ms=1)
        bus._redis.next_cursor = "0-0"
        await bus._reclaim_stale("topic", "g", "consumer", min_idle_ms=1)

    asyncio.run(run())

    assert bus._redis.autoclaim_start_ids == ["0-0", "9-0"]
