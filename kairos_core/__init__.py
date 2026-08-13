"""Kairos Core — shared contracts, message bus, config and logging.

This package is the single source of truth for the data structures that flow
between Kairos layers (Scouts -> Router -> Aggregator -> Macro-Strategist ->
Risk Manager -> Execution Engine). Every service depends on it so that the
"compact JSON" exchanged on the bus is strongly typed and versioned.
"""

from __future__ import annotations

__version__ = "0.2.0"

from .contracts import (
    DerivativesMetrics,
    ExecutionReport,
    GridAdjustment,
    KairosMessage,
    LLMHealthEvent,
    MarketSnapshot,
    OrderBookSummary,
    OrderIntent,
    RouterDecision,
    SentimentSignal,
    StrategicAllocation,
    TacticalCommand,
    TechnicalIndicators,
    ValidatedOrder,
)
from .enums import (
    ImpactDirection,
    MarketRegime,
    OrderSide,
    OrderStatus,
    OrderType,
    ReasonCode,
    ReasoningEffort,
    RouterMode,
    Side,
    StrategicTrigger,
    SystemMode,
    TacticalStatus,
    TimeInForce,
)
from .topics import ALL_TOPICS, Topics

__all__ = [
    "__version__",
    "ReasoningEffort",
    "RouterMode",
    "SystemMode",
    "Side",
    "OrderSide",
    "ImpactDirection",
    "MarketRegime",
    "TacticalStatus",
    "ReasonCode",
    "StrategicTrigger",
    "OrderType",
    "TimeInForce",
    "OrderStatus",
    "Topics",
    "ALL_TOPICS",
    "KairosMessage",
    "MarketSnapshot",
    "OrderBookSummary",
    "DerivativesMetrics",
    "TechnicalIndicators",
    "SentimentSignal",
    "RouterDecision",
    "TacticalCommand",
    "GridAdjustment",
    "StrategicAllocation",
    "OrderIntent",
    "ValidatedOrder",
    "ExecutionReport",
    "LLMHealthEvent",
]
