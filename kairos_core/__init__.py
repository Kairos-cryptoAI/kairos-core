"""Kairos Core — shared contracts, message bus, config and logging.

This package is the single source of truth for the data structures that flow
between Kairos layers (Scouts -> Router -> Aggregator -> Macro-Strategist ->
Risk Manager -> Execution Engine). Every service depends on it so that the
"compact JSON" exchanged on the bus is strongly typed and versioned.
"""
from __future__ import annotations

__version__ = "0.1.0"

from .enums import (
    ReasoningEffort,
    RouterMode,
    SystemMode,
    Side,
    OrderSide,
    ImpactDirection,
    MarketRegime,
    TacticalStatus,
    ReasonCode,
    StrategicTrigger,
    OrderType,
    TimeInForce,
    OrderStatus,
)
from .topics import Topics, ALL_TOPICS
from .contracts import (
    KairosMessage,
    MarketSnapshot,
    OrderBookSummary,
    DerivativesMetrics,
    TechnicalIndicators,
    SentimentSignal,
    RouterDecision,
    TacticalCommand,
    GridAdjustment,
    StrategicAllocation,
    OrderIntent,
    ValidatedOrder,
    ExecutionReport,
)

__all__ = [
    "__version__",
    "ReasoningEffort", "RouterMode", "SystemMode", "Side", "OrderSide",
    "ImpactDirection", "MarketRegime", "TacticalStatus", "ReasonCode",
    "StrategicTrigger", "OrderType", "TimeInForce", "OrderStatus",
    "Topics", "ALL_TOPICS",
    "KairosMessage", "MarketSnapshot", "OrderBookSummary", "DerivativesMetrics",
    "TechnicalIndicators", "SentimentSignal", "RouterDecision", "TacticalCommand",
    "GridAdjustment", "StrategicAllocation", "OrderIntent", "ValidatedOrder",
    "ExecutionReport",
]
