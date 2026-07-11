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

    async def xgroup_create(self, *a, **k):
        return True

    async def xautoclaim(self, topic, group, consumer, min_idle_time, start_id, count):
        self.autoclaim_calls += 1
        stale, self.stale = self.stale, []
        return "0-0", stale, []

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
    assert got[1].payload["kind"] == "fresh"
    assert bus._redis.autoclaim_calls >= 1
