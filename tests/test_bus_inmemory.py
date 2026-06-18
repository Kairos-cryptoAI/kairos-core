"""Pub/sub behaviour of the in-memory bus."""
import asyncio

import pytest

from kairos_core.bus import InMemoryBus
from kairos_core.contracts import SentimentSignal
from kairos_core.enums import ImpactDirection
from kairos_core.topics import Topics


@pytest.mark.asyncio
async def test_publish_subscribe_round_trip():
    bus = InMemoryBus()
    received = []

    async def consumer():
        async for env in bus.subscribe(Topics.SENTIMENT_SIGNAL):
            received.append(env)
            await bus.ack(Topics.SENTIMENT_SIGNAL, env)
            break

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)  # let the subscriber register its queue

    sig = SentimentSignal(source="text-scouts", topic="CPI", sentiment=-0.4, impact=ImpactDirection.BEARISH)
    await bus.publish(Topics.SENTIMENT_SIGNAL, sig)
    await asyncio.wait_for(task, timeout=1.0)

    assert len(received) == 1
    assert received[0].payload["topic"] == "CPI"
