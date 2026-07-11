"""Prometheus metrics registry and shared instrumentation."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Default shared registry; each service can override with a custom registry.
_registry = CollectorRegistry(auto_describe=True)


def get_registry() -> CollectorRegistry:
    return _registry


def metrics_text() -> bytes:
    """Export current metrics in Prometheus text format."""
    return generate_latest(_registry)


# ── Service-level metrics ────────────────────────────────────────────────────
bus_messages_received = Counter(
    "kairos_bus_messages_received_total",
    "Total messages consumed from the bus",
    ["service", "topic"],
    registry=_registry,
)

bus_messages_published = Counter(
    "kairos_bus_messages_published_total",
    "Total messages published to the bus",
    ["service", "topic"],
    registry=_registry,
)

bus_processing_duration_seconds = Histogram(
    "kairos_bus_processing_duration_seconds",
    "Time spent processing a single bus message",
    ["service", "topic"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=_registry,
)

bus_pending_messages = Gauge(
    "kairos_bus_pending_messages",
    "Approximate number of pending messages (Redis PEL length, etc.)",
    ["service", "topic"],
    registry=_registry,
)

llm_requests_total = Counter(
    "kairos_llm_requests_total",
    "Total LLM requests",
    ["service", "model", "effort", "result"],  # result=ok|error|timeout|5xx
    registry=_registry,
)

llm_latency_seconds = Histogram(
    "kairos_llm_latency_seconds",
    "LLM request latency",
    ["service", "model", "effort"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
    registry=_registry,
)

# ── Risk-specific metrics ──────────────────────────────────────────────────
risk_commands_total = Counter(
    "kairos_risk_commands_total",
    "Tactical commands received",
    ["service", "symbol", "reason_code"],
    registry=_registry,
)

risk_orders_total = Counter(
    "kairos_risk_orders_total",
    "Validated orders produced",
    ["service", "approved", "reason_code"],  # approved=true|false
    registry=_registry,
)

risk_account_staleness_seconds = Gauge(
    "kairos_risk_account_staleness_seconds",
    "Age of the last reconciled account snapshot",
    ["service"],
    registry=_registry,
)

risk_allocation_staleness_seconds = Gauge(
    "kairos_risk_allocation_staleness_seconds",
    "Age of the last strategic allocation",
    ["service"],
    registry=_registry,
)

# ── Execution-specific metrics ──────────────────────────────────────────────
execution_orders_total = Counter(
    "kairos_execution_orders_total",
    "Orders received by the execution engine",
    ["service", "symbol", "side"],
    registry=_registry,
)

execution_fills_total = Counter(
    "kairos_execution_fills_total",
    "Fills reported to the bus",
    ["service", "symbol", "side"],
    registry=_registry,
)

execution_state_transitions = Counter(
    "kairos_execution_state_transitions_total",
    "Order state transitions",
    ["service", "from_state", "to_state"],
    registry=_registry,
)


# ── Helpers for async measurement ─────────────────────────────────────────────
@asynccontextmanager
async def observe_duration(histogram: Histogram, **labels) -> AsyncIterator[None]:
    """Context manager for timing async operations."""
    start = time.monotonic()
    try:
        yield
    finally:
        histogram.labels(**labels).observe(time.monotonic() - start)
